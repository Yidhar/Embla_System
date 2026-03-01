from __future__ import annotations

import asyncio
from types import SimpleNamespace

from apiserver import api_server


def test_recall_memory_lines_falls_back_to_local_grag(monkeypatch):
    async def _fake_get_relevant_memories(_question: str, limit: int = 5):
        return [("服务A", "Service", "depends_on", "数据库B", "Database")][:limit]

    fake_manager = SimpleNamespace(
        enabled=True,
        get_relevant_memories=_fake_get_relevant_memories,
    )

    monkeypatch.setattr(
        "summer_memory.memory_client.get_remote_memory_client",
        lambda: None,
    )
    monkeypatch.setattr("summer_memory.memory_manager.memory_manager", fake_manager)

    lines = asyncio.run(api_server._recall_memory_lines("请检查依赖关系", limit=5))
    assert lines
    assert "服务A" in lines[0]
    assert "数据库B" in lines[0]
