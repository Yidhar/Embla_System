from __future__ import annotations

import json

from system.config import load_embla_system_config


def test_load_embla_system_config_falls_back_to_defaults_when_missing(tmp_path) -> None:
    missing = tmp_path / "missing_embla_system.yaml"
    payload = load_embla_system_config(missing)

    assert payload["config_loaded"] is False
    assert payload["security"]["enforce_dual_lane"] is True
    assert payload["security"]["audit_ledger_file"] == "scratch/runtime/audit_ledger.jsonl"
    assert "policy" in payload["security"]["approval_required_scopes"]


def test_load_embla_system_config_merges_runtime_and_security_settings(tmp_path) -> None:
    config_path = tmp_path / "embla_system.yaml"
    config_path.write_text(
        json.dumps(
            {
                "runtime": {"max_task_cost_usd": 8.5},
                "security": {
                    "enforce_dual_lane": False,
                    "approval_required_scopes": ["policy", "core", "policy"],
                    "audit_ledger_file": "scratch/runtime/custom_audit_ledger.jsonl",
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    payload = load_embla_system_config(config_path)
    assert payload["config_loaded"] is True
    assert payload["runtime"]["max_task_cost_usd"] == 8.5
    assert payload["security"]["enforce_dual_lane"] is False
    assert payload["security"]["approval_required_scopes"] == ["policy", "core"]
    assert payload["security"]["audit_ledger_file"] == "scratch/runtime/custom_audit_ledger.jsonl"
