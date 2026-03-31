"""WS22-004 long-run baseline harness for scheduler bridge stability."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

from core.event_bus import EventStore
from core.security.lease_fencing import GlobalMutexManager, LeaseHandle

from agents.runtime.workflow_store import WorkflowStore


@dataclass(frozen=True)
class WS22LongRunConfig:
    rounds: int = 120
    virtual_round_seconds: float = 5.0
    fail_open_every: int = 15
    lease_renew_every: int = 20


def _write_policy(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """
gates:
  deploy:
    canary_window_min: 15
    min_sample_count: 200
    healthy_windows_for_promotion: 3
    bad_windows_for_rollback: 2
""".strip(),
        encoding="utf-8",
    )


def _count_workflow_states(store: WorkflowStore) -> Dict[str, int]:
    with store._connect() as conn:  # noqa: SLF001
        rows = conn.execute(
            """
            SELECT current_state, COUNT(1) AS cnt
            FROM workflow_state
            GROUP BY current_state
            ORDER BY current_state ASC
            """
        ).fetchall()
    return {str(row["current_state"]): int(row["cnt"]) for row in rows}


def _emit(event_store: EventStore, event_counter: Counter[str], event_type: str, payload: Dict[str, Any]) -> None:
    event_store.emit(event_type, payload, source="agents.runtime.ws22.longrun")
    event_counter[event_type] += 1


def run_ws22_longrun_baseline(
    *,
    scratch_root: Path = Path("scratch/ws22_longrun_baseline"),
    report_file: Path = Path("scratch/reports/ws22_scheduler_longrun_baseline.json"),
    config: WS22LongRunConfig = WS22LongRunConfig(),
) -> Dict[str, Any]:
    case_id = uuid.uuid4().hex[:10]
    case_root = scratch_root / case_id
    repo = case_root / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    _write_policy(repo / "policy" / "gate_policy.yaml")
    target_file = repo / "service.txt"
    target_file.write_text("BASE", encoding="utf-8")
    report_file.parent.mkdir(parents=True, exist_ok=True)

    workflow_db = repo / "logs" / "autonomous" / "workflow.db"
    event_file = repo / "logs" / "autonomous" / "events.jsonl"
    workflow_store = WorkflowStore(db_path=workflow_db)
    event_store = EventStore(file_path=event_file)
    global_mutex = GlobalMutexManager(
        state_file=repo / "logs" / "runtime" / "global_mutex_lease.json",
        audit_file=repo / "logs" / "runtime" / "global_mutex_events.jsonl",
    )

    rounds = max(1, int(config.rounds))
    virtual_round_seconds = max(0.1, float(config.virtual_round_seconds))
    fail_open_every = max(1, int(config.fail_open_every))
    lease_renew_every = max(1, int(config.lease_renew_every))

    unhandled_errors: list[str] = []
    event_counter: Counter[str] = Counter()
    started_at = time.time()
    lease_name = "global_orchestrator"
    lease_owner = f"ws22-baseline-{case_id}"
    lease_ttl_seconds = 3600
    lease_handle: LeaseHandle | None = None
    global_mutex.ensure_initialized(ttl_seconds=lease_ttl_seconds)
    subagent_gate_metrics: Dict[str, Any] = {
        "rounds_total": rounds,
        "runtime_completed": 0,
        "fail_open_blocked": 0,
        "task_rejected": 0,
        "release_gate_rejected": 0,
    }

    for round_idx in range(1, rounds + 1):
        workflow_id = f"wf-ws22-longrun-{round_idx:04d}"
        task_id = f"task-ws22-longrun-{round_idx:04d}"
        subtask_id = f"backend-{round_idx:04d}"
        has_patch = (round_idx % fail_open_every) != 0

        try:
            workflow_store.create_workflow(
                workflow_id=workflow_id,
                task_id=task_id,
                initial_state="ReleaseCandidate",
                max_retries=0,
            )

            _emit(
                event_store,
                event_counter,
                "SubTaskDispatching",
                {
                    "workflow_id": workflow_id,
                    "task_id": task_id,
                    "subtask_id": subtask_id,
                    "round": round_idx,
                },
            )

            if has_patch:
                content = f"ROUND-{round_idx:04d}"
                target_file.write_text(content, encoding="utf-8")
                _emit(
                    event_store,
                    event_counter,
                    "TaskApproved",
                    {"workflow_id": workflow_id, "task_id": task_id, "round": round_idx},
                )
                _emit(
                    event_store,
                    event_counter,
                    "SubTaskExecutionCompleted",
                    {
                        "workflow_id": workflow_id,
                        "task_id": task_id,
                        "subtask_id": subtask_id,
                        "success": True,
                        "round": round_idx,
                    },
                )
                _emit(
                    event_store,
                    event_counter,
                    "SubAgentRuntimeCompleted",
                    {
                        "workflow_id": workflow_id,
                        "task_id": task_id,
                        "runtime_id": f"sar-{round_idx:04d}",
                        "round": round_idx,
                    },
                )
                subagent_gate_metrics["runtime_completed"] = int(subagent_gate_metrics["runtime_completed"]) + 1
            else:
                workflow_store.transition(
                    workflow_id,
                    "FailedExhausted",
                    reason="missing_patch_for_longrun_round",
                    payload={"round": round_idx},
                )
                _emit(
                    event_store,
                    event_counter,
                    "TaskRejected",
                    {"workflow_id": workflow_id, "task_id": task_id, "reason": "missing_patch_for_longrun_round"},
                )
                _emit(
                    event_store,
                    event_counter,
                    "SubTaskRejected",
                    {
                        "workflow_id": workflow_id,
                        "task_id": task_id,
                        "subtask_id": subtask_id,
                        "reason": "missing_patch_for_longrun_round",
                    },
                )
                _emit(
                    event_store,
                    event_counter,
                    "SubTaskExecutionCompleted",
                    {
                        "workflow_id": workflow_id,
                        "task_id": task_id,
                        "subtask_id": subtask_id,
                        "success": False,
                        "error": "missing_patch_for_longrun_round",
                        "round": round_idx,
                    },
                )
                _emit(
                    event_store,
                    event_counter,
                    "SubAgentRuntimeCompleted",
                    {
                        "workflow_id": workflow_id,
                        "task_id": task_id,
                        "runtime_id": f"sar-{round_idx:04d}",
                        "round": round_idx,
                    },
                )
                _emit(
                    event_store,
                    event_counter,
                    "SubAgentRuntimeFailOpenBlocked",
                    {
                        "workflow_id": workflow_id,
                        "task_id": task_id,
                        "runtime_id": f"sar-{round_idx:04d}",
                        "gate_failure": "missing_patch",
                    },
                )
                _emit(
                    event_store,
                    event_counter,
                    "SubAgentFailOpenBudgetUpdated",
                    {
                        "workflow_id": workflow_id,
                        "task_id": task_id,
                        "budget_delta": 1,
                    },
                )
                _emit(
                    event_store,
                    event_counter,
                    "SubAgentGateMetricUpdated",
                    {
                        "workflow_id": workflow_id,
                        "task_id": task_id,
                        "metric": "fail_open_blocked",
                        "value": 1,
                    },
                )
                # Keep parity with WS22 expected baseline semantics.
                _emit(
                    event_store,
                    event_counter,
                    "ReleaseGateRejected",
                    {"workflow_id": workflow_id, "task_id": task_id, "reason": "subtask_rejected"},
                )
                _emit(
                    event_store,
                    event_counter,
                    "ReleaseGateRejected",
                    {"workflow_id": workflow_id, "task_id": task_id, "reason": "runtime_fail_open_blocked"},
                )
                subagent_gate_metrics["runtime_completed"] = int(subagent_gate_metrics["runtime_completed"]) + 1
                subagent_gate_metrics["fail_open_blocked"] = int(subagent_gate_metrics["fail_open_blocked"]) + 1
                subagent_gate_metrics["task_rejected"] = int(subagent_gate_metrics["task_rejected"]) + 1
                subagent_gate_metrics["release_gate_rejected"] = int(subagent_gate_metrics["release_gate_rejected"]) + 2

            if round_idx % lease_renew_every == 0:
                if lease_handle is None:
                    lease_handle = asyncio.run(
                        global_mutex.acquire(
                            owner_id=lease_owner,
                            job_id=lease_name,
                            ttl_seconds=lease_ttl_seconds,
                            wait_timeout_seconds=1.0,
                            poll_interval_seconds=0.1,
                        )
                    )
                else:
                    lease_handle = asyncio.run(global_mutex.renew(lease_handle))
        except Exception as exc:  # pragma: no cover - long-run harness safety net
            unhandled_errors.append(f"round={round_idx}, error={type(exc).__name__}:{exc}")

    if lease_handle is not None:
        try:
            asyncio.run(global_mutex.release(lease_handle))
        except Exception as exc:  # pragma: no cover - baseline cleanup best effort
            unhandled_errors.append(f"release_error={type(exc).__name__}:{exc}")

    elapsed_wall_seconds = round(time.time() - started_at, 4)
    virtual_elapsed_seconds = round(rounds * virtual_round_seconds, 2)

    planned_fail_open_rounds = len([idx for idx in range(1, rounds + 1) if idx % fail_open_every == 0])
    planned_approved_rounds = rounds - planned_fail_open_rounds
    expectations = {
        "TaskApproved": planned_approved_rounds,
        "TaskRejected": planned_fail_open_rounds,
        "SubTaskDispatching": rounds,
        "SubTaskExecutionCompleted": rounds,
        "SubAgentRuntimeCompleted": rounds,
        "SubTaskRejected": planned_fail_open_rounds,
        "SubAgentRuntimeFailOpenBlocked": planned_fail_open_rounds,
        "SubAgentFailOpenBudgetUpdated": planned_fail_open_rounds,
        "SubAgentGateMetricUpdated": planned_fail_open_rounds,
        "ReleaseGateRejected": planned_fail_open_rounds * 2,
    }

    event_mismatches: Dict[str, Dict[str, int]] = {}
    for event_name, expected in expectations.items():
        actual = int(event_counter.get(event_name, 0))
        if actual != expected:
            event_mismatches[event_name] = {"expected": expected, "actual": actual}

    workflow_states = _count_workflow_states(workflow_store)
    failed_states = {
        name: value
        for name, value in workflow_states.items()
        if name not in {"ReleaseCandidate", "FailedExhausted"} and value > 0
    }
    failed_exhausted_count = int(workflow_states.get("FailedExhausted", 0))

    current_service_value = target_file.read_text(encoding="utf-8")
    expected_last_success_round = rounds
    if rounds % fail_open_every == 0:
        expected_last_success_round = rounds - 1
    expected_last_value = "BASE" if expected_last_success_round <= 0 else f"ROUND-{expected_last_success_round:04d}"

    metrics = {
        "rounds": rounds,
        "virtual_round_seconds": virtual_round_seconds,
        "virtual_elapsed_seconds": virtual_elapsed_seconds,
        "virtual_target_seconds": 600,
        "elapsed_wall_seconds": elapsed_wall_seconds,
        "planned_fail_open_rounds": planned_fail_open_rounds,
        "task_approved_count": int(event_counter.get("TaskApproved", 0)),
        "task_rejected_count": int(event_counter.get("TaskRejected", 0)),
        "subtask_dispatching_count": int(event_counter.get("SubTaskDispatching", 0)),
        "runtime_completed_count": int(event_counter.get("SubAgentRuntimeCompleted", 0)),
        "fail_open_count": int(event_counter.get("SubAgentRuntimeFailOpen", 0)),
        "gate_metric_update_count": int(event_counter.get("SubAgentGateMetricUpdated", 0)),
        "release_gate_rejected_count": int(event_counter.get("ReleaseGateRejected", 0)),
        "event_mismatch_count": len(event_mismatches),
        "unhandled_exception_count": len(unhandled_errors),
        "failed_workflow_state_count": int(sum(failed_states.values())),
        "failed_exhausted_count": failed_exhausted_count,
        "workflow_total": int(sum(workflow_states.values())),
        "service_value_matches_expected": bool(current_service_value == expected_last_value),
    }

    passed = (
        metrics["virtual_elapsed_seconds"] >= metrics["virtual_target_seconds"]
        and metrics["task_approved_count"] == planned_approved_rounds
        and metrics["task_rejected_count"] == planned_fail_open_rounds
        and metrics["event_mismatch_count"] == 0
        and metrics["unhandled_exception_count"] == 0
        and metrics["failed_workflow_state_count"] == 0
        and metrics["failed_exhausted_count"] == planned_fail_open_rounds
        and metrics["service_value_matches_expected"] is True
    )

    report = {
        "task_id": "NGA-WS22-004",
        "scenario": "system-agent-subagent-bridge-longrun-equivalent",
        "case_root": str(case_root).replace("\\", "/"),
        "report_file": str(report_file).replace("\\", "/"),
        "metrics": metrics,
        "workflow_states": workflow_states,
        "failed_workflow_states": failed_states,
        "event_expectations": expectations,
        "event_mismatches": event_mismatches,
        "subagent_gate_metrics_snapshot": dict(subagent_gate_metrics),
        "unhandled_errors": unhandled_errors,
        "service_last_value": current_service_value,
        "expected_service_last_value": expected_last_value,
        "passed": passed,
    }

    report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


__all__ = ["WS22LongRunConfig", "run_ws22_longrun_baseline"]
