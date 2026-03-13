from __future__ import annotations

import json

from system.config import (
    get_immutable_agent_identity_prompts,
    get_immutable_dna_runtime_prompts,
    load_embla_system_config,
)


def test_load_embla_system_config_falls_back_to_defaults_when_missing(tmp_path) -> None:
    missing = tmp_path / "missing_embla_system.yaml"
    payload = load_embla_system_config(missing)

    assert payload["config_loaded"] is False
    assert payload["runtime"]["child_session_cleanup"]["mode"] == "retain"
    assert payload["runtime"]["child_session_cleanup"]["ttl_seconds"] == 86400
    assert payload["security"]["enforce_dual_lane"] is True
    assert payload["security"]["audit_ledger_file"] == "scratch/runtime/audit_ledger.jsonl"
    assert "policy" in payload["security"]["approval_required_scopes"]
    assert payload["security"]["immutable_dna_runtime_prompts"] == [
        "conversation_style_prompt",
        "agentic_tool_prompt",
    ]
    assert payload["security"]["immutable_agent_identity_prompts"] == [
        "shell_persona",
        "core_values",
    ]


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
    assert payload["runtime"]["child_session_cleanup"]["mode"] == "retain"
    assert payload["runtime"]["child_session_cleanup"]["ttl_seconds"] == 86400
    assert payload["security"]["enforce_dual_lane"] is False
    assert payload["security"]["approval_required_scopes"] == ["policy", "core"]
    assert payload["security"]["audit_ledger_file"] == "scratch/runtime/custom_audit_ledger.jsonl"
    assert payload["watchers"]["tools_registry_root"] == "workspace/tools_registry"
    assert payload["watchers"]["backend"] == "watchdog"


def test_load_embla_system_config_normalizes_child_session_cleanup_policy(tmp_path) -> None:
    config_path = tmp_path / "embla_system.yaml"
    config_path.write_text(
        json.dumps(
            {
                "runtime": {
                    "child_session_cleanup": {
                        "mode": "destroy_on_end",
                        "ttl_seconds": -5,
                    }
                }
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    payload = load_embla_system_config(config_path)
    cleanup = payload["runtime"]["child_session_cleanup"]
    assert cleanup["mode"] == "destroy"
    assert cleanup["ttl_seconds"] == 0


def test_load_embla_system_config_normalizes_legacy_immutable_prompt_file_references(tmp_path) -> None:
    config_path = tmp_path / "embla_system.yaml"
    config_path.write_text(
        json.dumps(
            {
                "security": {
                    "immutable_dna_runtime_prompts": [
                        "conversation_style_prompt.md",
                        "tool_call_contract_prompt",
                    ],
                    "immutable_agent_identity_prompts": [
                        "dna/shell_persona.md",
                        "core_values.md",
                    ],
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    payload = load_embla_system_config(config_path)
    security = payload["security"]
    assert security["immutable_dna_runtime_prompts"] == [
        "conversation_style_prompt",
        "agentic_tool_prompt",
    ]
    assert security["immutable_agent_identity_prompts"] == [
        "shell_persona",
        "core_values",
    ]


def test_get_immutable_prompt_getters_return_canonical_names(monkeypatch) -> None:
    monkeypatch.setattr(
        "system.config.get_embla_system_config",
        lambda: {
            "security": {
                "immutable_dna_runtime_prompts": ["conversation_style_prompt", "agentic_tool_prompt"],
                "immutable_agent_identity_prompts": ["shell_persona", "core_values"],
            }
        },
    )

    assert get_immutable_dna_runtime_prompts() == [
        "conversation_style_prompt",
        "agentic_tool_prompt",
    ]
    assert get_immutable_agent_identity_prompts() == [
        "shell_persona",
        "core_values",
    ]


def test_load_embla_system_config_drops_legacy_prompt_root_watcher(tmp_path) -> None:
    config_path = tmp_path / "embla_system.yaml"
    config_path.write_text(
        json.dumps(
            {
                "watchers": {
                    "prompt_root": "workspace/prompts",
                    "tools_registry_root": "workspace/custom_tools_registry",
                    "backend": "polling",
                }
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    payload = load_embla_system_config(config_path)
    watchers = payload["watchers"]
    assert "prompt_root" not in watchers
    assert watchers["tools_registry_root"] == "workspace/custom_tools_registry"
    assert watchers["backend"] == "polling"


def test_load_embla_system_config_drops_dead_immutable_paths_security_key(tmp_path) -> None:
    config_path = tmp_path / "embla_system.yaml"
    config_path.write_text(
        json.dumps(
            {
                "security": {
                    "immutable_paths": [
                        "core/**",
                        "workspace/prompts/immutable_dna.md",
                    ]
                }
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    payload = load_embla_system_config(config_path)
    security = payload["security"]
    assert "immutable_paths" not in security
