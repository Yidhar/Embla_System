from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from apiserver.message_manager import MessageManager
from agents.shell_tools import handle_shell_tool
from summer_memory.memory_manager import GRAGMemoryManager
from system.config import AI_NAME


class _DummyMemoryManager:
    def __init__(self) -> None:
        self.enabled = True
        self.auto_extract = True
        self.calls: list[dict[str, object]] = []

    async def add_shell_round_memory(
        self,
        session_id: str,
        round_messages,
        *,
        latest_user_input: str = "",
        latest_ai_response: str = "",
    ) -> bool:
        self.calls.append(
            {
                "session_id": session_id,
                "round_messages": list(round_messages),
                "latest_user_input": latest_user_input,
                "latest_ai_response": latest_ai_response,
            }
        )
        return True


def test_add_shell_round_memory_extracts_from_complete_round_messages() -> None:
    manager = GRAGMemoryManager.__new__(GRAGMemoryManager)
    manager.enabled = True
    manager.auto_extract = True
    manager.context_length = 5
    manager.similarity_threshold = 0.5
    manager.recent_context = []
    manager.extraction_cache = set()
    manager.active_tasks = set()

    captured: dict[str, str] = {}

    async def fake_submit(extraction_text: str) -> bool:
        captured["text"] = extraction_text
        return True

    manager._submit_extraction_text = fake_submit  # type: ignore[attr-defined]

    round_messages = [
        {"role": "system", "content": "你是 Shell 助手。"},
        {"role": "user", "content": "记住我喜欢简洁回答"},
        {
            "role": "assistant",
            "content": "我先查一下。",
            "tool_calls": [
                {
                    "id": "call-1",
                    "function": {"name": "memory_search", "arguments": "{}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call-1", "content": '{"status":"success"}'},
        {"role": "assistant", "content": "好的，我会保持简洁。"},
    ]

    ok = asyncio.run(
        manager.add_shell_round_memory(
            "sess-shell-round",
            round_messages,
            latest_user_input="记住我喜欢简洁回答",
            latest_ai_response="好的，我会保持简洁。",
        )
    )

    assert ok is True
    assert "系统: 你是 Shell 助手。" in captured["text"]
    assert "用户: 记住我喜欢简洁回答" in captured["text"]
    assert "[tool_calls] memory_search" in captured["text"]
    assert "工具[call-1]: {\"status\":\"success\"}" in captured["text"]
    assert "好的，我会保持简洁。" in captured["text"]
    assert manager.recent_context == [f"用户: 记住我喜欢简洁回答\n{AI_NAME}: 好的，我会保持简洁。"]


def test_save_conversation_and_logs_only_triggers_shell_l2_when_enabled(monkeypatch) -> None:
    mgr = MessageManager()
    session_id = f"test-shell-l2-{uuid.uuid4().hex}"
    mgr.create_session(session_id=session_id, temporary=False)

    monkeypatch.setattr(mgr, "_save_session_to_disk", lambda _sid: None)
    monkeypatch.setattr(mgr, "save_conversation_log", lambda *_args, **_kwargs: None)

    dummy_memory = _DummyMemoryManager()
    import summer_memory.memory_manager as memory_module

    monkeypatch.setattr(memory_module, "memory_manager", dummy_memory)
    monkeypatch.setattr(asyncio, "create_task", lambda coro: asyncio.run(coro))

    try:
        mgr.save_conversation_and_logs(
            session_id,
            "hi",
            "hello",
            enable_shell_l2_extraction=False,
            shell_round_messages=[{"role": "user", "content": "hi"}],
        )
        assert dummy_memory.calls == []

        mgr.save_conversation_and_logs(
            session_id,
            "记住我的风格",
            "好的",
            enable_shell_l2_extraction=True,
            shell_round_messages=[
                {"role": "system", "content": "shell prompt"},
                {"role": "user", "content": "记住我的风格"},
                {"role": "assistant", "content": "好的"},
            ],
        )
        assert len(dummy_memory.calls) == 1
        call = dummy_memory.calls[0]
        assert call["session_id"] == session_id
        assert call["latest_user_input"] == "记住我的风格"
        assert call["latest_ai_response"] == "好的"
    finally:
        mgr.delete_session(session_id)


def test_memory_search_keeps_l1_and_reads_shell_l2(monkeypatch, tmp_path: Path) -> None:
    episodic = tmp_path / "memory" / "episodic"
    episodic.mkdir(parents=True)
    (episodic / "_index.md").write_text("- [exp_001.md] 简洁回答\n", encoding="utf-8")

    import summer_memory.quintuple_graph as quintuple_graph

    monkeypatch.setattr(
        quintuple_graph,
        "query_graph_by_keywords",
        lambda keywords: [("用户", "person", "偏好", "简洁回答", "style")] if keywords == ["简洁回答"] else [],
    )
    monkeypatch.setattr(
        quintuple_graph,
        "get_all_quintuples",
        lambda: {("用户", "person", "偏好", "简洁回答", "style")},
    )

    result = handle_shell_tool(
        "memory_search",
        {"query": "简洁回答"},
        project_root=tmp_path,
    )
    assert result["status"] == "success"
    assert "L1 关键词匹配" in result["result"]
    assert "Shell L2 五元组图谱" in result["result"]
    assert "用户(person) —[偏好]→ 简洁回答(style)" in result["result"]
