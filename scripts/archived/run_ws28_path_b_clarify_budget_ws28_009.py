#!/usr/bin/env python3
"""Archived legacy gate: WS28-009 path-b clarify budget."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


DEFAULT_OUTPUT = Path("scratch/reports/ws28_009_path_b_clarify_budget.json")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_unix(path: Path) -> str:
    return str(path).replace("\\", "/")


def _resolve_path(repo_root: Path, candidate: Path) -> Path:
    return candidate if candidate.is_absolute() else repo_root / candidate


def run_ws28_path_b_clarify_budget_ws28_009(
    *,
    repo_root: Path,
    output_file: Path = DEFAULT_OUTPUT,
) -> Dict[str, Any]:
    root = repo_root.resolve()
    checks = {
        "archived_legacy_gate": True,
        "pre_route_budget_guard_retired": True,
    }
    report: Dict[str, Any] = {
        "task_id": "NGA-WS28-009",
        "scenario": "path_b_clarify_budget_ws28_009",
        "generated_at": _utc_now(),
        "repo_root": _to_unix(root),
        "lifecycle": "archived_legacy",
        "passed": True,
        "checks": checks,
        "notes": [
            "Path-b clarify-budget pre-route guard retired from active runtime path.",
            "Legacy script preserved as archived artifact for audit traceability.",
        ],
    }
    output = _resolve_path(root, output_file)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["output_file"] = _to_unix(output)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run archived WS28-009 pre-route gate")
    parser.add_argument("--repo-root", type=Path, default=Path("."), help="Repository root")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output JSON report path")
    parser.add_argument("--strict", action="store_true", help="Return non-zero when checks fail")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_ws28_path_b_clarify_budget_ws28_009(
        repo_root=args.repo_root,
        output_file=args.output,
    )
    print(
        json.dumps(
            {
                "passed": bool(report.get("passed")),
                "checks": report.get("checks", {}),
                "output": report.get("output_file"),
                "lifecycle": report.get("lifecycle"),
            },
            ensure_ascii=False,
        )
    )
    if args.strict and not bool(report.get("passed")):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
