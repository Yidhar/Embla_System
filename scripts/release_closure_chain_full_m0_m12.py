#!/usr/bin/env python3
"""Unified release closure chain runner for M0-M12 gates."""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from autonomous.ws27_longrun_endurance import WS27LongRunConfig, run_ws27_72h_endurance_baseline
from scripts.export_slo_snapshot import build_snapshot
from scripts.export_ws26_runtime_snapshot_ws26_002 import _build_ws26_report
from scripts.manage_ws27_subagent_cutover_ws27_002 import run_ws27_subagent_cutover_ws27_002
from scripts.release_closure_chain_full_m0_m7 import run_release_closure_chain_full_m0_m7
from scripts.run_ws27_oob_repair_drill_ws27_003 import run_ws27_oob_repair_drill_ws27_003


DEFAULT_FULL_OUTPUT = Path("scratch/reports/release_closure_chain_full_m0_m12_result.json")
DEFAULT_M0_M11_OUTPUT = Path("scratch/reports/release_closure_chain_full_m0_m7_result.json")
DEFAULT_M0_M5_OUTPUT = Path("scratch/reports/release_closure_chain_m0_m5_result.json")
DEFAULT_M6_M7_OUTPUT = Path("scratch/reports/ws22_phase3_release_chain_result.json")
DEFAULT_M8_OUTPUT = Path("scratch/reports/release_closure_chain_m8_ws23_006_result.json")
DEFAULT_M9_OUTPUT = Path("scratch/reports/release_closure_chain_m9_ws24_006_result.json")
DEFAULT_M10_OUTPUT = Path("scratch/reports/release_closure_chain_m10_ws25_006_result.json")
DEFAULT_M11_OUTPUT = Path("scratch/reports/release_closure_chain_m11_ws26_006_result.json")
DEFAULT_WS26_RUNTIME_SNAPSHOT = Path("scratch/reports/ws26_runtime_snapshot_ws26_002.json")
DEFAULT_WS27_ENDURANCE_OUTPUT = Path("scratch/reports/ws27_72h_endurance_ws27_001.json")
DEFAULT_WS27_ENDURANCE_SCRATCH = Path("scratch/ws27_72h_endurance")
DEFAULT_WS27_CUTOVER_PLAN_OUTPUT = Path("scratch/reports/ws27_subagent_cutover_plan_ws27_002.json")
DEFAULT_WS27_CUTOVER_APPLY_OUTPUT = Path("scratch/reports/ws27_subagent_cutover_apply_ws27_002.json")
DEFAULT_WS27_CUTOVER_STATUS_OUTPUT = Path("scratch/reports/ws27_subagent_cutover_status_ws27_002.json")
DEFAULT_WS27_CUTOVER_ROLLBACK_SNAPSHOT = Path("scratch/reports/ws27_subagent_cutover_rollback_snapshot_ws27_002.json")
DEFAULT_WS27_OOB_OUTPUT = Path("scratch/reports/ws27_oob_repair_drill_ws27_003.json")
DEFAULT_WS27_OOB_SCRATCH = Path("scratch/ws27_oob_repair_drill")
DEFAULT_AUTONOMOUS_CONFIG = Path("autonomous/config/autonomous_config.yaml")


def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_unix_path(path: Path) -> str:
    return str(path).replace("\\", "/")


def _resolve_path(repo_root: Path, candidate: Path) -> Path:
    return candidate if candidate.is_absolute() else repo_root / candidate


