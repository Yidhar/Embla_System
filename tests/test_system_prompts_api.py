from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi import HTTPException

from apiserver.api_server import (
    get_system_prompt_template_v1,
    list_system_prompts_v1,
    update_system_prompt_template_v1,
)
import system.config as config_module


def _install_temp_prompt_manager(tmp_path: Path, monkeypatch) -> Path:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    (prompts_dir / "conversation_style_prompt.txt").write_text("STYLE_V1", encoding="utf-8")
    (prompts_dir / "tool_dispatch_prompt.txt").write_text("DISPATCH_V1", encoding="utf-8")
    manager = config_module.PromptManager(prompts_dir=str(prompts_dir))
    monkeypatch.setattr(config_module, "_prompt_manager", manager)
    return prompts_dir


def _run(coro):
    return asyncio.run(coro)


def test_v1_system_prompts_list_and_get(monkeypatch, tmp_path: Path) -> None:
    _install_temp_prompt_manager(tmp_path, monkeypatch)

    payload = _run(list_system_prompts_v1())
    assert payload.get("status") == "success"
    names = [str(item.get("name") or "") for item in payload.get("prompts", [])]
    assert "conversation_style_prompt" in names
    assert "tool_dispatch_prompt" in names

    detail = _run(get_system_prompt_template_v1("conversation_style_prompt"))
    assert detail.get("status") == "success"
    assert detail.get("name") == "conversation_style_prompt"
    assert detail.get("content") == "STYLE_V1"
    assert isinstance(detail.get("meta"), dict)


def test_v1_system_prompts_update(monkeypatch, tmp_path: Path) -> None:
    prompts_dir = _install_temp_prompt_manager(tmp_path, monkeypatch)

    payload = _run(
        update_system_prompt_template_v1(
            "conversation_style_prompt",
            payload={
                "content": "STYLE_V2",
                "approval_ticket": "TICKET-WS28-003",
                "change_reason": "refine style for ws28 controlled update",
            },
        )
    )
    assert payload.get("status") == "success"
    assert payload.get("name") == "conversation_style_prompt"
    assert isinstance(payload.get("acl"), dict)
    assert payload["acl"]["matched_rule"]["level"] == "S1_CONTROLLED"

    detail = _run(get_system_prompt_template_v1("conversation_style_prompt.txt"))
    assert detail.get("content") == "STYLE_V2"

    file_content = (prompts_dir / "conversation_style_prompt.txt").read_text(encoding="utf-8")
    assert file_content == "STYLE_V2"


def test_v1_system_prompts_reject_invalid_name(monkeypatch, tmp_path: Path) -> None:
    _install_temp_prompt_manager(tmp_path, monkeypatch)

    with pytest.raises(HTTPException) as exc:
        _run(get_system_prompt_template_v1("bad-name"))
    assert exc.value.status_code == 400
