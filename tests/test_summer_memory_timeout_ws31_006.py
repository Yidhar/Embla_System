from __future__ import annotations

import asyncio
from types import SimpleNamespace

import summer_memory.memory_manager as memory_mod
import summer_memory.quintuple_graph as graph_mod
import summer_memory.task_manager as task_mod


def test_task_manager_uses_grag_extraction_timeout_and_retries(monkeypatch) -> None:
    monkeypatch.setattr(
        task_mod,
        "config",
        SimpleNamespace(
            grag=SimpleNamespace(
                enabled=True,
                extraction_timeout=7,
                extraction_retries=4,
            )
        ),
    )

    manager = task_mod.QuintupleTaskManager()

    assert manager.task_timeout == 7
    assert manager.extraction_retries == 4
    assert manager.enabled is True


def test_task_manager_timeout_returns_error_instead_of_raising(monkeypatch) -> None:
    monkeypatch.setattr(
        task_mod,
        "config",
        SimpleNamespace(
            grag=SimpleNamespace(
                enabled=True,
                extraction_timeout=1,
                extraction_retries=0,
            )
        ),
    )

    observed: dict[str, float | int] = {}

    async def _slow_extract(text: str, *, timeout_seconds: int | None = None, max_retries: int | None = None):
        del text
        observed["timeout_seconds"] = float(timeout_seconds or 0)
        observed["max_retries"] = int(max_retries or 0)
        await asyncio.sleep(0.2)
        return [("a", "人物", "做", "b", "物品")]

    monkeypatch.setattr("summer_memory.quintuple_extractor.extract_quintuples_async", _slow_extract)

    async def _run() -> tuple[list | None, str | None, task_mod.QuintupleTaskManager]:
        manager = task_mod.QuintupleTaskManager(max_workers=1, max_queue_size=8)
        manager.task_timeout = 0.05
        await manager.start()
        try:
            task_id = await manager.add_task("演示文本")
            result, error = await manager.get_task_result(task_id, timeout=1.0)
            return result, error, manager
        finally:
            await manager.shutdown()

    result, error, manager = asyncio.run(_run())

    assert result is None
    assert error == "任务执行超时(0.05s)"
    assert observed["timeout_seconds"] == 0.05
    assert observed["max_retries"] == 0
    assert manager.failed_tasks == 1


def test_grag_memory_manager_registers_failed_task_callback(monkeypatch) -> None:
    dummy_task_manager = SimpleNamespace(on_task_completed=None, on_task_failed=None)
    monkeypatch.setattr(memory_mod, "task_manager", dummy_task_manager)
    monkeypatch.setattr(memory_mod, "start_auto_cleanup", lambda: None)
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

    assert dummy_task_manager.on_task_completed == manager._on_task_completed_wrapper
    assert dummy_task_manager.on_task_failed == manager._on_task_failed_wrapper


def test_grag_memory_fallback_passes_timeout_budget_to_sync_extractor(monkeypatch) -> None:
    dummy_task_manager = SimpleNamespace(on_task_completed=None, on_task_failed=None)
    monkeypatch.setattr(memory_mod, "task_manager", dummy_task_manager)
    monkeypatch.setattr(memory_mod, "start_auto_cleanup", lambda: None)
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

    observed: dict[str, int] = {}

    def _extract(text: str, *, timeout_seconds: int | None = None, max_retries: int | None = None):
        del text
        observed["timeout_seconds"] = int(timeout_seconds or 0)
        observed["max_retries"] = int(max_retries or 0)
        return [("小明", "人物", "在", "公园", "地点")]

    monkeypatch.setattr(memory_mod, "extract_quintuples", _extract)
    monkeypatch.setattr(memory_mod, "store_quintuples", lambda rows: bool(rows))

    manager = memory_mod.GRAGMemoryManager()

    ok = asyncio.run(manager._extract_and_store_quintuples_fallback("小明在公园。"))

    assert ok is True
    assert observed == {"timeout_seconds": 9, "max_retries": 1}
