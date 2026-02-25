#!/usr/bin/env python3
"""WS23-005 smoke runner for outbox -> brainstem bridge adapter."""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

from autonomous.system_agent import SystemAgent


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_release_policy(path: Path) -> None:
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


def run_outbox_bridge_smoke(*, output_file: Path) -> Dict[str, Any]:
    scratch_root = Path("scratch").resolve()
    scratch_root.mkdir(parents=True, exist_ok=True)
    temp_root = scratch_root / "runtime" / "ws23_005_smoke" / uuid.uuid4().hex[:12]
    repo = temp_root / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    _write_release_policy(repo / "policy" / "gate_policy.yaml")

    agent = SystemAgent(
        config={
            "enabled": False,
            "release": {
                "enabled": True,
                "gate_policy_path": "policy/gate_policy.yaml",
                "auto_rollback_enabled": False,
                "rollback_command": "",
            },
        },
        repo_dir=str(repo),
    )

    workflow_id = "wf-ws23-005-smoke"
    agent.workflow_store.create_workflow(workflow_id, task_id="task-ws23-005-smoke", initial_state="ReleaseCandidate")
    outbox_id = agent.workflow_store.enqueue_outbox(
        workflow_id,
        "ChangePromoted",
        {
            "workflow_id": workflow_id,
            "task_id": "task-ws23-005-smoke",
            "session_id": "session-ws23-005-smoke",
            "trace_id": "trace-ws23-005-smoke",
            "source": "ws23_005_smoke",
        },
        max_attempts=3,
    )
    event = agent.workflow_store.read_pending_outbox(limit=10)[0]

    captured: List[Tuple[str, Dict[str, Any], Dict[str, Any]]] = []

    def _capture(event_type: str, payload: Dict[str, Any], **kwargs: Any) -> None:
        captured.append((event_type, dict(payload), dict(kwargs)))

    agent._emit = _capture  # type: ignore[method-assign]
    asyncio.run(agent._dispatch_single_outbox_event(event, consumer="release-controller", fencing_epoch=1))

    bridged_payloads = [payload for event_type, payload, _ in captured if event_type == "BrainstemEventBridged"]
    bridge_payload = bridged_payloads[0] if bridged_payloads else {}
    event_types = [event_type for event_type, _, _ in captured]

    report: Dict[str, Any] = {
        "task_id": "NGA-WS23-005",
        "scenario": "outbox_brainstem_bridge_smoke",
        "generated_at": _utc_iso(),
        "passed": bool(bridged_payloads) and ("OutboxDispatched" in event_types),
        "checks": {
            "bridged_event_emitted": bool(bridged_payloads),
            "outbox_dispatched_emitted": "OutboxDispatched" in event_types,
            "outbox_id_matches": int(bridge_payload.get("outbox_id") or 0) == int(outbox_id),
            "workflow_id_matches": str(bridge_payload.get("workflow_id") or "") == workflow_id,
            "event_type_matches": str(bridge_payload.get("event_type") or "") == "ChangePromoted",
            "trace_id_matches": str(bridge_payload.get("trace_id") or "") == "trace-ws23-005-smoke",
            "session_id_matches": str(bridge_payload.get("session_id") or "") == "session-ws23-005-smoke",
        },
        "event_types": event_types,
        "bridge_payload": bridge_payload,
        "outbox_id": int(outbox_id),
        "workflow_id": workflow_id,
        "runtime_dir": str(temp_root).replace("\\", "/"),
    }

    target = output_file.resolve() if output_file.is_absolute() else (Path(".").resolve() / output_file)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["output_file"] = str(target).replace("\\", "/")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run WS23-005 outbox bridge smoke")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("scratch/reports/outbox_brainstem_bridge_ws23_005.json"),
        help="Output JSON report path",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_outbox_bridge_smoke(output_file=args.output)
    print(
        json.dumps(
            {
                "passed": report.get("passed"),
                "output": report.get("output_file"),
                "checks": report.get("checks"),
            },
            ensure_ascii=False,
        )
    )
    return 0 if bool(report.get("passed")) else 2


if __name__ == "__main__":
    raise SystemExit(main())
