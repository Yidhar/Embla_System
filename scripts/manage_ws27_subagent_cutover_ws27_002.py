#!/usr/bin/env python3
"""Manage WS27-002 Legacy -> SubAgent full cutover and rollback window."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

import yaml


DEFAULT_CONFIG_PATH = Path("autonomous/config/autonomous_config.yaml")
DEFAULT_RUNTIME_SNAPSHOT_REPORT = Path("scratch/reports/ws26_runtime_snapshot_ws26_002.json")
DEFAULT_ROLLBACK_SNAPSHOT = Path("scratch/reports/ws27_subagent_cutover_rollback_snapshot_ws27_002.json")
DEFAULT_OUTPUT_REPORT = Path("scratch/reports/ws27_subagent_cutover_ws27_002.json")


def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_unix_path(path: Path) -> str:
    return str(path).replace("\\", "/")


def _clamp_percent(value: Any, *, default: int) -> int:
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, min(100, numeric))


def _clamp_ratio(value: Any, *, default: float) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, numeric))


def _read_yaml_payload(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {}
    return dict(payload)


def _write_yaml_payload(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _ensure_subagent_runtime(payload: Dict[str, Any]) -> Dict[str, Any]:
    autonomous = payload.get("autonomous")
    if not isinstance(autonomous, dict):
        autonomous = {}
        payload["autonomous"] = autonomous

    subagent_runtime = autonomous.get("subagent_runtime")
    if not isinstance(subagent_runtime, dict):
        subagent_runtime = {}
        autonomous["subagent_runtime"] = subagent_runtime
    return subagent_runtime


def _normalized_runtime_config(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "enabled": bool(payload.get("enabled", False)),
        "max_subtasks": max(1, int(payload.get("max_subtasks", 16) or 16)),
        "rollout_percent": _clamp_percent(payload.get("rollout_percent", 100), default=100),
        "fail_open": bool(payload.get("fail_open", True)),
        "fail_open_budget_ratio": _clamp_ratio(payload.get("fail_open_budget_ratio", 0.15), default=0.15),
        "enforce_scaffold_txn_for_write": bool(payload.get("enforce_scaffold_txn_for_write", True)),
        "allow_legacy_fail_open_for_write": bool(payload.get("allow_legacy_fail_open_for_write", False)),
        "require_contract_negotiation": bool(payload.get("require_contract_negotiation", True)),
        "require_scaffold_patch": bool(payload.get("require_scaffold_patch", True)),
        "fail_fast_on_subtask_error": bool(payload.get("fail_fast_on_subtask_error", True)),
    }


def _runtime_mode_hint(*, enabled: bool, rollout_percent: int) -> str:
    if not enabled or rollout_percent <= 0:
        return "legacy"
    if rollout_percent >= 100:
        return "subagent_full"
    return "hybrid_rollout"


def _load_runtime_snapshot_readiness(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {
            "passed": False,
            "checks": {
                "runtime_snapshot_exists": False,
                "runtime_snapshot_passed": False,
                "fail_open_budget_available": False,
                "lease_not_critical": False,
            },
            "summary": {
                "fail_open_budget_exhausted": None,
                "lease_status": "unknown",
            },
            "path": _to_unix_path(path),
        }

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        payload = {}

    if not isinstance(payload, dict):
        payload = {}

    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    fail_open_budget_exhausted = bool(summary.get("fail_open_budget_exhausted"))
    lease_status = str(summary.get("lease_status") or "unknown")
    checks = {
        "runtime_snapshot_exists": True,
        "runtime_snapshot_passed": bool(payload.get("passed")),
        "fail_open_budget_available": not fail_open_budget_exhausted,
        "lease_not_critical": lease_status not in {"critical"},
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "summary": {
            "fail_open_budget_exhausted": fail_open_budget_exhausted,
            "lease_status": lease_status,
        },
        "path": _to_unix_path(path),
    }


def _build_cutover_phases(current_rollout_percent: int) -> List[Dict[str, Any]]:
    percent = _clamp_percent(current_rollout_percent, default=0)
    phase_targets = [25, 50, 75, 100]
    phases: List[Dict[str, Any]] = [
        {
            "phase_id": "P0",
            "rollout_percent": percent,
            "mode_hint": _runtime_mode_hint(enabled=True, rollout_percent=percent),
            "hold_minutes": 30,
            "objective": "baseline_observation",
        }
    ]

    next_index = 1
    for target in phase_targets:
        if target <= percent:
            continue
        phases.append(
            {
                "phase_id": f"P{next_index}",
                "rollout_percent": target,
                "mode_hint": _runtime_mode_hint(enabled=True, rollout_percent=target),
                "hold_minutes": 60 if target < 100 else 120,
                "objective": "promote_cutover_window" if target < 100 else "full_cutover_validation",
                "promotion_checks": [
                    "runtime_snapshot_passed",
                    "fail_open_budget_available",
                    "lease_not_critical",
                ],
            }
        )
        next_index += 1
    return phases


def _resolve_path(repo_root: Path, candidate: Path) -> Path:
    return candidate if candidate.is_absolute() else repo_root / candidate


def run_ws27_subagent_cutover_ws27_002(
    *,
    repo_root: Path,
    action: str,
    config_path: Path = DEFAULT_CONFIG_PATH,
    runtime_snapshot_report: Path = DEFAULT_RUNTIME_SNAPSHOT_REPORT,
    rollback_snapshot: Path = DEFAULT_ROLLBACK_SNAPSHOT,
    output_file: Path = DEFAULT_OUTPUT_REPORT,
    rollout_percent: int = 100,
    rollback_window_minutes: int = 180,
    disable_fail_open: bool = False,
) -> Dict[str, Any]:
    root = repo_root.resolve()
    config_file = _resolve_path(root, config_path)
    runtime_snapshot_file = _resolve_path(root, runtime_snapshot_report)
    rollback_snapshot_file = _resolve_path(root, rollback_snapshot)
    output = _resolve_path(root, output_file)

    payload = _read_yaml_payload(config_file)
    subagent_runtime = _ensure_subagent_runtime(payload)
    current = _normalized_runtime_config(subagent_runtime)
    readiness = _load_runtime_snapshot_readiness(runtime_snapshot_file)

    normalized_action = str(action or "").strip().lower()
    if normalized_action not in {"plan", "apply", "rollback", "status"}:
        raise ValueError(f"unsupported action: {action}")

    report: Dict[str, Any] = {
        "task_id": "NGA-WS27-002",
        "scenario": "legacy_to_subagent_full_cutover_and_rollback_window",
        "generated_at": _utc_iso_now(),
        "action": normalized_action,
        "repo_root": _to_unix_path(root),
        "config_path": _to_unix_path(config_file),
        "runtime_snapshot_report": _to_unix_path(runtime_snapshot_file),
        "rollback_snapshot_path": _to_unix_path(rollback_snapshot_file),
        "previous_runtime_config": current,
        "runtime_snapshot_readiness": readiness,
    }

    if normalized_action == "plan":
        rollback_window = max(15, int(rollback_window_minutes))
        rollback_deadline = datetime.now(timezone.utc) + timedelta(minutes=rollback_window)
        rollback_command = (
            "python -m scripts.manage_ws27_subagent_cutover_ws27_002 "
            f"--action rollback --repo-root {_to_unix_path(root)} "
            f"--config {_to_unix_path(config_path)} "
            f"--snapshot {_to_unix_path(rollback_snapshot)}"
        )
        report.update(
            {
                "passed": True,
                "cutover_ready": bool(readiness.get("passed")),
                "rollback_window_minutes": rollback_window,
                "rollback_deadline_utc": rollback_deadline.isoformat(),
                "rollback_command": rollback_command,
                "phase_plan": _build_cutover_phases(current_rollout_percent=current["rollout_percent"]),
            }
        )
    elif normalized_action == "apply":
        target_percent = _clamp_percent(rollout_percent, default=100)
        rollback_snapshot_file.parent.mkdir(parents=True, exist_ok=True)
        rollback_snapshot_file.write_text(
            json.dumps(
                {
                    "task_id": "NGA-WS27-002",
                    "scenario": "ws27_cutover_rollback_snapshot",
                    "generated_at": _utc_iso_now(),
                    "repo_root": _to_unix_path(root),
                    "config_path": _to_unix_path(config_file),
                    "previous_runtime_config": current,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        subagent_runtime["enabled"] = True
        subagent_runtime["rollout_percent"] = target_percent
        if disable_fail_open:
            subagent_runtime["fail_open"] = False
        _write_yaml_payload(config_file, payload)

        updated = _normalized_runtime_config(_ensure_subagent_runtime(_read_yaml_payload(config_file)))
        report.update(
            {
                "passed": True,
                "rollback_mode": "snapshot_saved",
                "updated_runtime_config": updated,
            }
        )
    elif normalized_action == "rollback":
        rollback_mode = "force_legacy_without_snapshot"
        if rollback_snapshot_file.exists():
            snapshot_payload = json.loads(rollback_snapshot_file.read_text(encoding="utf-8"))
            previous = (
                snapshot_payload.get("previous_runtime_config")
                if isinstance(snapshot_payload.get("previous_runtime_config"), dict)
                else {}
            )
            if previous:
                subagent_runtime.update(previous)
                rollback_mode = "restore_snapshot"
            else:
                subagent_runtime["enabled"] = False
                subagent_runtime["rollout_percent"] = 0
        else:
            subagent_runtime["enabled"] = False
            subagent_runtime["rollout_percent"] = 0

        _write_yaml_payload(config_file, payload)
        updated = _normalized_runtime_config(_ensure_subagent_runtime(_read_yaml_payload(config_file)))
        report.update(
            {
                "passed": True,
                "rollback_mode": rollback_mode,
                "updated_runtime_config": updated,
            }
        )
    else:
        checks = {
            "subagent_runtime_enabled": bool(current["enabled"]),
            "rollout_percent_is_full": int(current["rollout_percent"]) >= 100,
            "runtime_snapshot_ready": bool(readiness.get("passed")),
            "rollback_snapshot_exists": rollback_snapshot_file.exists(),
        }
        report.update(
            {
                "checks": checks,
                "passed": all(checks.values()),
                "current_runtime_mode_hint": _runtime_mode_hint(
                    enabled=bool(current["enabled"]),
                    rollout_percent=int(current["rollout_percent"]),
                ),
            }
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manage WS27-002 Legacy -> SubAgent full cutover")
    parser.add_argument(
        "--action",
        choices=("plan", "apply", "rollback", "status"),
        default="plan",
        help="Action: generate plan, apply rollout, rollback, or query status",
    )
    parser.add_argument("--repo-root", type=Path, default=Path("."), help="Repository root path")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help="Autonomous config YAML path")
    parser.add_argument(
        "--runtime-snapshot-report",
        type=Path,
        default=DEFAULT_RUNTIME_SNAPSHOT_REPORT,
        help="WS26 runtime snapshot report path",
    )
    parser.add_argument(
        "--snapshot",
        type=Path,
        default=DEFAULT_ROLLBACK_SNAPSHOT,
        help="Rollback snapshot path",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_REPORT,
        help="Output report JSON path",
    )
    parser.add_argument("--rollout-percent", type=int, default=100, help="Target rollout percent for apply action")
    parser.add_argument(
        "--rollback-window-minutes",
        type=int,
        default=180,
        help="Rollback window minutes for plan action",
    )
    parser.add_argument(
        "--disable-fail-open",
        action="store_true",
        help="Disable fail-open while applying cutover rollout",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_ws27_subagent_cutover_ws27_002(
        repo_root=args.repo_root,
        action=str(args.action),
        config_path=args.config,
        runtime_snapshot_report=args.runtime_snapshot_report,
        rollback_snapshot=args.snapshot,
        output_file=args.output,
        rollout_percent=int(args.rollout_percent),
        rollback_window_minutes=int(args.rollback_window_minutes),
        disable_fail_open=bool(args.disable_fail_open),
    )
    print(
        json.dumps(
            {
                "action": report.get("action"),
                "passed": bool(report.get("passed")),
                "output": _to_unix_path(args.output if args.output.is_absolute() else (args.repo_root / args.output)),
            },
            ensure_ascii=False,
        )
    )
    if str(args.action) == "status":
        return 0 if bool(report.get("passed")) else 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
