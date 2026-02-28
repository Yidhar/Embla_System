from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

import apiserver.api_server as api_server


def test_get_system_config_includes_embla_system_payload(monkeypatch) -> None:
    monkeypatch.setattr(
        api_server,
        "get_config_snapshot",
        lambda: {"system": {"version": "5.0.0"}},
    )
    monkeypatch.setattr(
        api_server,
        "get_embla_system_config",
        lambda: {
            "version": 1,
            "security": {
                "audit_ledger_file": "scratch/runtime/audit_ledger.jsonl",
                "approval_required_scopes": ["core", "policy"],
            },
            "config_source": "/tmp/embla_system.yaml",
            "config_loaded": True,
        },
    )

    payload = asyncio.run(api_server.get_system_config())
    assert payload["status"] == "success"
    config = payload["config"]
    assert config["system"]["version"] == "5.0.0"
    assert config["embla_system"]["security"]["audit_ledger_file"] == "scratch/runtime/audit_ledger.jsonl"
    assert "config_source" not in config["embla_system"]
    assert "config_loaded" not in config["embla_system"]


def test_update_system_config_supports_embla_only_patch(monkeypatch) -> None:
    saved: dict = {}

    def _save(payload):
        saved.update(payload)
        return payload

    monkeypatch.setattr(api_server, "update_config", lambda _payload: True)
    monkeypatch.setattr(
        api_server,
        "get_embla_system_config",
        lambda: {
            "version": 1,
            "security": {
                "enforce_dual_lane": True,
                "audit_ledger_file": "scratch/runtime/audit_ledger.jsonl",
                "approval_required_scopes": ["core", "policy"],
            },
            "config_source": "/tmp/embla_system.yaml",
            "config_loaded": True,
        },
    )
    monkeypatch.setattr(api_server, "save_embla_system_config", _save)

    report = asyncio.run(
        api_server.update_system_config(
            {
                "embla_system": {
                    "security": {
                        "audit_ledger_file": "scratch/runtime/custom_ledger.jsonl",
                        "approval_required_scopes": ["policy"],
                    }
                }
            }
        )
    )
    assert report["status"] == "success"
    assert report["updated"]["config_json"] is False
    assert report["updated"]["embla_system_yaml"] is True
    assert saved["security"]["enforce_dual_lane"] is True
    assert saved["security"]["audit_ledger_file"] == "scratch/runtime/custom_ledger.jsonl"
    assert saved["security"]["approval_required_scopes"] == ["policy"]


def test_update_system_config_rejects_invalid_embla_patch(monkeypatch) -> None:
    monkeypatch.setattr(api_server, "update_config", lambda _payload: True)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(api_server.update_system_config({"embla_system": "invalid"}))
    assert exc.value.status_code == 400
