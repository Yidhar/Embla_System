from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi import HTTPException

from apiserver.api_server import update_system_prompt_template_v1
import system.config as config_module


def _run(coro):
    return asyncio.run(coro)


def _install_temp_prompt_manager(tmp_path: Path, monkeypatch, *, acl_spec_text: str = "") -> Path:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    (prompts_dir / "conversation_style_prompt.txt").write_text("STYLE_V1", encoding="utf-8")
    (prompts_dir / "tool_dispatch_prompt.txt").write_text("DISPATCH_V1", encoding="utf-8")
    if acl_spec_text:
        (prompts_dir / "prompt_acl.spec").write_text(acl_spec_text, encoding="utf-8")
    manager = config_module.PromptManager(prompts_dir=str(prompts_dir))
    monkeypatch.setattr(config_module, "_prompt_manager", manager)
    return prompts_dir


def test_prompt_acl_s1_requires_ticket(monkeypatch, tmp_path: Path) -> None:
    _install_temp_prompt_manager(tmp_path, monkeypatch)

    with pytest.raises(HTTPException) as exc:
        _run(
            update_system_prompt_template_v1(
                "conversation_style_prompt",
                payload={"content": "STYLE_V2", "change_reason": "missing ticket should fail"},
            )
        )
    assert exc.value.status_code == 403
    assert isinstance(exc.value.detail, dict)
    assert exc.value.detail.get("code") == "PROMPT_ACL_APPROVAL_TICKET_REQUIRED"


def test_prompt_acl_s0_locked_is_always_rejected(monkeypatch, tmp_path: Path) -> None:
    _install_temp_prompt_manager(tmp_path, monkeypatch)

    with pytest.raises(HTTPException) as exc:
        _run(
            update_system_prompt_template_v1(
                "immutable_dna_manifest",
                payload={
                    "content": "MUTATED",
                    "approval_ticket": "TICKET-S0",
                    "change_reason": "attempt to update locked file",
                },
            )
        )
    assert exc.value.status_code == 403
    assert isinstance(exc.value.detail, dict)
    assert exc.value.detail.get("code") == "PROMPT_ACL_S0_LOCKED"


def test_prompt_acl_s2_flexible_allows_update_without_ticket(monkeypatch, tmp_path: Path) -> None:
    prompts_dir = _install_temp_prompt_manager(tmp_path, monkeypatch)
    (prompts_dir / "custom_prompt.txt").write_text("CUSTOM_V1", encoding="utf-8")

    payload = _run(
        update_system_prompt_template_v1(
            "custom_prompt",
            payload={"content": "CUSTOM_V2"},
        )
    )
    assert payload.get("status") == "success"
    acl = payload.get("acl", {})
    assert acl.get("matched_rule", {}).get("level") == "S2_FLEXIBLE"
    assert acl.get("blocked") is False
    assert (prompts_dir / "custom_prompt.txt").read_text(encoding="utf-8") == "CUSTOM_V2"
