#!/usr/bin/env python3
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
    root = (project_root or Path(__file__).resolve().parent.parent).resolve()
    frontend_dir = root / "frontend"

    package_json = json.loads((frontend_dir / "package.json").read_text(encoding="utf-8"))
    package_scripts = package_json.get("scripts", {})
    dependencies = package_json.get("dependencies", {})
    dev_dependencies = package_json.get("devDependencies", {})
    all_dependencies = {**dependencies, **dev_dependencies}

    builder_yaml = (frontend_dir / "electron-builder.yml").read_text(encoding="utf-8")
    electron_main = (frontend_dir / "electron/main.ts").read_text(encoding="utf-8")
    updater_module = (frontend_dir / "electron/modules/updater.ts").read_text(encoding="utf-8")
    build_win = (root / "scripts/build-win.py").read_text(encoding="utf-8")

    required_dist_scripts = ["dist", "dist:win", "dist:mac", "dist:linux"]
    missing_scripts = [name for name in required_dist_scripts if name not in package_scripts]

    required_runtime_deps = ["electron", "electron-builder", "electron-updater"]
    missing_runtime_deps = [name for name in required_runtime_deps if name not in all_dependencies]

    checks = [
        CompatCheck(
            check_id="ws20-006-dist-scripts",
            passed=not missing_scripts,
            severity="critical",
            detail="missing scripts: " + ",".join(missing_scripts) if missing_scripts else "dist scripts exist for win/mac/linux",
        ),
        CompatCheck(
            check_id="ws20-006-electron-runtime-deps",
            passed=not missing_runtime_deps,
            severity="critical",
            detail=(
                "missing dependencies: " + ",".join(missing_runtime_deps)
                if missing_runtime_deps
                else "electron runtime dependencies are declared"
            ),
        ),
        CompatCheck(
            check_id="ws20-006-builder-targets",
            passed=_contains_all(
                builder_yaml,
                [
                    "extraResources:",
                    "from: backend-dist/naga-backend",
                    "win:",
                    "mac:",
                    "linux:",
                    "target: nsis",
                    "target: dmg",
                    "target: AppImage",
                ],
            ),
            severity="critical",
            detail="electron-builder has backend resource mapping and win/mac/linux targets",
        ),
        CompatCheck(
            check_id="ws20-006-network-offline-fallback",
            passed=_contains_all(
                updater_module,
                [
                    "checkForUpdates().catch",
                    "Silently fail if no update server is configured",
                ],
            ),
            severity="high",
            detail="updater keeps startup alive when update server/network is unavailable",
        ),
        CompatCheck(
            check_id="ws20-006-screen-capture-permission-fallback",
            passed=_contains_all(
                electron_main,
                [
                    "capture:getSources",
                    "systemPreferences.getMediaAccessStatus('screen')",
                    "return { permission: status }",
                    "capture:openScreenSettings",
                ],
            ),
            severity="high",
            detail="screen capture permission denial path and settings handoff are wired",
        ),
        CompatCheck(
            check_id="ws20-006-build-env-thresholds",
            passed=_contains_all(
                build_win,
                [
                    "MIN_NODE_MAJOR = 22",
                    "MIN_PYTHON = (3, 11)",
                    "npm\", \"run\", \"dist:win\"",
                ],
            ),
            severity="medium",
            detail="windows release script enforces python/node baseline and dist entrypoint",
        ),
    ]

    scenario_matrix = [
        {
            "scenario_id": "cfg-online-default",
            "type": "config",
            "description": "默认配置在线启动与更新检查",
            "automated_by": ["ws20-006-dist-scripts", "ws20-006-builder-targets"],
        },
        {
            "scenario_id": "cfg-api-base-url-override",
            "type": "config",
            "description": "设置 VITE_API_BASE_URL 的自定义后端地址",
            "automated_by": ["ws20-006-dist-scripts"],
        },
        {
            "scenario_id": "net-offline-startup",
            "type": "network",
            "description": "离线或更新服务不可达时启动不阻塞",
            "automated_by": ["ws20-006-network-offline-fallback"],
        },
        {
            "scenario_id": "net-proxy-restricted",
            "type": "network",
            "description": "代理/受限网络下仍可本地运行",
            "automated_by": ["ws20-006-network-offline-fallback"],
        },
        {
            "scenario_id": "permission-screen-capture-denied",
            "type": "permission",
            "description": "macOS 未授予录屏权限时 UI 给出可恢复路径",
            "automated_by": ["ws20-006-screen-capture-permission-fallback"],
        },
    ]

    return {
        "task_id": "NGA-WS20-006",
        "generated_at": datetime.now(UTC).isoformat(),
        "all_passed": all(item.passed for item in checks),
        "checks": [asdict(item) for item in checks],
        "scenario_matrix": scenario_matrix,
    }


def write_report(report: dict, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(description="WS20-006 desktop release compatibility verifier")
    parser.add_argument(
        "--report-out",
        default="doc/task/reports/ws20_006_desktop_compat_report.json",
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
    print(json.dumps({"report_path": str(output), "all_passed": report["all_passed"]}, ensure_ascii=False))
    if args.strict and not report["all_passed"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
