#!/usr/bin/env python3
"""Run WS27-003 OOB repair drill for remote host recovery."""

from __future__ import annotations

import argparse
import json
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Sequence

import yaml

from scripts.export_killswitch_oob_bundle_ws23_004 import export_killswitch_oob_bundle
from scripts.manage_ws27_subagent_cutover_ws27_002 import run_ws27_subagent_cutover_ws27_002


def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_unix_path(path: Path) -> str:
    return str(path).replace("\\", "/")


def _write_runtime_config(path: Path, *, enabled: bool, rollout_percent: int, fail_open: bool) -> None:
    payload = {
        "autonomous": {
            "subagent_runtime": {
                "enabled": bool(enabled),
                "max_subtasks": 16,
                "rollout_percent": max(0, min(100, int(rollout_percent))),
                "fail_open": bool(fail_open),
                "fail_open_budget_ratio": 0.15,
                "enforce_scaffold_txn_for_write": True,
                "allow_legacy_fail_open_for_write": False,
                "require_contract_negotiation": True,
                "require_scaffold_patch": True,
                "fail_fast_on_subtask_error": True,
            }
        }
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _write_runtime_snapshot(path: Path, *, passed: bool = True) -> None:
    payload = {
        "task_id": "NGA-WS26-002",
        "scenario": "runtime_rollout_fail_open_lease_unified_snapshot",
        "passed": bool(passed),
        "summary": {
            "fail_open_budget_exhausted": False,
            "lease_status": "healthy",
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_runtime_config(path: Path) -> Dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {}
    autonomous = payload.get("autonomous") if isinstance(payload.get("autonomous"), dict) else {}
    subagent_runtime = autonomous.get("subagent_runtime") if isinstance(autonomous.get("subagent_runtime"), dict) else {}
    return {
        "enabled": bool(subagent_runtime.get("enabled", False)),
        "rollout_percent": max(0, min(100, int(subagent_runtime.get("rollout_percent", 0) or 0))),
        "fail_open": bool(subagent_runtime.get("fail_open", True)),
    }


@dataclass
class DrillCaseResult:
    case_id: str
    name: str
    passed: bool
    checks: Dict[str, bool]
    details: Dict[str, Any]
    duration_seconds: float
    error: str = ""


def _run_case_snapshot_recovery(*, case_root: Path, rollback_window_minutes: int) -> DrillCaseResult:
    started = time.time()
    repo_root = case_root / "repo"
    config_rel = Path("config/autonomous_runtime.yaml")
    runtime_snapshot_rel = Path("scratch/reports/ws26_runtime_snapshot_ws26_002.json")
    rollback_snapshot_rel = Path("scratch/reports/ws27_drill_snapshot_recovery.json")

    _write_runtime_config(
        repo_root / config_rel,
        enabled=False,
        rollout_percent=20,
        fail_open=True,
    )
    _write_runtime_snapshot(repo_root / runtime_snapshot_rel, passed=True)

    try:
        plan = run_ws27_subagent_cutover_ws27_002(
            repo_root=repo_root,
            action="plan",
            config_path=config_rel,
            runtime_snapshot_report=runtime_snapshot_rel,
            rollback_snapshot=rollback_snapshot_rel,
            output_file=Path("scratch/reports/ws27_drill_case1_plan.json"),
            rollback_window_minutes=rollback_window_minutes,
        )
        apply_report = run_ws27_subagent_cutover_ws27_002(
            repo_root=repo_root,
            action="apply",
            config_path=config_rel,
            runtime_snapshot_report=runtime_snapshot_rel,
            rollback_snapshot=rollback_snapshot_rel,
            output_file=Path("scratch/reports/ws27_drill_case1_apply.json"),
            rollout_percent=100,
            disable_fail_open=True,
        )
        run_ws27_subagent_cutover_ws27_002(
            repo_root=repo_root,
            action="rollback",
            config_path=config_rel,
            runtime_snapshot_report=runtime_snapshot_rel,
            rollback_snapshot=rollback_snapshot_rel,
            output_file=Path("scratch/reports/ws27_drill_case1_rollback.json"),
        )
        restored = _read_runtime_config(repo_root / config_rel)
        checks = {
            "plan_generated": bool(plan.get("passed")),
            "apply_switched_full_cutover": bool(apply_report.get("updated_runtime_config", {}).get("enabled"))
            and int(apply_report.get("updated_runtime_config", {}).get("rollout_percent", 0)) == 100,
            "rollback_restored_previous_config": restored == {"enabled": False, "rollout_percent": 20, "fail_open": True},
        }
        passed = all(checks.values())
        details: Dict[str, Any] = {
            "repo_root": _to_unix_path(repo_root),
            "plan_output": _to_unix_path(repo_root / "scratch/reports/ws27_drill_case1_plan.json"),
            "apply_output": _to_unix_path(repo_root / "scratch/reports/ws27_drill_case1_apply.json"),
            "rollback_output": _to_unix_path(repo_root / "scratch/reports/ws27_drill_case1_rollback.json"),
            "restored_runtime_config": restored,
        }
        return DrillCaseResult(
            case_id="C1",
            name="snapshot_based_rollback_recovery",
            passed=passed,
            checks=checks,
            details=details,
            duration_seconds=round(time.time() - started, 4),
        )
    except Exception as exc:  # pragma: no cover - defensive wrapper
        return DrillCaseResult(
            case_id="C1",
            name="snapshot_based_rollback_recovery",
            passed=False,
            checks={"case_completed_without_exception": False},
            details={"repo_root": _to_unix_path(repo_root)},
            duration_seconds=round(time.time() - started, 4),
            error=f"{type(exc).__name__}:{exc}",
        )


def _run_case_safe_baseline_without_snapshot(*, case_root: Path) -> DrillCaseResult:
    started = time.time()
    repo_root = case_root / "repo"
    config_rel = Path("config/autonomous_runtime.yaml")
    runtime_snapshot_rel = Path("scratch/reports/ws26_runtime_snapshot_ws26_002.json")

    _write_runtime_config(
        repo_root / config_rel,
        enabled=True,
        rollout_percent=100,
        fail_open=False,
    )
    _write_runtime_snapshot(repo_root / runtime_snapshot_rel, passed=True)

    try:
        rollback_report = run_ws27_subagent_cutover_ws27_002(
            repo_root=repo_root,
            action="rollback",
            config_path=config_rel,
            runtime_snapshot_report=runtime_snapshot_rel,
            rollback_snapshot=Path("scratch/reports/non_existent_snapshot_case2.json"),
            output_file=Path("scratch/reports/ws27_drill_case2_rollback.json"),
        )
        current = _read_runtime_config(repo_root / config_rel)
        checks = {
            "rollback_completed": bool(rollback_report.get("passed")),
            "rollback_mode_safe_baseline": str(rollback_report.get("rollback_mode")) == "safe_baseline_without_snapshot",
            "runtime_config_reset_to_safe_baseline": current.get("enabled") is False
            and int(current.get("rollout_percent", 1)) == 0,
        }
        passed = all(checks.values())
        details: Dict[str, Any] = {
            "repo_root": _to_unix_path(repo_root),
            "rollback_output": _to_unix_path(repo_root / "scratch/reports/ws27_drill_case2_rollback.json"),
            "runtime_config_after_rollback": current,
        }
        return DrillCaseResult(
            case_id="C2",
            name="safe_baseline_without_snapshot",
            passed=passed,
            checks=checks,
            details=details,
            duration_seconds=round(time.time() - started, 4),
        )
    except Exception as exc:  # pragma: no cover - defensive wrapper
        return DrillCaseResult(
            case_id="C2",
            name="safe_baseline_without_snapshot",
            passed=False,
            checks={"case_completed_without_exception": False},
            details={"repo_root": _to_unix_path(repo_root)},
            duration_seconds=round(time.time() - started, 4),
            error=f"{type(exc).__name__}:{exc}",
        )


def _run_case_oob_bundle_export(
    *,
    case_root: Path,
    oob_allowlist: Sequence[str],
    probe_targets: Sequence[str],
) -> DrillCaseResult:
    started = time.time()
    output = case_root / "ws27_drill_oob_bundle.json"

    try:
        report = export_killswitch_oob_bundle(
            oob_allowlist=list(oob_allowlist),
            probe_targets=list(probe_targets),
            output_file=output,
            dns_allow=True,
            tcp_port=22,
            ping_timeout_seconds=2,
        )
        checks = {
            "bundle_passed": bool(report.get("passed")),
            "freeze_plan_valid": bool((report.get("freeze_plan") or {}).get("validation_ok")),
            "probe_plan_valid": bool((report.get("probe_plan") or {}).get("validation_ok")),
        }
        return DrillCaseResult(
            case_id="C3",
            name="oob_bundle_export_validation",
            passed=all(checks.values()),
            checks=checks,
            details={"output": _to_unix_path(output)},
            duration_seconds=round(time.time() - started, 4),
        )
    except Exception as exc:  # pragma: no cover - defensive wrapper
        return DrillCaseResult(
            case_id="C3",
            name="oob_bundle_export_validation",
            passed=False,
            checks={"case_completed_without_exception": False},
            details={"output": _to_unix_path(output)},
            duration_seconds=round(time.time() - started, 4),
            error=f"{type(exc).__name__}:{exc}",
        )


def run_ws27_oob_repair_drill_ws27_003(
    *,
    repo_root: Path,
    output_file: Path,
    scratch_root: Path = Path("scratch/ws27_oob_repair_drill"),
    rollback_window_minutes: int = 180,
    oob_allowlist: Sequence[str] = ("10.0.0.0/24", "bastion.example.com"),
    probe_targets: Sequence[str] = ("10.0.0.10", "bastion.example.com"),
) -> Dict[str, Any]:
    root = repo_root.resolve()
    target_output = output_file if output_file.is_absolute() else root / output_file
    drill_root = scratch_root if scratch_root.is_absolute() else root / scratch_root
    case_root = drill_root / uuid.uuid4().hex[:10]
    case_root.mkdir(parents=True, exist_ok=True)

    started_at = time.time()
    cases = [
        _run_case_snapshot_recovery(
            case_root=case_root / "case_snapshot_recovery",
            rollback_window_minutes=max(15, int(rollback_window_minutes)),
        ),
        _run_case_safe_baseline_without_snapshot(case_root=case_root / "case_safe_baseline_without_snapshot"),
        _run_case_oob_bundle_export(
            case_root=case_root / "case_oob_bundle_export",
            oob_allowlist=list(oob_allowlist),
            probe_targets=list(probe_targets),
        ),
    ]

    checks = {
        "snapshot_recovery_path": bool(cases[0].passed),
        "safe_baseline_without_snapshot_path": bool(cases[1].passed),
        "oob_bundle_validation_path": bool(cases[2].passed),
    }
    passed = all(checks.values())

    report: Dict[str, Any] = {
        "task_id": "NGA-WS27-003",
        "scenario": "oob_repair_runbook_drill_for_remote_hosts",
        "generated_at": _utc_iso_now(),
        "repo_root": _to_unix_path(root),
        "case_root": _to_unix_path(case_root),
        "elapsed_seconds": round(time.time() - started_at, 4),
        "passed": passed,
        "checks": checks,
        "case_count_planned": 3,
        "case_count_executed": len(cases),
        "case_results": [asdict(item) for item in cases],
    }
    target_output.parent.mkdir(parents=True, exist_ok=True)
    target_output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["output_file"] = _to_unix_path(target_output)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run WS27-003 OOB repair runbook drill")
    parser.add_argument("--repo-root", type=Path, default=Path("."), help="Repository root")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("scratch/reports/ws27_oob_repair_drill_ws27_003.json"),
        help="Output JSON report path",
    )
    parser.add_argument(
        "--scratch-root",
        type=Path,
        default=Path("scratch/ws27_oob_repair_drill"),
        help="Scratch workspace root",
    )
    parser.add_argument(
        "--rollback-window-minutes",
        type=int,
        default=180,
        help="Rollback window minutes used by snapshot recovery drill",
    )
    parser.add_argument(
        "--oob-allowlist",
        nargs="+",
        default=["10.0.0.0/24", "bastion.example.com"],
        help="OOB allowlist used by bundle export drill",
    )
    parser.add_argument(
        "--probe-targets",
        nargs="+",
        default=["10.0.0.10", "bastion.example.com"],
        help="Probe targets used by bundle export drill",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_ws27_oob_repair_drill_ws27_003(
        repo_root=args.repo_root,
        output_file=args.output,
        scratch_root=args.scratch_root,
        rollback_window_minutes=max(15, int(args.rollback_window_minutes)),
        oob_allowlist=list(args.oob_allowlist or []),
        probe_targets=list(args.probe_targets or []),
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
    return 0 if bool(report.get("passed")) else 2


if __name__ == "__main__":
    raise SystemExit(main())
