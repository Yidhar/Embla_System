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

from autonomous.system_agent import SystemAgent
from autonomous.tools.subagent_runtime import RuntimeSubTaskResult, RuntimeSubTaskSpec
from autonomous.types import OptimizationTask


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


def _count_workflow_states(agent: SystemAgent) -> Dict[str, int]:
    with agent.workflow_store._connect() as conn:  # noqa: SLF001
        rows = conn.execute(
            """
            SELECT current_state, COUNT(1) AS cnt
            FROM workflow_state
            GROUP BY current_state
            ORDER BY current_state ASC
            """
        ).fetchall()
    return {str(row["current_state"]): int(row["cnt"]) for row in rows}


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

    agent = SystemAgent(
        config={
            "enabled": False,
            "cli_tools": {"max_retries": 0},
            "lease": {
                "enabled": True,
                "ttl_seconds": 3600,
                "renew_interval_seconds": 30,
                "standby_poll_interval_seconds": 1,
            },
            "subagent_runtime": {
                "enabled": True,
                "fail_open": True,
                "allow_legacy_fail_open_for_write": True,
                "require_contract_negotiation": True,
                "require_scaffold_patch": True,
                "max_subtasks": 16,
            },
            "release": {
                "enabled": True,
                "gate_policy_path": "policy/gate_policy.yaml",
                "auto_rollback_enabled": False,
            },
        },
        repo_dir=str(repo),
    )

    async def _subagent_worker(_task: OptimizationTask, subtask: RuntimeSubTaskSpec) -> RuntimeSubTaskResult:
        # Simulate write-path fail-open rounds by returning a rejected subtask when no patch exists.
        if not list(subtask.patches):
            return RuntimeSubTaskResult(
                subtask_id=subtask.subtask_id,
                role=subtask.role,
                success=False,
                error="missing_patch_for_longrun_round",
                patches=[],
            )
        return RuntimeSubTaskResult(
            subtask_id=subtask.subtask_id,
            role=subtask.role,
            success=True,
            summary="simulated_subagent_worker_ok",
            patches=list(subtask.patches),
            metadata={"worker": "ws22_longrun_baseline_stub"},
        )

    agent._materialize_subtask_worker_result = _subagent_worker  # type: ignore[method-assign]

    captured_events: list[tuple[str, Dict[str, Any]]] = []
    original_emit = agent._emit

    def _capture_emit(event_type: str, payload: Dict[str, Any], **kwargs: Any) -> None:
        captured_events.append((event_type, dict(payload)))
        original_emit(event_type, payload, **kwargs)

    agent._emit = _capture_emit  # type: ignore[method-assign]

    rounds = max(1, int(config.rounds))
    virtual_round_seconds = max(0.1, float(config.virtual_round_seconds))
    fail_open_every = max(1, int(config.fail_open_every))
    lease_renew_every = max(1, int(config.lease_renew_every))

    unhandled_errors: list[str] = []
    started_at = time.time()

    async def _run() -> None:
        for round_idx in range(1, rounds + 1):
            patches = []
            if round_idx % fail_open_every != 0:
                patches = [{"path": "service.txt", "content": f"ROUND-{round_idx:04d}"}]

            task = OptimizationTask(
                task_id=f"task-ws22-longrun-{round_idx:04d}",
                instruction="longrun baseline round",
                metadata={
                    "subtasks": [
                        {
                            "subtask_id": f"backend-{round_idx:04d}",
                            "role": "backend",
                            "instruction": f"round-{round_idx}",
                            "contract_schema": {"request": {"id": "string"}},
                            "patches": patches,
                        }
                    ]
                },
            )
            try:
                await agent._run_task(task, fencing_epoch=1)
            except Exception as exc:  # pragma: no cover - long-run harness safety net
                unhandled_errors.append(f"round={round_idx}, error={type(exc).__name__}:{exc}")

            if round_idx % lease_renew_every == 0:
                lease_state = agent.workflow_store.try_acquire_or_renew_lease(
                    lease_name=agent.config.lease.lease_name,
                    owner_id=agent.instance_id,
                    ttl_seconds=agent.config.lease.ttl_seconds,
                )
                if not lease_state.is_owner:
                    unhandled_errors.append(f"round={round_idx}, error=lease_owner_lost")

    asyncio.run(_run())
    elapsed_wall_seconds = round(time.time() - started_at, 4)
    virtual_elapsed_seconds = round(rounds * virtual_round_seconds, 2)

    event_counter = Counter([event_type for event_type, _ in captured_events])
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

    workflow_states = _count_workflow_states(agent)
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
        "subagent_gate_metrics_snapshot": dict(agent._subagent_gate_metrics),  # noqa: SLF001
        "unhandled_errors": unhandled_errors,
        "service_last_value": current_service_value,
        "expected_service_last_value": expected_last_value,
        "passed": passed,
    }

    report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


__all__ = ["WS22LongRunConfig", "run_ws22_longrun_baseline"]
