#!/usr/bin/env python3
"""Run WS28-006 prompt routing/injection release closure chain."""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from scripts.run_ws28_background_analyzer_parity_ws28_004 import (
    run_ws28_background_analyzer_parity_ws28_004,
)
from scripts.run_ws28_dna_spec_gate_ws28_005 import run_ws28_dna_spec_gate_ws28_005
from scripts.run_ws28_prompt_acl_guard_ws28_003 import run_ws28_prompt_acl_guard_ws28_003
from scripts.run_ws28_outer_core_path_gate_ws28_007 import run_ws28_outer_core_path_gate_ws28_007
from scripts.run_ws28_prompt_slice_compose_ws28_002 import run_ws28_prompt_slice_compose_ws28_002
from scripts.run_ws28_router_prompt_profile_ws28_001 import run_ws28_router_prompt_profile_ws28_001
from scripts.run_ws28_core_contract_input_ws28_008 import run_ws28_core_contract_input_ws28_008
from scripts.run_ws28_path_b_clarify_budget_ws28_009 import run_ws28_path_b_clarify_budget_ws28_009
from scripts.run_ws28_outer_core_session_bridge_ws28_010 import run_ws28_outer_core_session_bridge_ws28_010
from scripts.run_ws28_chat_route_bridge_observability_ws28_011 import (
    run_ws28_chat_route_bridge_observability_ws28_011,
)


DEFAULT_OUTPUT = Path("scratch/reports/release_closure_prompt_routing_ws28_006.json")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_unix(path: Path) -> str:
    return str(path).replace("\\", "/")


def _resolve_path(repo_root: Path, candidate: Path) -> Path:
    return candidate if candidate.is_absolute() else repo_root / candidate


def run_release_closure_prompt_routing_ws28_006(
    *,
    repo_root: Path,
    output_file: Path = DEFAULT_OUTPUT,
) -> Dict[str, Any]:
    root = repo_root.resolve()
    started = time.time()
    groups: List[Dict[str, Any]] = []

    group_specs = [
        ("ws28_001", run_ws28_router_prompt_profile_ws28_001),
        ("ws28_002", run_ws28_prompt_slice_compose_ws28_002),
        ("ws28_003", run_ws28_prompt_acl_guard_ws28_003),
        ("ws28_004", run_ws28_background_analyzer_parity_ws28_004),
        ("ws28_005", run_ws28_dna_spec_gate_ws28_005),
        ("ws28_007", run_ws28_outer_core_path_gate_ws28_007),
        ("ws28_008", run_ws28_core_contract_input_ws28_008),
        ("ws28_009", run_ws28_path_b_clarify_budget_ws28_009),
        ("ws28_010", run_ws28_outer_core_session_bridge_ws28_010),
        ("ws28_011", run_ws28_chat_route_bridge_observability_ws28_011),
    ]

    for group_id, fn in group_specs:
        group_report = fn(repo_root=root, output_file=Path(f"scratch/reports/{group_id}_result.json"))
        groups.append(
            {
                "group_id": group_id,
                "passed": bool(group_report.get("passed")),
                "checks": group_report.get("checks", {}),
                "output_file": group_report.get("output_file"),
            }
        )

    failed_groups = [item["group_id"] for item in groups if not bool(item.get("passed"))]
    passed = len(failed_groups) == 0
    report: Dict[str, Any] = {
        "task_id": "NGA-WS28-006",
        "scenario": "release_closure_prompt_routing_ws28_006",
        "generated_at": _utc_now(),
        "repo_root": _to_unix(root),
        "elapsed_seconds": round(time.time() - started, 4),
        "passed": passed,
        "failed_groups": failed_groups,
        "group_results": groups,
    }

    output = _resolve_path(root, output_file)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["output_file"] = _to_unix(output)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run WS28 prompt routing/injection closure chain")
    parser.add_argument("--repo-root", type=Path, default=Path("."), help="Repository root")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output JSON report path")
    parser.add_argument("--strict", action="store_true", help="Return non-zero when checks fail")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_release_closure_prompt_routing_ws28_006(
        repo_root=args.repo_root,
        output_file=args.output,
    )
    print(
        json.dumps(
            {
                "passed": bool(report.get("passed")),
                "failed_groups": report.get("failed_groups", []),
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
