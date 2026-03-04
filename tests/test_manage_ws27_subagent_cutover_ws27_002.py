from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

import yaml

from scripts.manage_ws27_subagent_cutover_ws27_002 import main, run_ws27_subagent_cutover_ws27_002


def _make_case_root(prefix: str) -> Path:
    root = Path("scratch") / prefix / uuid.uuid4().hex[:12]
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_case_root(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


def _write_config(path: Path, *, enabled: bool, rollout_percent: int, fail_open: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "autonomous": {
            "subagent_runtime": {
                "enabled": bool(enabled),
                "max_subtasks": 16,
                "rollout_percent": int(rollout_percent),
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
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _write_runtime_snapshot(path: Path, *, passed: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "task_id": "NGA-WS26-002",
                "scenario": "runtime_rollout_fail_open_lease_unified_snapshot",
                "passed": bool(passed),
                "summary": {
                    "fail_open_budget_exhausted": False,
                    "lease_status": "healthy",
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def test_cutover_plan_contains_rollout_phases_and_rollback_window() -> None:
    case_root = _make_case_root("test_manage_ws27_subagent_cutover_ws27_002")
    try:
        config_path = case_root / "repo" / "config" / "autonomous_runtime.yaml"
        runtime_snapshot = case_root / "repo" / "scratch" / "reports" / "ws26_snapshot.json"
        output = case_root / "repo" / "scratch" / "reports" / "ws27_cutover_plan.json"
        _write_config(config_path, enabled=True, rollout_percent=40)
        _write_runtime_snapshot(runtime_snapshot, passed=True)

        report = run_ws27_subagent_cutover_ws27_002(
            repo_root=case_root / "repo",
            action="plan",
            config_path=config_path.relative_to(case_root / "repo"),
            runtime_snapshot_report=runtime_snapshot.relative_to(case_root / "repo"),
            output_file=output.relative_to(case_root / "repo"),
            rollback_window_minutes=120,
        )
        assert report["passed"] is True
        assert report["cutover_ready"] is True
        assert report["rollback_window_minutes"] == 120
        phase_targets = [int(item["rollout_percent"]) for item in report["phase_plan"]]
        assert 50 in phase_targets
        assert 75 in phase_targets
        assert 100 in phase_targets
        assert "action rollback" in str(report["rollback_command"])
        assert output.exists() is True
    finally:
        _cleanup_case_root(case_root)


def test_cutover_apply_and_rollback_restore_previous_runtime_config() -> None:
    case_root = _make_case_root("test_manage_ws27_subagent_cutover_ws27_002")
    try:
        repo_root = case_root / "repo"
        config_path = repo_root / "config" / "autonomous_runtime.yaml"
        runtime_snapshot = repo_root / "scratch" / "reports" / "ws26_snapshot.json"
        snapshot = repo_root / "scratch" / "reports" / "ws27_cutover_snapshot.json"
        output_apply = repo_root / "scratch" / "reports" / "ws27_apply.json"
        output_rollback = repo_root / "scratch" / "reports" / "ws27_rollback.json"
        _write_config(config_path, enabled=False, rollout_percent=10, fail_open=True)
        _write_runtime_snapshot(runtime_snapshot, passed=True)

        apply_report = run_ws27_subagent_cutover_ws27_002(
            repo_root=repo_root,
            action="apply",
            config_path=config_path.relative_to(repo_root),
            runtime_snapshot_report=runtime_snapshot.relative_to(repo_root),
            rollback_snapshot=snapshot.relative_to(repo_root),
            output_file=output_apply.relative_to(repo_root),
            rollout_percent=100,
            disable_fail_open=True,
        )
        assert apply_report["passed"] is True
        updated_apply = apply_report["updated_runtime_config"]
        assert updated_apply["enabled"] is True
        assert updated_apply["rollout_percent"] == 100
        assert updated_apply["fail_open"] is False
        assert snapshot.exists() is True

        rollback_report = run_ws27_subagent_cutover_ws27_002(
            repo_root=repo_root,
            action="rollback",
            config_path=config_path.relative_to(repo_root),
            runtime_snapshot_report=runtime_snapshot.relative_to(repo_root),
            rollback_snapshot=snapshot.relative_to(repo_root),
            output_file=output_rollback.relative_to(repo_root),
        )
        assert rollback_report["passed"] is True
        assert rollback_report["rollback_mode"] == "restore_snapshot"
        updated_rollback = rollback_report["updated_runtime_config"]
        assert updated_rollback["enabled"] is False
        assert updated_rollback["rollout_percent"] == 10
        assert updated_rollback["fail_open"] is True
    finally:
        _cleanup_case_root(case_root)


def test_cutover_rollback_without_snapshot_uses_safe_baseline_mode() -> None:
    case_root = _make_case_root("test_manage_ws27_subagent_cutover_ws27_002")
    try:
        repo_root = case_root / "repo"
        config_path = repo_root / "config" / "autonomous_runtime.yaml"
        runtime_snapshot = repo_root / "scratch" / "reports" / "ws26_snapshot.json"
        output = repo_root / "scratch" / "reports" / "ws27_rollback_no_snapshot.json"
        _write_config(config_path, enabled=True, rollout_percent=100, fail_open=True)
        _write_runtime_snapshot(runtime_snapshot, passed=True)

        report = run_ws27_subagent_cutover_ws27_002(
            repo_root=repo_root,
            action="rollback",
            config_path=config_path.relative_to(repo_root),
            runtime_snapshot_report=runtime_snapshot.relative_to(repo_root),
            rollback_snapshot=Path("scratch/reports/missing_snapshot.json"),
            output_file=output.relative_to(repo_root),
        )
        assert report["passed"] is True
        assert report["rollback_mode"] == "safe_baseline_without_snapshot"
        updated = report["updated_runtime_config"]
        assert updated["enabled"] is False
        assert updated["rollout_percent"] == 0
    finally:
        _cleanup_case_root(case_root)


def test_cutover_cli_status_returns_nonzero_when_not_full_cutover(monkeypatch) -> None:
    case_root = _make_case_root("test_manage_ws27_subagent_cutover_ws27_002")
    try:
        repo_root = case_root / "repo"
        config_path = repo_root / "config" / "autonomous_runtime.yaml"
        runtime_snapshot = repo_root / "scratch" / "reports" / "ws26_snapshot.json"
        output = repo_root / "scratch" / "reports" / "ws27_status.json"
        _write_config(config_path, enabled=True, rollout_percent=75, fail_open=True)
        _write_runtime_snapshot(runtime_snapshot, passed=True)

        monkeypatch.setattr(
            "sys.argv",
            [
                "manage_ws27_subagent_cutover_ws27_002.py",
                "--action",
                "status",
                "--repo-root",
                str(repo_root),
                "--config",
                str(config_path.relative_to(repo_root)),
                "--runtime-snapshot-report",
                str(runtime_snapshot.relative_to(repo_root)),
                "--output",
                str(output.relative_to(repo_root)),
            ],
        )
        exit_code = main()
        assert exit_code == 2
        assert output.exists() is True
    finally:
        _cleanup_case_root(case_root)


def test_cutover_apply_preserves_non_runtime_yaml_layout() -> None:
    case_root = _make_case_root("test_manage_ws27_subagent_cutover_ws27_002")
    try:
        repo_root = case_root / "repo"
        config_path = repo_root / "config" / "autonomous_runtime.yaml"
        runtime_snapshot = repo_root / "scratch" / "reports" / "ws26_snapshot.json"
        output = repo_root / "scratch" / "reports" / "ws27_apply_preserve_layout.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            "\n".join(
                [
                    "autonomous:",
                    "  enabled: false",
                    "",
                    "  cli_tools:",
                    '    preferred: "claude"',
                    '    fallback_order: ["claude", "gemini"]',
                    "",
                    "  subagent_runtime:",
                    "    enabled: false",
                    "    max_subtasks: 16",
                    "    rollout_percent: 10",
                    "    fail_open: true",
                    "    fail_open_budget_ratio: 0.15",
                    "    enforce_scaffold_txn_for_write: true",
                    "    allow_legacy_fail_open_for_write: false",
                    "    require_contract_negotiation: true",
                    "    require_scaffold_patch: true",
                    "    fail_fast_on_subtask_error: true",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        _write_runtime_snapshot(runtime_snapshot, passed=True)

        report = run_ws27_subagent_cutover_ws27_002(
            repo_root=repo_root,
            action="apply",
            config_path=config_path.relative_to(repo_root),
            runtime_snapshot_report=runtime_snapshot.relative_to(repo_root),
            output_file=output.relative_to(repo_root),
            rollout_percent=100,
            disable_fail_open=True,
        )
        assert report["passed"] is True
        content = config_path.read_text(encoding="utf-8")
        assert 'preferred: "claude"' in content
        assert 'fallback_order: ["claude", "gemini"]' in content
        assert "    enabled: true" in content
        assert "    rollout_percent: 100" in content
        assert "    fail_open: false" in content
    finally:
        _cleanup_case_root(case_root)