def _jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return _to_unix_path(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _build_endurance_config(*, quick_mode: bool) -> WS27LongRunConfig:
    if not quick_mode:
        return WS27LongRunConfig()
    return WS27LongRunConfig(
        target_hours=0.02,
        virtual_round_seconds=6.0,
        artifact_payload_kb=256,
        max_total_size_mb=1,
        max_single_artifact_mb=1,
        max_artifact_count=256,
        high_watermark_ratio=0.8,
        low_watermark_ratio=0.5,
        critical_reserve_ratio=0.1,
        normal_priority_every=3,
        high_priority_every=8,
    )


def _ensure_runtime_snapshot(*, repo_root: Path, runtime_snapshot_file: Path, events_limit: int = 20_000) -> Dict[str, Any]:
    snapshot = build_snapshot(repo_root=repo_root, events_limit=max(1, int(events_limit)))
    report = _build_ws26_report(snapshot=snapshot, output_file=runtime_snapshot_file)
    runtime_snapshot_file.parent.mkdir(parents=True, exist_ok=True)
    runtime_snapshot_file.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def _run_m12_endurance_step(
    *,
    repo_root: Path,
    output_file: Path,
    scratch_root: Path,
    quick_mode: bool,
) -> Dict[str, Any]:
    started = time.time()
    try:
        report = run_ws27_72h_endurance_baseline(
            scratch_root=scratch_root,
            report_file=output_file,
            config=_build_endurance_config(quick_mode=quick_mode),
        )
        checks = report.get("checks") if isinstance(report.get("checks"), dict) else {}
        return {
            "step_id": "M12-T1",
            "name": "ws27_001_endurance_baseline",
            "passed": bool(report.get("passed")),
            "checks": checks,
            "output_file": _to_unix_path(output_file),
            "duration_seconds": round(time.time() - started, 4),
        }
    except Exception as exc:  # pragma: no cover - defensive wrapper
        return {
            "step_id": "M12-T1",
            "name": "ws27_001_endurance_baseline",
            "passed": False,
            "checks": {"completed_without_exception": False},
            "output_file": _to_unix_path(output_file),
            "duration_seconds": round(time.time() - started, 4),
            "error": f"{type(exc).__name__}:{exc}",
        }


def _run_m12_cutover_step(
    *,
    repo_root: Path,
    config_path: Path,
    runtime_snapshot_report: Path,
    rollback_snapshot: Path,
    plan_output: Path,
    apply_output: Path,
    status_output: Path,
    rollback_window_minutes: int,
) -> Dict[str, Any]:
    started = time.time()
    runtime_snapshot_generated = False
    runtime_snapshot_status = {}
    try:
        if not runtime_snapshot_report.exists():
            runtime_snapshot_status = _ensure_runtime_snapshot(
                repo_root=repo_root,
                runtime_snapshot_file=runtime_snapshot_report,
            )
            runtime_snapshot_generated = True

        plan_report = run_ws27_subagent_cutover_ws27_002(
            repo_root=repo_root,
            action="plan",
            config_path=config_path,
            runtime_snapshot_report=runtime_snapshot_report,
            rollback_snapshot=rollback_snapshot,
            output_file=plan_output,
            rollback_window_minutes=max(15, int(rollback_window_minutes)),
        )
        apply_report = run_ws27_subagent_cutover_ws27_002(
            repo_root=repo_root,
            action="apply",
            config_path=config_path,
            runtime_snapshot_report=runtime_snapshot_report,
            rollback_snapshot=rollback_snapshot,
            output_file=apply_output,
            rollout_percent=100,
            disable_fail_open=True,
        )
        status_report = run_ws27_subagent_cutover_ws27_002(
            repo_root=repo_root,
            action="status",
            config_path=config_path,
            runtime_snapshot_report=runtime_snapshot_report,
            rollback_snapshot=rollback_snapshot,
            output_file=status_output,
        )
        status_checks = status_report.get("checks") if isinstance(status_report.get("checks"), dict) else {}
        checks = {
            "plan_passed": bool(plan_report.get("passed")),
            "apply_passed": bool(apply_report.get("passed")),
            "status_passed": bool(status_report.get("passed")),
            "subagent_runtime_enabled": bool(status_checks.get("subagent_runtime_enabled")),
            "rollout_percent_is_full": bool(status_checks.get("rollout_percent_is_full")),
            "runtime_snapshot_ready": bool(status_checks.get("runtime_snapshot_ready")),
            "rollback_snapshot_exists": bool(status_checks.get("rollback_snapshot_exists")),
        }
        return {
            "step_id": "M12-T2",
            "name": "ws27_002_cutover_and_status_gate",
            "passed": all(checks.values()),
            "checks": checks,
            "outputs": {
                "runtime_snapshot_report": _to_unix_path(runtime_snapshot_report),
                "plan_output": _to_unix_path(plan_output),
                "apply_output": _to_unix_path(apply_output),
                "status_output": _to_unix_path(status_output),
                "rollback_snapshot": _to_unix_path(rollback_snapshot),
            },
            "runtime_snapshot_generated": runtime_snapshot_generated,
            "runtime_snapshot_generation_passed": bool(runtime_snapshot_status.get("passed"))
            if runtime_snapshot_generated
            else None,
            "duration_seconds": round(time.time() - started, 4),
        }
    except Exception as exc:  # pragma: no cover - defensive wrapper
        return {
            "step_id": "M12-T2",
            "name": "ws27_002_cutover_and_status_gate",
            "passed": False,
            "checks": {"completed_without_exception": False},
            "outputs": {
                "runtime_snapshot_report": _to_unix_path(runtime_snapshot_report),
                "plan_output": _to_unix_path(plan_output),
                "apply_output": _to_unix_path(apply_output),
                "status_output": _to_unix_path(status_output),
                "rollback_snapshot": _to_unix_path(rollback_snapshot),
            },
            "duration_seconds": round(time.time() - started, 4),
            "error": f"{type(exc).__name__}:{exc}",
        }


def _run_m12_oob_step(
    *,
    repo_root: Path,
    output_file: Path,
    scratch_root: Path,
    rollback_window_minutes: int,
) -> Dict[str, Any]:
    started = time.time()
    try:
        report = run_ws27_oob_repair_drill_ws27_003(
            repo_root=repo_root,
            output_file=output_file,
            scratch_root=scratch_root,
            rollback_window_minutes=max(15, int(rollback_window_minutes)),
        )
        checks = report.get("checks") if isinstance(report.get("checks"), dict) else {}
        return {
            "step_id": "M12-T3",
            "name": "ws27_003_oob_repair_drill",
            "passed": bool(report.get("passed")),
            "checks": checks,
            "output_file": _to_unix_path(output_file),
            "duration_seconds": round(time.time() - started, 4),
        }
    except Exception as exc:  # pragma: no cover - defensive wrapper
        return {
            "step_id": "M12-T3",
            "name": "ws27_003_oob_repair_drill",
            "passed": False,
            "checks": {"completed_without_exception": False},
            "output_file": _to_unix_path(output_file),
            "duration_seconds": round(time.time() - started, 4),
            "error": f"{type(exc).__name__}:{exc}",
        }


def _write_report(*, repo_root: Path, output_file: Path, report: Dict[str, Any]) -> None:
    output = _resolve_path(repo_root, output_file)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(_jsonable(report), ensure_ascii=False, indent=2), encoding="utf-8")


