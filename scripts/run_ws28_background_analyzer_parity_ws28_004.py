#!/usr/bin/env python3
"""Run WS28-004 background analyzer prompt parity checks."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from system.background_analyzer import (
    _PROMPT_ROUTE_ENGINE,
    _build_router_request_for_messages,
    _derive_prompt_route_metadata,
)


DEFAULT_OUTPUT = Path("scratch/reports/ws28_004_analyzer_parity.json")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_unix(path: Path) -> str:
    return str(path).replace("\\", "/")


def _resolve_path(repo_root: Path, candidate: Path) -> Path:
    return candidate if candidate.is_absolute() else repo_root / candidate


def run_ws28_background_analyzer_parity_ws28_004(
    *,
    repo_root: Path,
    output_file: Path = DEFAULT_OUTPUT,
) -> Dict[str, Any]:
    root = repo_root.resolve()

    coding_messages = [{"role": "user", "content": "请修复 API 错误并补回归测试"}]
    coding_request = _build_router_request_for_messages(coding_messages)
    coding_decision = _PROMPT_ROUTE_ENGINE.route(coding_request)
    coding_meta = _derive_prompt_route_metadata(coding_messages)

    readonly_messages = [{"role": "user", "content": "请分析这份文档并总结要点，不要执行修改"}]
    readonly_meta = _derive_prompt_route_metadata(readonly_messages)

    checks = {
        "router_metadata_parity": (
            coding_meta.get("prompt_profile") == coding_decision.prompt_profile
            and coding_meta.get("injection_mode") == coding_decision.injection_mode
            and coding_meta.get("delegation_intent") == coding_decision.delegation_intent
            and coding_meta.get("selected_role") == coding_decision.selected_role
        ),
        "readonly_path_uses_readonly_intent": readonly_meta.get("delegation_intent") == "read_only_exploration",
        "readonly_path_uses_minimal_mode": readonly_meta.get("injection_mode") == "minimal",
    }
    passed = all(checks.values())

    report: Dict[str, Any] = {
        "task_id": "NGA-WS28-004",
        "scenario": "background_analyzer_prompt_parity_ws28_004",
        "generated_at": _utc_now(),
        "repo_root": _to_unix(root),
        "passed": passed,
        "checks": checks,
        "samples": {
            "coding_route_metadata": coding_meta,
            "coding_router_decision": coding_decision.to_dict(),
            "readonly_route_metadata": readonly_meta,
        },
    }

    output = _resolve_path(root, output_file)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["output_file"] = _to_unix(output)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run WS28-004 background analyzer prompt parity checks")
    parser.add_argument("--repo-root", type=Path, default=Path("."), help="Repository root")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output JSON report path")
    parser.add_argument("--strict", action="store_true", help="Return non-zero when checks fail")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_ws28_background_analyzer_parity_ws28_004(
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
