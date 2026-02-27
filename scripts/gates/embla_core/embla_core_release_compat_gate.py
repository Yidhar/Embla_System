#!/usr/bin/env python3
"""Embla_core (Next.js) minimal release compatibility gate."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class CompatCheck:
    check_id: str
    passed: bool
    severity: str
    detail: str


def _contains_all(text: str, patterns: Iterable[str]) -> bool:
    return all(pattern in text for pattern in patterns)


def build_release_compat_report(project_root: Path | None = None) -> dict:
    root = (project_root or Path(__file__).resolve().parent.parent.parent.parent).resolve()
    embla_core_dir = root / "Embla_core"
    package_json_path = embla_core_dir / "package.json"
    app_dir = embla_core_dir / "app" / "(dashboard)"
    ops_api_path = embla_core_dir / "lib" / "api" / "ops.ts"

    package_json = json.loads(package_json_path.read_text(encoding="utf-8"))
    package_scripts = package_json.get("scripts", {})
    dependencies = package_json.get("dependencies", {})

    required_scripts = ["dev", "build", "start"]
    missing_scripts = [name for name in required_scripts if name not in package_scripts]

    required_routes = [
        app_dir / "runtime-posture" / "page.tsx",
        app_dir / "mcp-fabric" / "page.tsx",
        app_dir / "memory-graph" / "page.tsx",
        app_dir / "workflow-events" / "page.tsx",
    ]
    missing_routes = [str(path.relative_to(root)).replace("\\", "/") for path in required_routes if not path.exists()]

    ops_api_source = ops_api_path.read_text(encoding="utf-8")

    checks = [
        CompatCheck(
            check_id="embla-core-root-present",
            passed=embla_core_dir.exists(),
            severity="critical",
            detail="Embla_core directory is present",
        ),
        CompatCheck(
            check_id="embla-core-next-scripts",
            passed=not missing_scripts,
            severity="critical",
            detail="missing npm scripts: " + ",".join(missing_scripts) if missing_scripts else "next dev/build/start scripts exist",
        ),
        CompatCheck(
            check_id="embla-core-runtime-routes",
            passed=not missing_routes,
            severity="critical",
            detail="missing route files: " + ",".join(missing_routes)
            if missing_routes
            else "runtime/mcp/memory/workflow route files exist",
        ),
        CompatCheck(
            check_id="embla-core-ops-api-wiring",
            passed=_contains_all(
                ops_api_source,
                [
                    '"/v1/ops/runtime/posture"',
                    '"/v1/ops/mcp/fabric"',
                    "fetchRuntimePosture",
                    "fetchMcpFabric",
                ],
            ),
            severity="critical",
            detail="ops API adapter wires runtime posture + mcp fabric endpoints",
        ),
        CompatCheck(
            check_id="embla-core-next-deps",
            passed="next" in dependencies and "react" in dependencies and "react-dom" in dependencies,
            severity="high",
            detail="next/react/react-dom dependencies declared",
        ),
    ]

    return {
        "task_id": "NGA-WS20-006-EMBLA-CORE",
        "gate_mode": "embla_core_web_frontend",
        "generated_at": datetime.now(UTC).isoformat(),
        "all_passed": all(item.passed for item in checks),
        "checks": [asdict(item) for item in checks],
        "route_base": "Embla_core/app/(dashboard)",
        "ops_api_file": str(ops_api_path.relative_to(root)).replace("\\", "/"),
    }


def write_report(report: dict, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Embla_core release compatibility gate")
    parser.add_argument(
        "--report-out",
        default="doc/task/reports/embla_core_release_compat_report.json",
        help="path to write JSON report",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="return non-zero when any check fails",
    )
    args = parser.parse_args()

    report = build_release_compat_report()
    output = write_report(report, Path(args.report_out))
    print(
        json.dumps(
            {
                "report_path": str(output),
                "all_passed": report["all_passed"],
                "gate_mode": report.get("gate_mode"),
            },
            ensure_ascii=False,
        )
    )
    if args.strict and not report["all_passed"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