def run_release_closure_chain_full_m0_m12(
    *,
    repo_root: Path,
    output_file: Path = DEFAULT_FULL_OUTPUT,
    m0_m11_output_file: Path = DEFAULT_M0_M11_OUTPUT,
    m0_m5_output_file: Path = DEFAULT_M0_M5_OUTPUT,
    m6_m7_output_file: Path = DEFAULT_M6_M7_OUTPUT,
    m8_output_file: Path = DEFAULT_M8_OUTPUT,
    m9_output_file: Path = DEFAULT_M9_OUTPUT,
    m10_output_file: Path = DEFAULT_M10_OUTPUT,
    m11_output_file: Path = DEFAULT_M11_OUTPUT,
    ws26_runtime_snapshot_report: Path = DEFAULT_WS26_RUNTIME_SNAPSHOT,
    ws27_endurance_output: Path = DEFAULT_WS27_ENDURANCE_OUTPUT,
    ws27_endurance_scratch_root: Path = DEFAULT_WS27_ENDURANCE_SCRATCH,
    ws27_cutover_plan_output: Path = DEFAULT_WS27_CUTOVER_PLAN_OUTPUT,
    ws27_cutover_apply_output: Path = DEFAULT_WS27_CUTOVER_APPLY_OUTPUT,
    ws27_cutover_status_output: Path = DEFAULT_WS27_CUTOVER_STATUS_OUTPUT,
    ws27_cutover_rollback_snapshot: Path = DEFAULT_WS27_CUTOVER_ROLLBACK_SNAPSHOT,
    ws27_oob_output: Path = DEFAULT_WS27_OOB_OUTPUT,
    ws27_oob_scratch_root: Path = DEFAULT_WS27_OOB_SCRATCH,
    config_path: Path = DEFAULT_AUTONOMOUS_CONFIG,
    rollback_window_minutes: int = 180,
    skip_m0_m11: bool = False,
    skip_m0_m5: bool = False,
    skip_m6_m7: bool = False,
    skip_m8: bool = False,
    skip_m9: bool = False,
    skip_m10: bool = False,
    skip_m11: bool = False,
    skip_m12: bool = False,
    skip_m12_endurance: bool = False,
    skip_m12_cutover: bool = False,
    skip_m12_oob: bool = False,
    quick_mode: bool = False,
    continue_on_failure: bool = False,
    timeout_seconds: int = 2400,
) -> Dict[str, Any]:
    root = repo_root.resolve()
    started_at = time.time()
    failed_groups = []
    group_results: Dict[str, Any] = {}

    if not skip_m0_m11:
        m0_m11_report = run_release_closure_chain_full_m0_m7(
            repo_root=root,
            output_file=m0_m11_output_file,
            m0_m5_output_file=m0_m5_output_file,
            m6_m7_output_file=m6_m7_output_file,
            m8_output_file=m8_output_file,
            m9_output_file=m9_output_file,
            m10_output_file=m10_output_file,
            m11_output_file=m11_output_file,
            skip_m0_m5=bool(skip_m0_m5),
            skip_m6_m7=bool(skip_m6_m7),
            skip_m8=bool(skip_m8),
            skip_m9=bool(skip_m9),
            skip_m10=bool(skip_m10),
            skip_m11=bool(skip_m11),
            quick_mode=bool(quick_mode),
            continue_on_failure=bool(continue_on_failure),
            timeout_seconds=max(30, int(timeout_seconds)),
        )
        group_results["m0_m11"] = m0_m11_report
        if not bool(m0_m11_report.get("passed")):
            failed_groups.append("m0_m11")
            if not continue_on_failure:
                report = {
                    "scenario": "release_closure_chain_full_m0_m12",
                    "generated_at": _utc_iso_now(),
                    "repo_root": _to_unix_path(root),
                    "elapsed_seconds": round(time.time() - started_at, 4),
                    "target_scope": "M0-M12",
                    "passed": False,
                    "failed_groups": failed_groups,
                    "group_results": group_results,
                }
                _write_report(repo_root=root, output_file=output_file, report=report)
                return report

    if not skip_m12:
        endurance_output = _resolve_path(root, ws27_endurance_output)
        endurance_scratch_root = _resolve_path(root, ws27_endurance_scratch_root)
        runtime_snapshot_report = _resolve_path(root, ws26_runtime_snapshot_report)
        cutover_plan_output = _resolve_path(root, ws27_cutover_plan_output)
        cutover_apply_output = _resolve_path(root, ws27_cutover_apply_output)
        cutover_status_output = _resolve_path(root, ws27_cutover_status_output)
        cutover_rollback_snapshot = _resolve_path(root, ws27_cutover_rollback_snapshot)
        resolved_config_path = _resolve_path(root, config_path)
        oob_output = _resolve_path(root, ws27_oob_output)
        oob_scratch_root = _resolve_path(root, ws27_oob_scratch_root)

        if not skip_m12_endurance:
            endurance_report = _run_m12_endurance_step(
                repo_root=root,
                output_file=endurance_output,
                scratch_root=endurance_scratch_root,
                quick_mode=bool(quick_mode),
            )
            group_results["m12_endurance"] = endurance_report
            if not bool(endurance_report.get("passed")):
                failed_groups.append("m12_endurance")
                if not continue_on_failure:
                    report = {
                        "scenario": "release_closure_chain_full_m0_m12",
                        "generated_at": _utc_iso_now(),
                        "repo_root": _to_unix_path(root),
                        "elapsed_seconds": round(time.time() - started_at, 4),
                        "target_scope": "M0-M12",
                        "passed": False,
                        "failed_groups": failed_groups,
                        "group_results": group_results,
                    }
                    _write_report(repo_root=root, output_file=output_file, report=report)
                    return report

        if not skip_m12_cutover:
            cutover_report = _run_m12_cutover_step(
                repo_root=root,
                config_path=resolved_config_path,
                runtime_snapshot_report=runtime_snapshot_report,
                rollback_snapshot=cutover_rollback_snapshot,
                plan_output=cutover_plan_output,
                apply_output=cutover_apply_output,
                status_output=cutover_status_output,
                rollback_window_minutes=max(15, int(rollback_window_minutes)),
            )
            group_results["m12_cutover"] = cutover_report
            if not bool(cutover_report.get("passed")):
                failed_groups.append("m12_cutover")
                if not continue_on_failure:
                    report = {
                        "scenario": "release_closure_chain_full_m0_m12",
                        "generated_at": _utc_iso_now(),
                        "repo_root": _to_unix_path(root),
                        "elapsed_seconds": round(time.time() - started_at, 4),
                        "target_scope": "M0-M12",
                        "passed": False,
                        "failed_groups": failed_groups,
                        "group_results": group_results,
                    }
                    _write_report(repo_root=root, output_file=output_file, report=report)
                    return report

        if not skip_m12_oob:
            oob_report = _run_m12_oob_step(
                repo_root=root,
                output_file=oob_output,
                scratch_root=oob_scratch_root,
                rollback_window_minutes=max(15, int(rollback_window_minutes)),
            )
            group_results["m12_oob_repair"] = oob_report
            if not bool(oob_report.get("passed")):
                failed_groups.append("m12_oob_repair")

    report = {
        "scenario": "release_closure_chain_full_m0_m12",
        "generated_at": _utc_iso_now(),
        "repo_root": _to_unix_path(root),
        "elapsed_seconds": round(time.time() - started_at, 4),
        "target_scope": "M0-M12",
        "passed": len(failed_groups) == 0,
        "failed_groups": failed_groups,
        "group_results": group_results,
    }
    _write_report(repo_root=root, output_file=output_file, report=report)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run unified release closure chain for M0-M12")
    parser.add_argument("--repo-root", type=Path, default=Path("."), help="Repository root")
    parser.add_argument("--output", type=Path, default=DEFAULT_FULL_OUTPUT, help="Unified output JSON report path")
    parser.add_argument(
        "--m0-m11-output",
        type=Path,
        default=DEFAULT_M0_M11_OUTPUT,
        help="M0-M11 chain output JSON report path",
    )
    parser.add_argument("--m0-m5-output", type=Path, default=DEFAULT_M0_M5_OUTPUT, help="M0-M5 output JSON report path")
    parser.add_argument("--m6-m7-output", type=Path, default=DEFAULT_M6_M7_OUTPUT, help="M6-M7 output JSON report path")
    parser.add_argument("--m8-output", type=Path, default=DEFAULT_M8_OUTPUT, help="M8 output JSON report path")
    parser.add_argument("--m9-output", type=Path, default=DEFAULT_M9_OUTPUT, help="M9 output JSON report path")
    parser.add_argument("--m10-output", type=Path, default=DEFAULT_M10_OUTPUT, help="M10 output JSON report path")
    parser.add_argument("--m11-output", type=Path, default=DEFAULT_M11_OUTPUT, help="M11 output JSON report path")
    parser.add_argument(
        "--ws26-runtime-snapshot-report",
        type=Path,
        default=DEFAULT_WS26_RUNTIME_SNAPSHOT,
        help="WS26 runtime snapshot report path used by WS27-002 cutover",
    )
    parser.add_argument(
        "--ws27-001-output",
        type=Path,
        default=DEFAULT_WS27_ENDURANCE_OUTPUT,
        help="WS27-001 output JSON report path",
    )
    parser.add_argument(
        "--ws27-001-scratch-root",
        type=Path,
        default=DEFAULT_WS27_ENDURANCE_SCRATCH,
        help="WS27-001 scratch root path",
    )
    parser.add_argument(
        "--ws27-002-plan-output",
        type=Path,
        default=DEFAULT_WS27_CUTOVER_PLAN_OUTPUT,
        help="WS27-002 plan output JSON report path",
    )
    parser.add_argument(
        "--ws27-002-apply-output",
        type=Path,
        default=DEFAULT_WS27_CUTOVER_APPLY_OUTPUT,
        help="WS27-002 apply output JSON report path",
    )
    parser.add_argument(
        "--ws27-002-status-output",
        type=Path,
        default=DEFAULT_WS27_CUTOVER_STATUS_OUTPUT,
        help="WS27-002 status output JSON report path",
    )
    parser.add_argument(
        "--ws27-002-rollback-snapshot",
        type=Path,
        default=DEFAULT_WS27_CUTOVER_ROLLBACK_SNAPSHOT,
        help="WS27-002 rollback snapshot path",
    )
    parser.add_argument(
        "--ws27-003-output",
        type=Path,
        default=DEFAULT_WS27_OOB_OUTPUT,
        help="WS27-003 output JSON report path",
    )
    parser.add_argument(
        "--ws27-003-scratch-root",
        type=Path,
        default=DEFAULT_WS27_OOB_SCRATCH,
        help="WS27-003 scratch root path",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_AUTONOMOUS_CONFIG,
        help="Autonomous config YAML path used by WS27-002 cutover",
    )
    parser.add_argument(
        "--rollback-window-minutes",
        type=int,
        default=180,
        help="Rollback window minutes used by WS27-002 plan and WS27-003 drill",
    )
    parser.add_argument("--skip-m0-m11", action="store_true", help="Skip M0-M11 base closure chain")
    parser.add_argument("--skip-m0-m5", action="store_true", help="Skip M0-M5 group inside M0-M11 base chain")
    parser.add_argument("--skip-m6-m7", action="store_true", help="Skip M6-M7 group inside M0-M11 base chain")
    parser.add_argument("--skip-m8", action="store_true", help="Skip M8 group inside M0-M11 base chain")
    parser.add_argument("--skip-m9", action="store_true", help="Skip M9 group inside M0-M11 base chain")
    parser.add_argument("--skip-m10", action="store_true", help="Skip M10 group inside M0-M11 base chain")
    parser.add_argument("--skip-m11", action="store_true", help="Skip M11 group inside M0-M11 base chain")
    parser.add_argument("--skip-m12", action="store_true", help="Skip all M12 groups")
    parser.add_argument("--skip-m12-endurance", action="store_true", help="Skip WS27-001 endurance step")
    parser.add_argument("--skip-m12-cutover", action="store_true", help="Skip WS27-002 cutover step")
    parser.add_argument("--skip-m12-oob", action="store_true", help="Skip WS27-003 OOB drill step")
    parser.add_argument("--quick-mode", action="store_true", help="Run lightweight mode for M0-M12 chain")
    parser.add_argument("--continue-on-failure", action="store_true", help="Continue after group failure")
    parser.add_argument("--timeout-seconds", type=int, default=2400, help="Per-group timeout passed to M0-M11 chain")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_release_closure_chain_full_m0_m12(
        repo_root=args.repo_root,
        output_file=args.output,
        m0_m11_output_file=args.m0_m11_output,
        m0_m5_output_file=args.m0_m5_output,
        m6_m7_output_file=args.m6_m7_output,
        m8_output_file=args.m8_output,
        m9_output_file=args.m9_output,
        m10_output_file=args.m10_output,
        m11_output_file=args.m11_output,
        ws26_runtime_snapshot_report=args.ws26_runtime_snapshot_report,
        ws27_endurance_output=args.ws27_001_output,
        ws27_endurance_scratch_root=args.ws27_001_scratch_root,
        ws27_cutover_plan_output=args.ws27_002_plan_output,
        ws27_cutover_apply_output=args.ws27_002_apply_output,
        ws27_cutover_status_output=args.ws27_002_status_output,
        ws27_cutover_rollback_snapshot=args.ws27_002_rollback_snapshot,
        ws27_oob_output=args.ws27_003_output,
        ws27_oob_scratch_root=args.ws27_003_scratch_root,
        config_path=args.config,
        rollback_window_minutes=max(15, int(args.rollback_window_minutes)),
        skip_m0_m11=bool(args.skip_m0_m11),
        skip_m0_m5=bool(args.skip_m0_m5),
        skip_m6_m7=bool(args.skip_m6_m7),
        skip_m8=bool(args.skip_m8),
        skip_m9=bool(args.skip_m9),
        skip_m10=bool(args.skip_m10),
        skip_m11=bool(args.skip_m11),
        skip_m12=bool(args.skip_m12),
        skip_m12_endurance=bool(args.skip_m12_endurance),
        skip_m12_cutover=bool(args.skip_m12_cutover),
        skip_m12_oob=bool(args.skip_m12_oob),
        quick_mode=bool(args.quick_mode),
        continue_on_failure=bool(args.continue_on_failure),
        timeout_seconds=max(30, int(args.timeout_seconds)),
    )
    print(
        json.dumps(
            {
                "passed": bool(report.get("passed")),
                "failed_groups": report.get("failed_groups", []),
                "output": _to_unix_path(_resolve_path(args.repo_root.resolve(), args.output)),
            },
            ensure_ascii=False,
        )
    )
    return 0 if bool(report.get("passed")) else 2


if __name__ == "__main__":
    raise SystemExit(main())
