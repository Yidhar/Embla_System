from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import summer_memory.memory_manager as memory_mod
import summer_memory.quintuple_graph as graph_mod


class _DummyCursor:
    def __init__(self, rows):
        self._rows = rows

    def data(self):
        return self._rows


class _DummyGraph:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def run(self, query: str, **_kwargs):
        self.calls.append(query)
        if "RETURN count(DISTINCT n)" in query:
            return _DummyCursor([{"deleted_nodes": 2, "deleted_relationships": 1}])
        return _DummyCursor([])


def test_clear_quintuples_store_removes_file_and_clears_neo4j(monkeypatch, tmp_path) -> None:
    quintuples_file = tmp_path / "knowledge_graph" / "quintuples.json"
    quintuples_file.parent.mkdir(parents=True, exist_ok=True)
    quintuples_file.write_text(
        json.dumps([["小明", "人物", "在", "公园", "地点"]], ensure_ascii=False),
        encoding="utf-8",
    )

    dummy_graph = _DummyGraph()
    monkeypatch.setattr(graph_mod, "QUINTUPLES_FILE", str(quintuples_file))
    monkeypatch.setattr(graph_mod, "get_graph", lambda: dummy_graph)
    monkeypatch.setattr(graph_mod, "_VECTOR_INDEX_READY", True, raising=False)
    monkeypatch.setattr(graph_mod, "_VECTOR_LAST_ERROR", "stale", raising=False)

    result = graph_mod.clear_quintuples_store()

    assert result["ok"] is True
    assert result["file_removed"] is True
    assert result["file_cleared"] is True
    assert result["neo4j_cleared"] is True
    assert result["neo4j_state"] == "cleared"
    assert result["deleted_nodes"] == 2
    assert result["deleted_relationships"] == 1
    assert not quintuples_file.exists()
    assert any("RETURN count(DISTINCT n)" in call for call in dummy_graph.calls)
    assert any("DETACH DELETE n" in call for call in dummy_graph.calls)
    assert graph_mod._VECTOR_INDEX_READY is False
    assert graph_mod._VECTOR_LAST_ERROR == ""


def test_grag_memory_manager_clear_memory_clears_persisted_graph(monkeypatch) -> None:
    cancelled: list[str] = []
    clear_calls: list[bool] = []

    dummy_task_manager = SimpleNamespace(
        on_task_completed=None,
        on_task_failed=None,
        cancel_task=lambda task_id: cancelled.append(task_id) or True,
    )
    monkeypatch.setattr(memory_mod, "task_manager", dummy_task_manager)
    monkeypatch.setattr(memory_mod, "start_auto_cleanup", lambda: None)
    monkeypatch.setattr(memory_mod, "clear_quintuples_store", lambda: clear_calls.append(True) or {"ok": True})
    monkeypatch.setattr(graph_mod, "get_graph", lambda: None)
    monkeypatch.setattr(graph_mod, "GRAG_ENABLED", False, raising=False)
    monkeypatch.setattr(
        memory_mod,
        "config",
        SimpleNamespace(
            grag=SimpleNamespace(
                enabled=True,
                auto_extract=True,
                context_length=5,
                similarity_threshold=0.6,
                extraction_timeout=9,
                extraction_retries=1,
            )
        ),
    )

    manager = memory_mod.GRAGMemoryManager()
    manager.recent_context.extend(["u", "a"])
    manager.extraction_cache.add("hash")
    manager.active_tasks.update({"task-1", "task-2"})

    ok = asyncio.run(manager.clear_memory())

    assert ok is True
    assert manager.recent_context == []
    assert manager.extraction_cache == set()
    assert manager.active_tasks == set()
    assert set(cancelled) == {"task-1", "task-2"}
    assert clear_calls == [True]
