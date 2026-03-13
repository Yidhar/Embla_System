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


def _install_temp_prompts_root(tmp_path: Path, monkeypatch) -> Path:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    (prompts_dir / "core" / "dna").mkdir(parents=True, exist_ok=True)
    (prompts_dir / "core" / "routing").mkdir(parents=True, exist_ok=True)
    (prompts_dir / "core" / "dna" / "conversation_style_prompt.md").write_text("STYLE_V1", encoding="utf-8")
    (prompts_dir / "core" / "routing" / "tool_dispatch_prompt.md").write_text("DISPATCH_V1", encoding="utf-8")
    monkeypatch.setattr(config_module, "get_system_prompts_root", lambda: prompts_dir)
    return prompts_dir


def _run(coro):
    return asyncio.run(coro)


def test_v1_system_prompts_list_and_get(monkeypatch, tmp_path: Path) -> None:
    _install_temp_prompts_root(tmp_path, monkeypatch)

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


def test_v1_system_prompts_list_prefers_registry_nested_paths(monkeypatch, tmp_path: Path) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    nested = prompts_dir / "layers" / "core"
    nested.mkdir(parents=True, exist_ok=True)
    (nested / "conversation_style_prompt.md").write_text("STYLE_NESTED_V1", encoding="utf-8")
    (prompts_dir / "tool_dispatch_prompt.md").write_text("DISPATCH_V1", encoding="utf-8")
    spec_dir = prompts_dir / "specs"
    spec_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / "prompt_registry.spec").write_text(
        """
        {
          "schema_version": "ws28-prompt-registry-v1",
          "entries": [
            {"prompt_name": "conversation_style_prompt", "path": "layers/core/conversation_style_prompt.md", "aliases": []},
            {"prompt_name": "tool_dispatch_prompt", "path": "tool_dispatch_prompt.md", "aliases": []}
          ]
        }
        """,
        encoding="utf-8",
    )
    monkeypatch.setattr(config_module, "get_system_prompts_root", lambda: prompts_dir)

    payload = _run(list_system_prompts_v1())
    prompts = payload.get("prompts", [])
    style_rows = [item for item in prompts if str(item.get("name") or "") == "conversation_style_prompt"]
    assert style_rows
    assert style_rows[0].get("relative_path") == "layers/core/conversation_style_prompt.md"
    assert style_rows[0].get("source") == "registry"

    detail = _run(get_system_prompt_template_v1("conversation_style_prompt"))
    assert detail.get("content") == "STYLE_NESTED_V1"


def test_v1_system_prompts_update(monkeypatch, tmp_path: Path) -> None:
    prompts_dir = _install_temp_prompts_root(tmp_path, monkeypatch)

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

    detail = _run(get_system_prompt_template_v1("conversation_style_prompt"))
    assert detail.get("content") == "STYLE_V2"

    file_content = (prompts_dir / "core" / "dna" / "conversation_style_prompt.md").read_text(encoding="utf-8")
    assert file_content == "STYLE_V2"


def test_v1_system_prompts_reject_invalid_name(monkeypatch, tmp_path: Path) -> None:
    _install_temp_prompts_root(tmp_path, monkeypatch)

    with pytest.raises(HTTPException) as exc:
        _run(get_system_prompt_template_v1("bad-name"))
    assert exc.value.status_code == 400
