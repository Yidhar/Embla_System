#!/usr/bin/env python3
"""Run WS28-001 router prompt-profile compatibility checks."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from autonomous.router_engine import RouterRequest, TaskRouterEngine


DEFAULT_OUTPUT = Path("scratch/reports/ws28_001_router_prompt_profile.json")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_unix(path: Path) -> str:
    return str(path).replace("\\", "/")


def _resolve_path(repo_root: Path, candidate: Path) -> Path:
    return candidate if candidate.is_absolute() else repo_root / candidate


def run_ws28_router_prompt_profile_ws28_001(
    *,
    repo_root: Path,
    output_file: Path = DEFAULT_OUTPUT,
) -> Dict[str, Any]:
    root = repo_root.resolve()
    router = TaskRouterEngine()

    read_only = router.route(
        RouterRequest(
            task_id="ws28-001-readonly-research",
            description="分析文档并整理技术评估结论",
            estimated_complexity="medium",
            risk_level="read_only",
            budget_remaining=6000,
        )
    )
    high_risk = router.route(
        RouterRequest(
            task_id="ws28-001-high-risk",
            description="执行生产环境发布并校验配置",
            estimated_complexity="high",
            risk_level="deploy",
            budget_remaining=16000,
        )
    )
    explicit_recovery = router.route(
        RouterRequest(
            task_id="ws28-001-explicit-recovery",
            description="修复故障后执行回滚预案",
            estimated_complexity="medium",
            requested_role="developer",
            risk_level="read_only",
            budget_remaining=7000,
        )
    )

    checks = {
        "metadata_fields_present": all(
            bool(item.prompt_profile and item.injection_mode and item.delegation_intent)
            for item in (read_only, high_risk, explicit_recovery)
        ),
        "legacy_role_tier_preserved_for_high_risk": (
            high_risk.selected_role == "sys_admin" and high_risk.selected_model_tier == "primary"
        ),
        "readonly_profile_selected": (
            read_only.delegation_intent == "read_only_exploration"
            and read_only.prompt_profile == "outer_readonly_research"
            and read_only.injection_mode == "minimal"
        ),
        "explicit_delegate_recovery_selected": (
            explicit_recovery.delegation_intent == "explicit_role_delegate"
            and explicit_recovery.prompt_profile == "explicit_role_delegate"
            and explicit_recovery.injection_mode == "recovery"
        ),
    }
    passed = all(checks.values())

    report: Dict[str, Any] = {
        "task_id": "NGA-WS28-001",
        "scenario": "router_prompt_profile_compatibility_ws28_001",
        "generated_at": _utc_now(),
        "repo_root": _to_unix(root),
        "passed": passed,
        "checks": checks,
        "samples": {
            "read_only_research": read_only.to_dict(),
            "high_risk": high_risk.to_dict(),
            "explicit_recovery": explicit_recovery.to_dict(),
        },
    }
    output = _resolve_path(root, output_file)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["output_file"] = _to_unix(output)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run WS28-001 router prompt-profile compatibility checks")
    parser.add_argument("--repo-root", type=Path, default=Path("."), help="Repository root")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output JSON report path")
    parser.add_argument("--strict", action="store_true", help="Return non-zero when checks fail")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_ws28_router_prompt_profile_ws28_001(
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
