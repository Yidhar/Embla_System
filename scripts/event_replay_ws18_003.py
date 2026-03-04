"""WS18-003 CLI: replay Event Bus chains with audit logging."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

from core.event_bus import EventStore
from core.event_bus.replay_tool import EventReplayTool, ReplayRequest


def _default_event_log() -> Path:
    return Path("logs") / "autonomous" / "events.jsonl"


def _default_audit_log() -> Path:
    return Path("logs") / "autonomous" / "replay_audit.jsonl"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Replay Event Bus chain by trace/workflow/event filters.")
    parser.add_argument("--event-log", type=Path, default=_default_event_log(), help="Path to event jsonl log")
    parser.add_argument("--audit-log", type=Path, default=_default_audit_log(), help="Path to replay audit jsonl log")
    parser.add_argument("--trace-id", type=str, default=None, help="Trace id filter")
    parser.add_argument("--workflow-id", type=str, default=None, help="Workflow id filter")
    parser.add_argument("--event-type", type=str, default=None, help="Event type filter")
    parser.add_argument("--start-time", type=str, default=None, help="ISO start time (inclusive)")
    parser.add_argument("--end-time", type=str, default=None, help="ISO end time (inclusive)")
    parser.add_argument("--limit", type=int, default=2000, help="Max events to scan")
    parser.add_argument("--operator", type=str, default="manual", help="Operator name for audit")
    parser.add_argument("--reason", type=str, default="", help="Replay reason in audit")
    parser.add_argument("--output", type=Path, default=None, help="Optional json output path")
    parser.add_argument("--read-only", action="store_true", default=True, help="Keep replay as read-only drill")
    return parser


def _result_payload(result) -> Dict[str, Any]:
    return {
        "request": {
            "trace_id": result.request.trace_id,
            "workflow_id": result.request.workflow_id,
            "event_type": result.request.event_type,
            "start_time": result.request.start_time,
            "end_time": result.request.end_time,
            "limit": result.request.limit,
            "read_only": result.request.read_only,
            "operator": result.request.operator,
            "reason": result.request.reason,
        },
        "matched_count": len(result.matched_events),
        "matched_events": result.matched_events,
        "recovery_plan": result.recovery_plan,
        "audit_record": result.audit_record,
    }


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    store = EventStore(file_path=args.event_log)
    tool = EventReplayTool(event_store=store, audit_file=args.audit_log)
    request = ReplayRequest(
        trace_id=args.trace_id,
        workflow_id=args.workflow_id,
        event_type=args.event_type,
        start_time=args.start_time,
        end_time=args.end_time,
        limit=max(1, int(args.limit)),
        read_only=bool(args.read_only),
        operator=args.operator,
        reason=args.reason,
    )
    result = tool.replay(request)
    payload = _result_payload(result)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
