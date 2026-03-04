#!/usr/bin/env python3
"""WS23-005 smoke runner for outbox -> brainstem bridge adapter."""

from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from core.event_bus import EventStore
from system.brainstem_event_bridge import BRIDGED_EVENT_TYPE, build_brainstem_bridge_payload


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_unix(path: Path) -> str:
    return str(path).replace("\\", "/")


def run_outbox_bridge_smoke(*, output_file: Path) -> Dict[str, Any]:
    scratch_root = Path("scratch").resolve()
    scratch_root.mkdir(parents=True, exist_ok=True)
    temp_root = scratch_root / "runtime" / "ws23_005_smoke" / uuid.uuid4().hex[:12]
    temp_root.mkdir(parents=True, exist_ok=True)
    event_file = temp_root / "events.jsonl"
    event_store = EventStore(file_path=event_file)

    outbox_id = int(uuid.uuid4().int % 1_000_000) + 1
    workflow_id = "wf-ws23-005-smoke"
    task_id = "task-ws23-005-smoke"
    session_id = "session-ws23-005-smoke"
    trace_id = "trace-ws23-005-smoke"
    consumer = "release-controller"
    event_type = "ChangePromoted"

    outbox_row: Dict[str, Any] = {
        "outbox_id": outbox_id,
        "workflow_id": workflow_id,
        "event_type": event_type,
        "dispatch_attempts": 0,
        "max_attempts": 3,
        "schema_version": "ws23_005_smoke.v1",
        "source": "scripts.ws23_005.smoke",
        "severity": "info",
        "trace_id": trace_id,
        "payload": {
            "workflow_id": workflow_id,
            "task_id": task_id,
            "session_id": session_id,
            "trace_id": trace_id,
            "source": "ws23_005_smoke",
        },
        "event_envelope": {
            "event_id": f"evt-{uuid.uuid4().hex[:16]}",
            "schema_version": "ws23_005_smoke.v1",
            "timestamp": _utc_iso(),
            "event_type": event_type,
            "source": "scripts.ws23_005.smoke",
            "severity": "info",
            "idempotency_key": f"{workflow_id}:{event_type}:{outbox_id}",
            "trace_id": trace_id,
            "data": {
                "workflow_id": workflow_id,
                "task_id": task_id,
                "session_id": session_id,
                "trace_id": trace_id,
            },
        },
    }

    bridge_payload = build_brainstem_bridge_payload(outbox_row, consumer=consumer)
    event_store.emit(BRIDGED_EVENT_TYPE, bridge_payload, source="scripts.ws23_005.smoke")

    outbox_dispatched_payload = {
        "outbox_id": outbox_id,
        "workflow_id": workflow_id,
        "event_type": event_type,
        "task_id": task_id,
        "session_id": session_id,
        "trace_id": trace_id,
        "consumer": consumer,
        "fencing_epoch": 1,
    }
    event_store.emit("OutboxDispatched", outbox_dispatched_payload, source="scripts.ws23_005.smoke")

    rows: List[Dict[str, Any]] = event_store.read_recent(limit=100)
    event_types = [str(row.get("event_type") or "") for row in rows]
    bridged_payloads = [
        dict(row.get("payload") or {})
        for row in rows
        if str(row.get("event_type") or "") == BRIDGED_EVENT_TYPE
        and int((row.get("payload") or {}).get("outbox_id") or 0) == int(outbox_id)
    ]
    bridge_payload_from_store = bridged_payloads[-1] if bridged_payloads else {}

    report: Dict[str, Any] = {
        "task_id": "NGA-WS23-005",
        "scenario": "outbox_brainstem_bridge_smoke",
        "generated_at": _utc_iso(),
        "passed": bool(bridged_payloads) and ("OutboxDispatched" in event_types),
        "checks": {
            "bridged_event_emitted": bool(bridged_payloads),
            "outbox_dispatched_emitted": "OutboxDispatched" in event_types,
            "outbox_id_matches": int(bridge_payload_from_store.get("outbox_id") or 0) == int(outbox_id),
            "workflow_id_matches": str(bridge_payload_from_store.get("workflow_id") or "") == workflow_id,
            "event_type_matches": str(bridge_payload_from_store.get("event_type") or "") == event_type,
            "trace_id_matches": str(bridge_payload_from_store.get("trace_id") or "") == trace_id,
            "session_id_matches": str(bridge_payload_from_store.get("session_id") or "") == session_id,
        },
        "event_types": event_types,
        "bridge_payload": bridge_payload_from_store,
        "outbox_id": int(outbox_id),
        "workflow_id": workflow_id,
        "runtime_dir": _to_unix(temp_root),
        "event_file": _to_unix(event_file),
    }

    target = output_file.resolve() if output_file.is_absolute() else (Path(".").resolve() / output_file)
    report["output_file"] = _to_unix(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
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
