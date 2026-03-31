"""Tests for core execution contract payload + messages (ws28-008).

Migrated from api_server wrappers → agents.contract_runtime directly.
"""
from __future__ import annotations

import json

from agents.contract_runtime import (
    build_core_execution_contract_payload,
    build_core_execution_messages,
)


def test_core_execution_contract_payload_captures_recent_history() -> None:
    payload = build_core_execution_contract_payload(
        session_id="sess-contract",
        current_message="请修复接口并补充回归测试",
        recent_messages=[
            {"role": "user", "content": "先看一下最近错误"},
            {"role": "assistant", "content": "看到 500 错误集中在 /v1/chat"},
            {"role": "user", "content": "继续定位并修复"},
        ],
    )

    assert payload["contract_stage"] == "seed"
    assert payload["session_id"] == "sess-contract"
    assert payload["goal"].startswith("请修复接口")
    assert payload["recent_user_history"] == ["先看一下最近错误", "继续定位并修复"]
    assert payload["recent_assistant_history"] == ["看到 500 错误集中在 /v1/chat"]
    assert payload["evidence_path_hint"] == "scratch/reports/"


def test_core_execution_contract_payload_marks_followup_assumption() -> None:
    payload = build_core_execution_contract_payload(
        session_id="sess-followup",
        current_message="继续",
        recent_messages=[],
    )

    assert payload["goal"] == "继续"
    assert payload["assumptions"]
    assert any("续写" in item for item in payload["assumptions"])


def test_build_core_execution_messages_contract_only_shape() -> None:
    messages = build_core_execution_messages(
        session_id="sess-core-only",
        core_system_prompt="SYSTEM_PROMPT",
        current_message="请修复当前失败用例",
        recent_messages=[
            {"role": "user", "content": "昨天我们在讨论部署"},
            {"role": "assistant", "content": "你当时还在闲聊。"},
        ],
    )

    assert len(messages) == 3
    assert messages[0] == {"role": "system", "content": "SYSTEM_PROMPT"}
    assert messages[1]["role"] == "system"
    assert messages[2] == {"role": "user", "content": "请修复当前失败用例"}

    contract_blob = messages[1]["content"]
    assert contract_blob.startswith("[ExecutionContractInput]\n")
    payload = json.loads(contract_blob.split("\n", 1)[1])
    assert payload["goal"] == "请修复当前失败用例"
    assert payload["recent_user_history"] == ["昨天我们在讨论部署"]


def test_build_core_execution_messages_accepts_legacy_system_prompt_alias() -> None:
    messages = build_core_execution_messages(
        session_id="sess-core-legacy-alias",
        system_prompt="LEGACY_SYSTEM_PROMPT",
        current_message="继续推进",
        recent_messages=[],
    )

    assert len(messages) == 3
    assert messages[0] == {"role": "system", "content": "LEGACY_SYSTEM_PROMPT"}
