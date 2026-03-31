from __future__ import annotations

import pytest

from agents.runtime.agent_session import AgentSessionStore
from agents.runtime.mailbox import AgentMailbox
from agents.runtime.parent_tools import handle_parent_tool_call
from system.agent_profile_registry import (
    load_agent_profile_registry,
    resolve_agent_profile_defaults,
    upsert_agent_profile,
)


@pytest.fixture
def store():
    session_store = AgentSessionStore(db_path=":memory:")
    yield session_store
    session_store.close()


@pytest.fixture
def mailbox():
    agent_mailbox = AgentMailbox(db_path=":memory:")
    yield agent_mailbox
    agent_mailbox.close()


def _patch_parent_tool_runtime(monkeypatch, *, execution_backend: str = "native", execution_root: str = "/workspace") -> None:
    monkeypatch.setattr(
        "agents.runtime.parent_tools.resolve_execution_runtime_metadata",
        lambda **kwargs: {
            "execution_backend_requested": execution_backend,
            "execution_backend": execution_backend,
            "execution_root": execution_root,
            "execution_profile": "default",
            "box_profile": "",
            "box_provider": "",
            "box_mount_mode": "rw",
            "box_fallback_reason": "",
        },
    )


def test_load_agent_profile_registry_defaults(monkeypatch, tmp_path):
    registry_path = tmp_path / "agent_registry.spec"
    monkeypatch.setattr("system.agent_profile_registry._DEFAULT_REGISTRY_PATH", registry_path)

    registry = load_agent_profile_registry()

    assert registry["exists_on_disk"] is False
    assert registry["defaults_by_role"]["review"]["agent_type"] == "code_reviewer"
    assert any(item["agent_type"] == "dev_default" for item in registry["profiles"])
    assert all("prompts_root" not in item for item in registry["profiles"])


def test_upsert_agent_profile_overrides_role_default(monkeypatch, tmp_path):
    registry_path = tmp_path / "agent_registry.spec"
    monkeypatch.setattr("system.agent_profile_registry._DEFAULT_REGISTRY_PATH", registry_path)

    saved = upsert_agent_profile(
        {
            "agent_type": "frontend_dev",
            "role": "dev",
            "label": "Frontend Dev",
            "description": "Custom frontend implementation profile",
            "prompt_blocks": ["agents/review/code_reviewer.md"],
            "tool_profile": "bugfix",
            "default_for_role": True,
        }
    )
    resolved = resolve_agent_profile_defaults(role="dev")

    assert saved["agent_type"] == "frontend_dev"
    assert resolved["agent_type"] == "frontend_dev"
    assert resolved["tool_profile"] == "bugfix"
    assert resolved["prompt_blocks"] == ["agents/review/code_reviewer.md"]


def test_upsert_agent_profile_keeps_custom_prompts_root(monkeypatch, tmp_path):
    registry_path = tmp_path / "agent_registry.spec"
    monkeypatch.setattr("system.agent_profile_registry._DEFAULT_REGISTRY_PATH", registry_path)

    custom_root = tmp_path / "custom_prompts"
    saved = upsert_agent_profile(
        {
            "agent_type": "custom_dev",
            "role": "dev",
            "label": "Custom Dev",
            "prompt_blocks": ["agents/review/code_reviewer.md"],
            "tool_profile": "bugfix",
            "prompts_root": str(custom_root),
        }
    )

    registry = load_agent_profile_registry()
    row = next(item for item in registry["profiles"] if item["agent_type"] == "custom_dev")
    assert saved["prompts_root"] == str(custom_root)
    assert row["prompts_root"] == str(custom_root)


def test_spawn_child_agent_uses_explicit_agent_type(monkeypatch, tmp_path, store, mailbox):
    registry_path = tmp_path / "agent_registry.spec"
    monkeypatch.setattr("system.agent_profile_registry._DEFAULT_REGISTRY_PATH", registry_path)
    _patch_parent_tool_runtime(monkeypatch)

    upsert_agent_profile(
        {
            "agent_type": "strict_reviewer",
            "role": "review",
            "label": "Strict Reviewer",
            "prompt_blocks": ["agents/review/code_reviewer.md"],
            "tool_profile": "review",
            "default_for_role": False,
        }
    )

    result = handle_parent_tool_call(
        "spawn_child_agent",
        {
            "role": "review",
            "agent_type": "strict_reviewer",
            "task_description": "Review the completed patch",
        },
        parent_session_id="expert-1",
        store=store,
        mailbox=mailbox,
    )

    session = store.get(result["agent_id"])
    assert session is not None
    assert result["agent_type"] == "strict_reviewer"
    assert result["prompt_blocks"] == ["agents/review/code_reviewer.md"]
    assert session.metadata["agent_type"] == "strict_reviewer"
    assert session.prompt_blocks == ["agents/review/code_reviewer.md"]
    assert session.tool_profile == "review"


def test_spawn_child_agent_uses_review_role_default(monkeypatch, tmp_path, store, mailbox):
    registry_path = tmp_path / "agent_registry.spec"
    monkeypatch.setattr("system.agent_profile_registry._DEFAULT_REGISTRY_PATH", registry_path)
    _patch_parent_tool_runtime(monkeypatch)

    result = handle_parent_tool_call(
        "spawn_child_agent",
        {
            "role": "review",
            "task_description": "Review the completed patch",
        },
        parent_session_id="expert-1",
        store=store,
        mailbox=mailbox,
    )

    session = store.get(result["agent_id"])
    assert session is not None
    assert result["agent_type"] == "code_reviewer"
    assert result["prompt_blocks"] == ["agents/review/code_reviewer.md"]
    assert session.metadata["agent_type"] == "code_reviewer"
    assert session.tool_profile == "review"
