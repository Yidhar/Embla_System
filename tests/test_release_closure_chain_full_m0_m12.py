from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

import scripts.release_closure_chain_full_m0_m12 as full_chain


def _make_case_root(prefix: str) -> Path:
    root = Path("scratch") / prefix / uuid.uuid4().hex[:12]
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_case_root(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


def _write_runtime_snapshot(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "task_id": "NGA-WS26-002",
                "scenario": "runtime_rollout_fail_open_lease_unified_snapshot",
                "passed": True,
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


def test_full_chain_m0_m12_runs_all_groups_when_green(monkeypatch) -> None:
    case_root = _make_case_root("test_release_closure_chain_full_m0_m12")
    try:
        repo_root = case_root / "repo"
        runtime_snapshot = repo_root / "scratch" / "reports" / "ws26_runtime_snapshot_ws26_002.json"
        _write_runtime_snapshot(runtime_snapshot)

        monkeypatch.setattr(
            full_chain,
            "run_release_closure_chain_full_m0_m7",
            lambda **kwargs: {"passed": True, "group": "m0_m11", "kwargs": kwargs},
        )
        monkeypatch.setattr(
            full_chain,
            "run_ws27_72h_endurance_baseline",
            lambda **kwargs: {"passed": True, "checks": {"virtual_72h_target_reached": True}},
        )
        monkeypatch.setattr(
            full_chain,
            "run_manage_brainstem_control_plane_ws28_017",
            lambda **kwargs: {
                "passed": True,
                "checks": {
                    "spawned": True,
                    "heartbeat_gate": True,
                    "launcher_pid_alive": True,
                    "manager_state_exists": True,
                },
                "heartbeat": {"checks": {"heartbeat_exists": True}},
                "state_file": "scratch/runtime/brainstem_control_plane_manager_ws28_017_state.json",
                "heartbeat_file": "scratch/runtime/brainstem_control_plane_heartbeat_ws23_001.json",
            },
        )

        def _cutover_stub(**kwargs):
            action = str(kwargs.get("action") or "")
            if action == "status":
                return {
                    "passed": True,
                    "checks": {
                        "subagent_runtime_enabled": True,
                        "rollout_percent_is_full": True,
                        "runtime_snapshot_ready": True,
                        "rollback_snapshot_exists": True,
                    },
                }
            return {"passed": True}

        monkeypatch.setattr(full_chain, "run_ws27_subagent_cutover_ws27_002", _cutover_stub)
        monkeypatch.setattr(
            full_chain,
            "run_ws27_oob_repair_drill_ws27_003",
            lambda **kwargs: {"passed": True, "checks": {"snapshot_recovery_path": True}},
        )
        monkeypatch.setattr(
            full_chain,
            "_run_m12_execution_governance_gate_step",
            lambda **kwargs: {
                "passed": True,
                "checks": {
                    "runtime_posture_payload_success": True,
                    "incidents_payload_success": True,
                    "runtime_governance_status_not_critical": True,
                    "incidents_governance_status_not_critical": True,
                    "critical_governance_issue_count_zero": True,
                    "governance_warning_ratio_within_budget": True,
                    "governance_rejection_ratio_within_budget": True,
                },
            },
        )

        output = repo_root / "scratch" / "reports" / "release_closure_chain_full_m0_m12_result.json"
        report = full_chain.run_release_closure_chain_full_m0_m12(
            repo_root=repo_root,
            output_file=Path("scratch/reports/release_closure_chain_full_m0_m12_result.json"),
            ws26_runtime_snapshot_report=runtime_snapshot,
        )
        assert report["passed"] is True
        assert report["failed_groups"] == []
        assert "m0_m11" in report["group_results"]
        assert "m12_brainstem_control_plane" in report["group_results"]
        assert "m12_endurance" in report["group_results"]
        assert "m12_cutover" in report["group_results"]
        assert "m12_oob_repair" in report["group_results"]
        assert "m12_execution_governance" in report["group_results"]
        brainstem = report["group_results"]["m12_brainstem_control_plane"]
        assert brainstem["action_sequence"] == ["start", "status"]
        assert brainstem["checks"]["state_file_consistent"] is True
        assert brainstem["checks"]["heartbeat_file_consistent"] is True
        assert brainstem["checks"]["start_spawn_or_already_running"] is True
        assert output.exists() is True
    finally:
        _cleanup_case_root(case_root)


def test_full_chain_m0_m12_stops_after_cutover_failure_by_default(monkeypatch) -> None:
    case_root = _make_case_root("test_release_closure_chain_full_m0_m12")
    try:
        repo_root = case_root / "repo"
        runtime_snapshot = repo_root / "scratch" / "reports" / "ws26_runtime_snapshot_ws26_002.json"
        _write_runtime_snapshot(runtime_snapshot)

        monkeypatch.setattr(full_chain, "run_release_closure_chain_full_m0_m7", lambda **kwargs: {"passed": True})
        monkeypatch.setattr(full_chain, "run_ws27_72h_endurance_baseline", lambda **kwargs: {"passed": True, "checks": {}})
        monkeypatch.setattr(
            full_chain,
            "run_manage_brainstem_control_plane_ws28_017",
            lambda **kwargs: {
                "passed": True,
                "checks": {
                    "spawned": True,
                    "heartbeat_gate": True,
                    "launcher_pid_alive": True,
                    "manager_state_exists": True,
                },
                "heartbeat": {"checks": {"heartbeat_exists": True}},
                "state_file": "scratch/runtime/brainstem_control_plane_manager_ws28_017_state.json",
                "heartbeat_file": "scratch/runtime/brainstem_control_plane_heartbeat_ws23_001.json",
            },
        )

        def _cutover_stub(**kwargs):
            action = str(kwargs.get("action") or "")
            if action == "status":
                return {
                    "passed": False,
                    "checks": {
                        "subagent_runtime_enabled": True,
                        "rollout_percent_is_full": True,
                        "runtime_snapshot_ready": False,
                        "rollback_snapshot_exists": True,
                    },
                }
            return {"passed": True}

        monkeypatch.setattr(full_chain, "run_ws27_subagent_cutover_ws27_002", _cutover_stub)
        oob_called = {"value": False}

        def _oob_stub(**kwargs):
            oob_called["value"] = True
            return {"passed": True}

        monkeypatch.setattr(full_chain, "run_ws27_oob_repair_drill_ws27_003", _oob_stub)
        monkeypatch.setattr(
            full_chain,
            "_run_m12_execution_governance_gate_step",
            lambda **kwargs: {
                "passed": True,
                "checks": {
                    "runtime_posture_payload_success": True,
                    "incidents_payload_success": True,
                    "runtime_governance_status_not_critical": True,
                    "incidents_governance_status_not_critical": True,
                    "critical_governance_issue_count_zero": True,
                    "governance_warning_ratio_within_budget": True,
                    "governance_rejection_ratio_within_budget": True,
                },
            },
        )

        report = full_chain.run_release_closure_chain_full_m0_m12(
            repo_root=repo_root,
            output_file=Path("scratch/reports/full_m0_m12_stop_on_failure.json"),
            ws26_runtime_snapshot_report=runtime_snapshot,
            continue_on_failure=False,
        )
        assert report["passed"] is False
        assert report["failed_groups"] == ["m12_cutover"]
        assert "m12_brainstem_control_plane" in report["group_results"]
        assert "m12_oob_repair" not in report["group_results"]
        assert oob_called["value"] is False
    finally:
        _cleanup_case_root(case_root)


def test_full_chain_m0_m12_quick_mode_forwards_flags(monkeypatch) -> None:
    case_root = _make_case_root("test_release_closure_chain_full_m0_m12")
    try:
        repo_root = case_root / "repo"
        runtime_snapshot = repo_root / "scratch" / "reports" / "ws26_runtime_snapshot_ws26_002.json"
        _write_runtime_snapshot(runtime_snapshot)

        captured = {"m0_m11_kwargs": None, "endurance_config": None}

        def _m0_m11_stub(**kwargs):
            captured["m0_m11_kwargs"] = kwargs
            return {"passed": True}

        def _endurance_stub(**kwargs):
            captured["endurance_config"] = kwargs.get("config")
            return {"passed": True, "checks": {}}

        monkeypatch.setattr(full_chain, "run_release_closure_chain_full_m0_m7", _m0_m11_stub)
        monkeypatch.setattr(full_chain, "run_ws27_72h_endurance_baseline", _endurance_stub)
        monkeypatch.setattr(
            full_chain,
            "run_manage_brainstem_control_plane_ws28_017",
            lambda **kwargs: {
                "passed": True,
                "checks": {
                    "spawned": True,
                    "heartbeat_gate": True,
                    "launcher_pid_alive": True,
                    "manager_state_exists": True,
                },
                "heartbeat": {"checks": {"heartbeat_exists": True}},
                "state_file": "scratch/runtime/brainstem_control_plane_manager_ws28_017_state.json",
                "heartbeat_file": "scratch/runtime/brainstem_control_plane_heartbeat_ws23_001.json",
            },
        )
        monkeypatch.setattr(
            full_chain,
            "run_ws27_subagent_cutover_ws27_002",
            lambda **kwargs: {
                "passed": True,
                "checks": {
                    "subagent_runtime_enabled": True,
                    "rollout_percent_is_full": True,
                    "runtime_snapshot_ready": True,
                    "rollback_snapshot_exists": True,
                },
            }
            if str(kwargs.get("action") or "") == "status"
            else {"passed": True},
        )
        monkeypatch.setattr(full_chain, "run_ws27_oob_repair_drill_ws27_003", lambda **kwargs: {"passed": True})
        monkeypatch.setattr(
            full_chain,
            "_run_m12_execution_governance_gate_step",
            lambda **kwargs: {
                "passed": True,
                "checks": {
                    "runtime_posture_payload_success": True,
                    "incidents_payload_success": True,
                    "runtime_governance_status_not_critical": True,
                    "incidents_governance_status_not_critical": True,
                    "critical_governance_issue_count_zero": True,
                    "governance_warning_ratio_within_budget": True,
                    "governance_rejection_ratio_within_budget": True,
                },
            },
        )

        report = full_chain.run_release_closure_chain_full_m0_m12(
            repo_root=repo_root,
            output_file=Path("scratch/reports/full_m0_m12_quick_mode.json"),
            ws26_runtime_snapshot_report=runtime_snapshot,
            quick_mode=True,
        )
        assert report["passed"] is True
        assert captured["m0_m11_kwargs"]["quick_mode"] is True

        endurance_config = captured["endurance_config"]
        assert endurance_config is not None
        assert round(float(endurance_config.target_hours), 4) == 0.02
        assert round(float(endurance_config.virtual_round_seconds), 4) == 6.0
        assert int(endurance_config.max_total_size_mb) == 1
    finally:
        _cleanup_case_root(case_root)


def test_full_chain_m0_m12_stops_when_brainstem_control_plane_step_fails(monkeypatch) -> None:
    case_root = _make_case_root("test_release_closure_chain_full_m0_m12")
    try:
        repo_root = case_root / "repo"
        runtime_snapshot = repo_root / "scratch" / "reports" / "ws26_runtime_snapshot_ws26_002.json"
        _write_runtime_snapshot(runtime_snapshot)

        monkeypatch.setattr(full_chain, "run_release_closure_chain_full_m0_m7", lambda **kwargs: {"passed": True})
        monkeypatch.setattr(
            full_chain,
            "run_manage_brainstem_control_plane_ws28_017",
            lambda **kwargs: {
                "passed": False,
                "checks": {
                    "spawned": True,
                    "heartbeat_gate": False,
                    "launcher_pid_alive": False,
                    "manager_state_exists": True,
                },
                "heartbeat": {"checks": {"heartbeat_exists": True}},
                "state_file": "scratch/runtime/brainstem_control_plane_manager_ws28_017_state.json",
                "heartbeat_file": "scratch/runtime/brainstem_control_plane_heartbeat_ws23_001.json",
            },
        )
        endurance_called = {"value": False}

        def _endurance_stub(**kwargs):
            endurance_called["value"] = True
            return {"passed": True, "checks": {}}

        monkeypatch.setattr(full_chain, "run_ws27_72h_endurance_baseline", _endurance_stub)
        monkeypatch.setattr(full_chain, "run_ws27_subagent_cutover_ws27_002", lambda **kwargs: {"passed": True})
        monkeypatch.setattr(full_chain, "run_ws27_oob_repair_drill_ws27_003", lambda **kwargs: {"passed": True})
        monkeypatch.setattr(
            full_chain,
            "_run_m12_execution_governance_gate_step",
            lambda **kwargs: {
                "passed": True,
                "checks": {
                    "runtime_posture_payload_success": True,
                    "incidents_payload_success": True,
                    "runtime_governance_status_not_critical": True,
                    "incidents_governance_status_not_critical": True,
                    "critical_governance_issue_count_zero": True,
                    "governance_warning_ratio_within_budget": True,
                    "governance_rejection_ratio_within_budget": True,
                },
            },
        )

        report = full_chain.run_release_closure_chain_full_m0_m12(
            repo_root=repo_root,
            output_file=Path("scratch/reports/full_m0_m12_brainstem_fail.json"),
            ws26_runtime_snapshot_report=runtime_snapshot,
            continue_on_failure=False,
        )
        assert report["passed"] is False
        assert report["failed_groups"] == ["m12_brainstem_control_plane"]
        assert "m12_brainstem_control_plane" in report["group_results"]
        assert "m12_endurance" not in report["group_results"]
        assert endurance_called["value"] is False
    finally:
        _cleanup_case_root(case_root)


def test_full_chain_m0_m12_stops_when_execution_governance_gate_fails(monkeypatch) -> None:
    case_root = _make_case_root("test_release_closure_chain_full_m0_m12")
    try:
        repo_root = case_root / "repo"
        runtime_snapshot = repo_root / "scratch" / "reports" / "ws26_runtime_snapshot_ws26_002.json"
        _write_runtime_snapshot(runtime_snapshot)

        monkeypatch.setattr(full_chain, "run_release_closure_chain_full_m0_m7", lambda **kwargs: {"passed": True})
        monkeypatch.setattr(full_chain, "run_ws27_72h_endurance_baseline", lambda **kwargs: {"passed": True, "checks": {}})
        monkeypatch.setattr(
            full_chain,
            "run_manage_brainstem_control_plane_ws28_017",
            lambda **kwargs: {
                "passed": True,
                "checks": {
                    "spawned": True,
                    "heartbeat_gate": True,
                    "launcher_pid_alive": True,
                    "manager_state_exists": True,
                },
                "heartbeat": {"checks": {"heartbeat_exists": True}},
                "state_file": "scratch/runtime/brainstem_control_plane_manager_ws28_017_state.json",
                "heartbeat_file": "scratch/runtime/brainstem_control_plane_heartbeat_ws23_001.json",
            },
        )
        monkeypatch.setattr(
            full_chain,
            "run_ws27_subagent_cutover_ws27_002",
            lambda **kwargs: {
                "passed": True,
                "checks": {
                    "subagent_runtime_enabled": True,
                    "rollout_percent_is_full": True,
                    "runtime_snapshot_ready": True,
                    "rollback_snapshot_exists": True,
                },
            }
            if str(kwargs.get("action") or "") == "status"
            else {"passed": True},
        )
        monkeypatch.setattr(full_chain, "run_ws27_oob_repair_drill_ws27_003", lambda **kwargs: {"passed": True})
        monkeypatch.setattr(
            full_chain,
            "_run_m12_execution_governance_gate_step",
            lambda **kwargs: {
                "passed": False,
                "checks": {
                    "runtime_posture_payload_success": True,
                    "incidents_payload_success": True,
                    "runtime_governance_status_not_critical": False,
                    "incidents_governance_status_not_critical": False,
                    "critical_governance_issue_count_zero": False,
                    "governance_warning_ratio_within_budget": False,
                    "governance_rejection_ratio_within_budget": False,
                },
            },
        )

        report = full_chain.run_release_closure_chain_full_m0_m12(
            repo_root=repo_root,
            output_file=Path("scratch/reports/full_m0_m12_governance_fail.json"),
            ws26_runtime_snapshot_report=runtime_snapshot,
            continue_on_failure=False,
        )
        assert report["passed"] is False
        assert report["failed_groups"] == ["m12_execution_governance"]
        assert "m12_execution_governance" in report["group_results"]
    finally:
        _cleanup_case_root(case_root)
