#!/usr/bin/env python3
"""Run WS28-008 core contract-only input checks for chat-stream ingress."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from apiserver.api_server import (
    _build_core_execution_contract_payload,
    _build_core_execution_messages,
)


DEFAULT_OUTPUT = Path("scratch/reports/ws28_008_core_contract_input.json")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_unix(path: Path) -> str:
    return str(path).replace("\\", "/")


def _resolve_path(repo_root: Path, candidate: Path) -> Path:
    return candidate if candidate.is_absolute() else repo_root / candidate


def run_ws28_core_contract_input_ws28_008(
    *,
    repo_root: Path,
    output_file: Path = DEFAULT_OUTPUT,
) -> Dict[str, Any]:
    root = repo_root.resolve()

    payload = _build_core_execution_contract_payload(
        session_id="ws28-008",
        current_message="请修复 API 错误并补齐回归",
        recent_messages=[
            {"role": "user", "content": "先定位线上失败请求"},
            {"role": "assistant", "content": "目前看到 500 来自 /v1/chat"},
            {"role": "user", "content": "继续修复"},
        ],
    )
    messages = _build_core_execution_messages(
        session_id="ws28-008",
        system_prompt="SYSTEM_PROMPT",
        current_message="请修复 API 错误并补齐回归",
    )

    checks = {
        "contract_stage_seed": payload.get("contract_stage") == "seed",
        "contract_has_evidence_hint": payload.get("evidence_path_hint") == "scratch/reports/",
        "contract_carries_recent_user_history": bool(payload.get("recent_user_history")),
        "core_messages_shape_contract_only": (
            len(messages) == 3
            and messages[0].get("role") == "system"
            and messages[1].get("role") == "system"
            and str(messages[1].get("content") or "").startswith("[ExecutionContractInput]")
            and messages[2].get("role") == "user"
        ),
    }
    passed = all(checks.values())

    report: Dict[str, Any] = {
        "task_id": "NGA-WS28-008",
        "scenario": "core_contract_input_ws28_008",
        "generated_at": _utc_now(),
        "repo_root": _to_unix(root),
        "passed": passed,
        "checks": checks,
        "samples": {
            "contract_payload": payload,
            "messages": messages,
        },
    }
    output = _resolve_path(root, output_file)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["output_file"] = _to_unix(output)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run WS28-008 core contract-only input checks")
    parser.add_argument("--repo-root", type=Path, default=Path("."), help="Repository root")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output JSON report path")
    parser.add_argument("--strict", action="store_true", help="Return non-zero when checks fail")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_ws28_core_contract_input_ws28_008(
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
