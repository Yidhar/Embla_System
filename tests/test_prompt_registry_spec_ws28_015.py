from __future__ import annotations

import json
from pathlib import Path

import system.config as config_module


def _install_temp_prompt_manager_with_registry(tmp_path: Path, monkeypatch):
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    (prompts_dir / "layers" / "core").mkdir(parents=True, exist_ok=True)
    (prompts_dir / "layers" / "core" / "conversation_style_prompt.md").write_text("STYLE_V1", encoding="utf-8")
    (prompts_dir / "tool_dispatch_prompt.md").write_text("DISPATCH_V1", encoding="utf-8")

    spec_dir = prompts_dir / "specs"
    spec_dir.mkdir(parents=True, exist_ok=True)
    registry = {
        "schema_version": "ws28-prompt-registry-v1",
        "entries": [
            {
                "prompt_name": "conversation_style_prompt",
                "path": "layers/core/conversation_style_prompt.md",
                "aliases": ["conversation_composition_prompt"],
            },
            {
                "prompt_name": "tool_dispatch_prompt",
                "path": "tool_dispatch_prompt.md",
                "aliases": [],
            },
        ],
    }
    (spec_dir / "prompt_registry.spec").write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
    manager = config_module.PromptManager(prompts_dir=str(prompts_dir))
    monkeypatch.setattr(config_module, "_prompt_manager", manager)
    return prompts_dir, manager


def test_prompt_registry_alias_can_read_and_write_canonical_file(monkeypatch, tmp_path: Path) -> None:
    prompts_dir, manager = _install_temp_prompt_manager_with_registry(tmp_path, monkeypatch)
    assert manager.get_prompt("conversation_composition_prompt") == "STYLE_V1"

    manager.save_prompt("conversation_composition_prompt", "STYLE_V2")
    canonical_file = prompts_dir / "layers" / "core" / "conversation_style_prompt.md"
    assert canonical_file.read_text(encoding="utf-8") == "STYLE_V2"


def test_prompt_acl_evaluation_uses_registry_canonical_mapping(monkeypatch, tmp_path: Path) -> None:
    prompts_dir, _manager = _install_temp_prompt_manager_with_registry(tmp_path, monkeypatch)
    (prompts_dir / "prompt_acl.spec").write_text(
        json.dumps(
            {
                "enforcement_mode": "block",
                "rules": [
                    {
                        "path_pattern": "conversation_style_prompt.md",
                        "level": "S1_CONTROLLED",
                        "require_ticket": True,
                        "require_manifest_refresh": True,
                        "require_gate_verify": True,
                        "allow_ai_direct_write": False,
                    },
                    {
                        "path_pattern": "*.md",
                        "level": "S2_FLEXIBLE",
                        "require_ticket": False,
                        "require_manifest_refresh": False,
                        "require_gate_verify": False,
                        "allow_ai_direct_write": True,
                    },
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    decision = config_module.evaluate_prompt_acl(
        prompt_name="conversation_composition_prompt",
        prompts_dir=prompts_dir,
    )
    assert decision["prompt_name"] == "conversation_style_prompt"
    assert decision["requested_prompt_name"] == "conversation_composition_prompt"
    assert decision["blocked"] is True
    assert decision["reason_code"] == "PROMPT_ACL_APPROVAL_TICKET_REQUIRED"
    assert decision["matched_rule"]["path_pattern"] == "conversation_style_prompt.md"


def test_prompt_acl_loader_prefers_specs_path(monkeypatch, tmp_path: Path) -> None:
    prompts_dir, _manager = _install_temp_prompt_manager_with_registry(tmp_path, monkeypatch)
    (prompts_dir / "prompt_acl.spec").write_text(
        json.dumps({"enforcement_mode": "shadow", "rules": []}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (prompts_dir / "specs" / "prompt_acl.spec").write_text(
        json.dumps({"enforcement_mode": "block", "rules": []}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    acl_spec = config_module.load_prompt_acl_spec(prompts_dir=prompts_dir)
    assert acl_spec["enforcement_mode"] == "block"


def test_prompt_registry_missing_entry_defaults_to_markdown(monkeypatch, tmp_path: Path) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    manager = config_module.PromptManager(prompts_dir=str(prompts_dir))
    monkeypatch.setattr(config_module, "_prompt_manager", manager)

    resolved = config_module.resolve_prompt_registry_entry(prompt_name="custom_prompt", prompts_dir=prompts_dir)
    assert resolved["canonical_name"] == "custom_prompt"
    assert resolved["relative_path"] == "custom_prompt.md"
