#!/usr/bin/env python3
"""Seed minimal WS28 runtime signals for governance/completion observability."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import apiserver.api_server as api_server
from autonomous.system_agent import SystemAgent
from autonomous.types import OptimizationTask
from core.event_bus import EventStore


DEFAULT_OUTPUT = Path("scratch/reports/ws28_runtime_signal_seed_ws28_031.json")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_unix(path: Path) -> str:
    return str(path).replace("\\", "/")


def _resolve_path(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_tail_events(event_file: Path, *, limit: int = 2000) -> List[Dict[str, Any]]:
    if not event_file.exists():
        return []
    try:
        lines = event_file.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return []
    rows: List[Dict[str, Any]] = []
    for raw in reversed(lines):
        if not raw.strip():
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        rows.append(payload)
        if len(rows) >= max(1, int(limit)):
            break
    rows.reverse()
    return rows


def run_ws28_runtime_signal_seed_ws28_031(
    *,
    repo_root: Path,
    output_file: Path = DEFAULT_OUTPUT,
    events_limit: int = 5000,
) -> Dict[str, Any]:
    started = time.time()
    root = repo_root.resolve()
    output_path = _resolve_path(root, output_file)
    event_file = root / "logs" / "autonomous" / "events.jsonl"
    event_store = EventStore(file_path=event_file)

    sample_id = uuid.uuid4().hex[:10]
    task_id = f"ws28-signal-seed-{sample_id}"
    workflow_id = f"wf-{task_id}"
    execution_session_id = f"ws28-seed-session-{sample_id}"
    trace_id = f"ws28-seed-trace-{sample_id}"
    sample_patch_path = f"scratch/reports/ws28_runtime_signal_seed_{sample_id}.md"
    sample_patch_content = (
        f"# WS28 Runtime Signal Seed\n\n"
        f"- sample_id: {sample_id}\n"
        f"- generated_at: {_utc_now()}\n"
    )

    task = OptimizationTask(
        task_id=task_id,
        instruction="seed minimal governance and completion signals",
        metadata={
            "write_intent": True,
            "subtasks": [
                {
                    "subtask_id": f"ops-{sample_id}",
                    "role": "ops",
                    "instruction": "create runtime signal seed artifact",
                    "contract_schema": {
                        "request": {
                            "artifact_path": "string",
                            "content": "string",
                        }
                    },
                    "role_executor_policy": {
                        "strict_role_paths": False,
                        "allowed_path_prefixes": ["scratch/reports/"],
                        "strict_semantic_guard": True,
                        "allowed_semantic_toolchains": ["ops", "docs", "config"],
                    },
                    "patches": [
                        {
                            "path": sample_patch_path,
                            "content": sample_patch_content,
                            "mode": "overwrite",
                            "encoding": "utf-8",
                        }
                    ],
                    "metadata": {
                        "ops_ticket": "WS28-SEED-AUTO",
                    },
                }
            ]
        },
    )

    agent = SystemAgent(
        config={
            "enabled": False,
            "lease": {"enabled": False},
            "release": {"enabled": False},
            "subagent_runtime": {
                "enabled": True,
                "rollout_percent": 100,
                "fail_open": False,
                "enforce_scaffold_txn_for_write": True,
                "require_contract_negotiation": True,
                "require_scaffold_patch": True,
                "fail_fast_on_subtask_error": True,
            },
        },
        repo_dir=str(root),
    )
    asyncio.run(agent._run_task(task, fencing_epoch=1))  # noqa: SLF001

    # Seed one completion-submitted signal through the same EventStore channel.
    completion_payload = {
        "session_id": execution_session_id,
        "execution_session_id": execution_session_id,
        "outer_session_id": execution_session_id,
        "core_session_id": f"{execution_session_id}__core",
        "trace_id": trace_id,
        "workflow_id": workflow_id,
        "path": "path-c",
        "status": "success",
        "reason": "submitted_completion",
        "decision": "stop",
        "round": 1,
        "task_completed": True,
        "submit_result_called": True,
        "submit_result_round": 1,
    }
    event_store.emit("AgenticLoopCompletionSubmitted", completion_payload, source="scripts.ws28_031.seed")

    rows = _read_tail_events(event_file, limit=max(200, int(events_limit)))
    completed_hits = [
        row
        for row in rows
        if str(row.get("event_type") or "") == "SubTaskExecutionCompleted"
        and isinstance(row.get("payload"), dict)
        and str(row["payload"].get("task_id") or "") == task_id
    ]
    completion_hits = [
        row
        for row in rows
        if str(row.get("event_type") or "") == "AgenticLoopCompletionSubmitted"
        and isinstance(row.get("payload"), dict)
        and str(row["payload"].get("execution_session_id") or "") == execution_session_id
    ]

    original_repo_root = api_server._ops_repo_root  # noqa: SLF001
    try:
        api_server._ops_repo_root = lambda: root  # type: ignore[assignment]  # noqa: SLF001
        posture_payload = api_server._ops_build_runtime_posture_payload(events_limit=max(200, int(events_limit)))  # noqa: SLF001
        incidents_payload = api_server._ops_build_incidents_latest_payload(limit=50)  # noqa: SLF001
    finally:
        api_server._ops_repo_root = original_repo_root  # type: ignore[assignment]  # noqa: SLF001

    posture_data = posture_payload.get("data") if isinstance(posture_payload.get("data"), dict) else {}
    posture_summary = posture_data.get("summary") if isinstance(posture_data.get("summary"), dict) else {}
    governance_status = str(posture_summary.get("execution_bridge_governance_status") or "unknown").strip().lower()
    completion_status = str(posture_summary.get("agentic_loop_completion_status") or "unknown").strip().lower()

    checks = {
        "subtask_execution_completed_emitted": len(completed_hits) >= 1,
        "agentic_loop_completion_submitted_emitted": len(completion_hits) >= 1,
        "runtime_governance_status_known": governance_status != "unknown",
        "agentic_loop_completion_status_known": completion_status != "unknown",
    }
    passed = all(checks.values())

    report = {
        "task_id": "NGA-WS28-031",
        "scenario": "ws28_runtime_signal_seed_minimal",
        "generated_at": _utc_now(),
        "repo_root": _to_unix(root),
        "passed": passed,
        "checks": checks,
        "seed": {
            "sample_id": sample_id,
            "task_id": task_id,
            "workflow_id": workflow_id,
            "execution_session_id": execution_session_id,
            "patch_path": sample_patch_path,
            "event_file": _to_unix(event_file),
        },
        "runtime_posture": {
            "status": str(posture_payload.get("status") or ""),
            "severity": str(posture_payload.get("severity") or ""),
            "reason_code": str(posture_payload.get("reason_code") or ""),
            "execution_bridge_governance_status": governance_status,
            "agentic_loop_completion_status": completion_status,
        },
        "incidents_latest": {
            "status": str(incidents_payload.get("status") or ""),
            "severity": str(incidents_payload.get("severity") or ""),
            "reason_code": str(incidents_payload.get("reason_code") or ""),
        },
        "events": {
            "subtask_execution_completed_hits": len(completed_hits),
            "agentic_loop_completion_submitted_hits": len(completion_hits),
        },
        "elapsed_seconds": round(max(0.0, time.time() - started), 4),
        "output_file": _to_unix(output_path),
    }
    _write_json(output_path, report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed minimal runtime signals for WS28 governance/completion observability.")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Repository root path.",
    )
    parser.add_argument(
        "--events-limit",
        type=int,
        default=5000,
        help="Tail events window for post-check summaries.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Output report JSON path.",
    )
    args = parser.parse_args()
    report = run_ws28_runtime_signal_seed_ws28_031(
        repo_root=args.repo_root,
        output_file=args.output,
        events_limit=max(200, int(args.events_limit)),
    )
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
