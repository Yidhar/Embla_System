#!/usr/bin/env python3
"""Run WS28-002 prompt-slice compose checks."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from agents.llm_gateway import (
    LLMGateway,
    GatewayRouteRequest,
    PromptEnvelopeInput,
    PromptSlice,
)


DEFAULT_OUTPUT = Path("scratch/reports/ws28_002_prompt_slice_compose.json")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_unix(path: Path) -> str:
    return str(path).replace("\\", "/")


def _resolve_path(repo_root: Path, candidate: Path) -> Path:
    return candidate if candidate.is_absolute() else repo_root / candidate


def run_ws28_prompt_slice_compose_ws28_002(
    *,
    repo_root: Path,
    output_file: Path = DEFAULT_OUTPUT,
) -> Dict[str, Any]:
    root = repo_root.resolve()
    gateway = LLMGateway()

    core_execution_plan = gateway.build_plan(
        request=GatewayRouteRequest(
            task_type="qa",
            severity="low",
            budget_remaining=5.0,
            route_semantic="core_execution",
        ),
        prompt_input=PromptEnvelopeInput(
            static_header="legacy-static",
            long_term_summary="legacy-summary",
            dynamic_messages=[{"role": "user", "content": "summarize current status"}],
            prompt_slices=[
                PromptSlice(
                    slice_uid="slice_l0",
                    layer="L0_DNA",
                    text="DNA CORE",
                    owner="system",
                    cache_segment="prefix_static",
                    priority=10,
                ),
                PromptSlice(
                    slice_uid="slice_l3",
                    layer="L3_TOOL_POLICY",
                    text="READ ONLY POLICY",
                    owner="tool_policy",
                    cache_segment="prefix_session",
                    priority=20,
                ),
                PromptSlice(
                    slice_uid="slice_l1_5",
                    layer="L1_5_EPISODIC_MEMORY",
                    text="memory tail payload",
                    owner="memory",
                    cache_segment="tail_dynamic",
                    priority=30,
                ),
            ],
        ),
    )
    shell_readonly_plan = gateway.build_plan(
        request=GatewayRouteRequest(
            task_type="qa",
            severity="low",
            budget_remaining=5.0,
            route_semantic="shell_readonly",
        ),
        prompt_input=PromptEnvelopeInput(
            static_header="legacy-static",
            long_term_summary="legacy-summary",
            dynamic_messages=[{"role": "user", "content": "please run patch"}],
            prompt_slices=[
                PromptSlice(
                    slice_uid="slice_task",
                    layer="L1_TASK_BASE",
                    text="task base",
                    owner="task",
                    cache_segment="prefix_static",
                    priority=10,
                ),
                PromptSlice(
                    slice_uid="slice_exec_policy",
                    layer="L3_TOOL_POLICY",
                    text="WRITE ENABLED",
                    owner="tool_policy",
                    cache_segment="tail_dynamic",
                    priority=20,
                ),
                PromptSlice(
                    slice_uid="legacy_dynamic_message_0",
                    layer="L4_RECOVERY",
                    text='{"role":"user","content":"please run patch"}',
                    owner="execution",
                    cache_segment="tail_dynamic",
                    priority=30,
                ),
            ],
        ),
    )

    compose_c = core_execution_plan.compose_decision
    compose_a = shell_readonly_plan.compose_decision
    checks = {
        "core_execution_compose_has_hashes": bool(compose_c and compose_c.prefix_hash and compose_c.tail_hash),
        "core_execution_compose_retains_execution_slices": bool(
            compose_c and "slice_l3" in compose_c.selected_slices and "slice_l3" not in compose_c.dropped_slices
        ),
        "shell_readonly_drops_execution_dynamic_slices": bool(
            compose_a
            and "slice_exec_policy" in compose_a.dropped_slices
            and "legacy_dynamic_message_0" in compose_a.dropped_slices
        ),
        "shell_readonly_envelope_excludes_write_policy_text": "WRITE ENABLED" not in (
            shell_readonly_plan.prompt_envelope.block1_text + shell_readonly_plan.prompt_envelope.block2_text
        ),
    }
    passed = all(checks.values())

    report: Dict[str, Any] = {
        "task_id": "NGA-WS28-002",
        "scenario": "prompt_slice_compose_ws28_002",
        "generated_at": _utc_now(),
        "repo_root": _to_unix(root),
        "passed": passed,
        "checks": checks,
        "samples": {
            "core_execution_compose_decision": (compose_c.to_dict() if compose_c else {}),
            "shell_readonly_compose_decision": (compose_a.to_dict() if compose_a else {}),
        },
    }

    output = _resolve_path(root, output_file)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["output_file"] = _to_unix(output)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run WS28-002 prompt-slice compose checks")
    parser.add_argument("--repo-root", type=Path, default=Path("."), help="Repository root")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output JSON report path")
    parser.add_argument("--strict", action="store_true", help="Return non-zero when checks fail")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_ws28_prompt_slice_compose_ws28_002(
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
