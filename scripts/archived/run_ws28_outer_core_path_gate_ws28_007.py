#!/usr/bin/env python3
"""Run WS28-007 outer/core path gate checks for chat-stream ingress."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from apiserver.api_server import _build_chat_route_prompt_event_payload, _resolve_chat_stream_route


DEFAULT_OUTPUT = Path("scratch/reports/ws28_007_outer_core_path_gate.json")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_unix(path: Path) -> str:
    return str(path).replace("\\", "/")


def _resolve_path(repo_root: Path, candidate: Path) -> Path:
    return candidate if candidate.is_absolute() else repo_root / candidate


def run_ws28_outer_core_path_gate_ws28_007(
    *,
    repo_root: Path,
    output_file: Path = DEFAULT_OUTPUT,
) -> Dict[str, Any]:
    root = repo_root.resolve()

    outer_route = _resolve_chat_stream_route("你好，帮我总结最近运行态势", session_id="ws28-007-outer")
    clarify_route = _resolve_chat_stream_route("继续", session_id="ws28-007-clarify")
    core_route = _resolve_chat_stream_route("请修复 API bug 并补测试", session_id="ws28-007-core")

    outer_payload = _build_chat_route_prompt_event_payload(outer_route)
    core_payload = _build_chat_route_prompt_event_payload(core_route)

    checks = {
        "outer_readonly_routed_to_path_a": outer_route.get("path") == "path-a",
        "clarify_routed_to_path_b": clarify_route.get("path") == "path-b",
        "core_execution_routed_to_path_c": core_route.get("path") == "path-c",
        "prompt_event_payload_carries_outer_core_flags": (
            outer_payload.get("outer_readonly_hit") is True
            and outer_payload.get("core_escalation") is False
            and core_payload.get("outer_readonly_hit") is False
            and core_payload.get("core_escalation") is True
        ),
    }
    passed = all(checks.values())

    report: Dict[str, Any] = {
        "task_id": "NGA-WS28-007",
        "scenario": "outer_core_path_gate_ws28_007",
        "generated_at": _utc_now(),
        "repo_root": _to_unix(root),
        "passed": passed,
        "checks": checks,
        "samples": {
            "outer": outer_route,
            "clarify": clarify_route,
            "core": core_route,
            "outer_payload": outer_payload,
            "core_payload": core_payload,
        },
    }
    output = _resolve_path(root, output_file)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["output_file"] = _to_unix(output)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run WS28-007 outer/core path gate checks")
    parser.add_argument("--repo-root", type=Path, default=Path("."), help="Repository root")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output JSON report path")
    parser.add_argument("--strict", action="store_true", help="Return non-zero when checks fail")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_ws28_outer_core_path_gate_ws28_007(
        repo_root=args.repo_root,
        output_file=args.output,
    )
    print(
        json.dumps(
            {
                "passed": bool(report.get("passed")),
                "checks": report.get("checks", {}),
                "output": report.get("output_file"),
            },
            ensure_ascii=False,
        )
    )
    if args.strict and not bool(report.get("passed")):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
