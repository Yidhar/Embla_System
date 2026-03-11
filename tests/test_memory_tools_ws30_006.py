from __future__ import annotations

from pathlib import Path

import pytest

from agents.expert_agent import ExpertAgent, ExpertAgentConfig
from agents.memory.l1_memory import L1MemoryManager
from agents.memory.memory_tools import get_memory_tool_definitions, handle_memory_tool
from agents.pipeline import _build_runtime_tool_definitions
from agents.runtime.agent_session import AgentSessionStore
from agents.runtime.mailbox import AgentMailbox
from agents.runtime.parent_tools import handle_parent_tool_call
from agents.runtime.task_board import TaskBoardEngine, TaskItem, TaskStatus
from agents.runtime.tool_profiles import resolve_child_tool_capabilities


def _patch_parent_tool_runtime(monkeypatch, *, execution_backend: str = "boxlite", execution_root: str = "/workspace") -> None:
    monkeypatch.setattr(
        "agents.runtime.parent_tools.resolve_execution_runtime_metadata",
        lambda **kwargs: {
            "execution_backend_requested": execution_backend,
            "execution_backend": execution_backend,
            "execution_root": execution_root,
            "execution_profile": "default",
            "box_profile": "default",
            "box_provider": "sdk",
            "box_mount_mode": "rw",
            "box_fallback_reason": "",
        },
    )


@pytest.fixture
def memory_dir(tmp_path: Path) -> Path:
    return tmp_path / "memory"


@pytest.fixture
def mgr(memory_dir: Path) -> L1MemoryManager:
    return L1MemoryManager(memory_root=str(memory_dir))


@pytest.fixture
def store() -> AgentSessionStore:
    session_store = AgentSessionStore(db_path=":memory:")
    yield session_store
    session_store.close()


@pytest.fixture
def mailbox() -> AgentMailbox:
    session_mailbox = AgentMailbox(db_path=":memory:")
    yield session_mailbox
    session_mailbox.close()


@pytest.fixture
def task_board_engine(tmp_path: Path) -> TaskBoardEngine:
    engine = TaskBoardEngine(boards_dir=str(tmp_path / "boards"), db_path=str(tmp_path / "task_boards.db"))
    yield engine
    engine.close()


def _write_sample_domain_doc(mgr: L1MemoryManager, path: str = "domain/python_ast_patterns.md") -> None:
    mgr.write_memory_file(
        path,
        "# Python AST Patterns\n"
        "tags: #python #ast\n"
        "\n"
        "## Notes\n"
        "Line A\n"
        "Line B\n",
    )


def test_memory_tools_cover_crud_search_and_index(mgr: L1MemoryManager) -> None:
    write_result = handle_memory_tool(
        "memory_write",
        {
            "path": "domain/python_ast_patterns.md",
            "content": "# Python AST Patterns\ntags: #python #ast\n\nOptimistic locking notes.\n",
        },
        manager=mgr,
    )
    assert write_result["status"] == "success"

    list_result = handle_memory_tool("memory_list", {"scope": "domain"}, manager=mgr)
    assert "domain/python_ast_patterns.md" in list_result["items"]

    read_result = handle_memory_tool(
        "memory_read",
        {"path": "domain/python_ast_patterns.md", "start_line": 1, "end_line": 2},
        manager=mgr,
    )
    assert "Python AST Patterns" in read_result["content"]
    assert "#python" in read_result["content"]

    grep_result = handle_memory_tool(
        "memory_grep",
        {"pattern": "locking", "scope": "domain"},
        manager=mgr,
    )
    assert grep_result["count"] == 1
    assert grep_result["matches"][0]["path"] == "domain/python_ast_patterns.md"

    search_result = handle_memory_tool(
        "memory_search",
        {"query": "python ast", "scope": "domain", "tags": ["python"]},
        manager=mgr,
    )
    assert search_result["count"] >= 1
    assert search_result["hits"][0]["path"] == "domain/python_ast_patterns.md"

    index_result = handle_memory_tool("memory_index", {}, manager=mgr)
    assert index_result["status"] == "success"
    assert index_result["stats"]["domain"] >= 1


def test_memory_tools_support_precise_editing_and_conflict(mgr: L1MemoryManager) -> None:
    _write_sample_domain_doc(mgr)

    patch_result = handle_memory_tool(
        "memory_patch",
        {
            "path": "domain/python_ast_patterns.md",
            "edits": [
                {
                    "start_line": 5,
                    "end_line": 5,
                    "old_content": "Line A",
                    "new_content": "Line A+",
                }
            ],
        },
        manager=mgr,
    )
    assert patch_result["status"] == "success"

    insert_result = handle_memory_tool(
        "memory_insert",
        {
            "path": "domain/python_ast_patterns.md",
            "line": 5,
            "position": "after",
            "content": "Line A.5",
        },
        manager=mgr,
    )
    assert insert_result["status"] == "success"

    append_result = handle_memory_tool(
        "memory_append",
        {"path": "domain/python_ast_patterns.md", "content": "\n## Tail\nDone\n"},
        manager=mgr,
    )
    assert append_result["status"] == "success"

    replace_result = handle_memory_tool(
        "memory_replace",
        {
            "path": "domain/python_ast_patterns.md",
            "old_text": "Line B",
            "new_text": "Line B+",
            "expected_count": 1,
        },
        manager=mgr,
    )
    assert replace_result["status"] == "success"
    assert replace_result["replaced_count"] == 1

    final_text = mgr.read_memory_file("domain/python_ast_patterns.md")
    assert "Line A+" in final_text
    assert "Line A.5" in final_text
    assert "Line B+" in final_text
    assert "## Tail" in final_text

    conflict_result = handle_memory_tool(
        "memory_patch",
        {
            "path": "domain/python_ast_patterns.md",
            "edits": [
                {
                    "start_line": 5,
                    "end_line": 5,
                    "old_content": "stale content",
                    "new_content": "won't apply",
                }
            ],
        },
        manager=mgr,
    )
    assert conflict_result["status"] == "conflict"


def test_memory_tools_support_tag_link_deprecate_and_delete(mgr: L1MemoryManager) -> None:
    _write_sample_domain_doc(mgr, path="domain/knowledge_card.md")

    tag_result = handle_memory_tool(
        "memory_tag",
        {"path": "domain/knowledge_card.md", "tags": ["patterns", "knowledge"]},
        manager=mgr,
    )
    assert tag_result["status"] == "success"

    link_result = handle_memory_tool(
        "memory_link",
        {
            "path": "domain/knowledge_card.md",
            "target": "episodic/exp_20260306_example.md",
            "label": "Example Experience",
        },
        manager=mgr,
    )
    assert link_result["created"] is True

    deprecate_result = handle_memory_tool(
        "memory_deprecate",
        {
            "path": "domain/knowledge_card.md",
            "reason": "superseded by v2",
            "replacement_path": "domain/knowledge_card_v2.md",
        },
        manager=mgr,
    )
    assert deprecate_result["status"] == "success"

    deprecated_text = mgr.read_memory_file("domain/knowledge_card.md")
    assert "deprecated: true" in deprecated_text
    assert "#deprecated" in deprecated_text
    assert "Example Experience" in deprecated_text

    delete_result = handle_memory_tool(
        "memory_delete",
        {"path": "domain/knowledge_card.md"},
        manager=mgr,
    )
    assert delete_result["status"] == "success"
    assert delete_result["archived_path"].startswith(".deprecated/domain/")
    assert mgr.resolve_memory_path(delete_result["archived_path"], must_exist=True).exists()


def test_parent_spawn_resolves_preset_profile_to_minimal_subset(monkeypatch, store: AgentSessionStore, mailbox: AgentMailbox) -> None:
    _patch_parent_tool_runtime(monkeypatch)
    result = handle_parent_tool_call(
        "spawn_child_agent",
        {
            "role": "dev",
            "task_description": "重构 memory/domain/python_ast_patterns.md 的标签与索引",
            "tool_profile": "refactor",
        },
        parent_session_id="expert-1",
        store=store,
        mailbox=mailbox,
    )

    session = store.get(result["agent_id"])
    assert session is not None
    assert result["tool_profile"] == "refactor"
    assert result["tool_subset"] == ["memory_read", "memory_grep", "memory_patch", "memory_tag"]
    assert session.tool_profile == "refactor"
    assert session.tool_subset == ["memory_read", "memory_grep", "memory_patch", "memory_tag"]


def test_expert_spawn_devs_infers_memory_profile_for_memory_tasks(
    monkeypatch,
    store: AgentSessionStore,
    mailbox: AgentMailbox,
    task_board_engine: TaskBoardEngine,
) -> None:
    _patch_parent_tool_runtime(monkeypatch)
    expert = ExpertAgent(
        config=ExpertAgentConfig(expert_type="docs", tool_subset=["read_file"]),
        session_id="expert-memory-1",
        store=store,
        mailbox=mailbox,
        task_board_engine=task_board_engine,
    )
    tasks = [
        TaskItem(
            task_id="t-001",
            title="重构 memory/domain/python_ast_patterns.md",
            status=TaskStatus.PENDING,
            files=["memory/domain/python_ast_patterns.md"],
        )
    ]

    spawned = expert.spawn_devs(tasks)
    assert len(spawned) == 1
    dev_session = store.get(spawned[0]["agent_id"])
    assert dev_session is not None
    assert dev_session.tool_profile == "refactor"
    assert dev_session.tool_subset == ["memory_read", "memory_grep", "memory_patch", "memory_tag"]


def test_resolve_child_tool_capabilities_supports_custom_memory_aliases() -> None:
    resolution = resolve_child_tool_capabilities(
        role="dev",
        tool_profile=["read", "patch", "tag"],
        task_description="编辑 memory/domain/index.md",
    )
    assert resolution.profile_name == "custom"
    assert resolution.tool_subset == ["memory_read", "memory_patch", "memory_tag"]


def test_runtime_tool_definitions_only_inject_selected_memory_schemas() -> None:
    defs = _build_runtime_tool_definitions(["memory_read", "memory_patch"])
    assert [item["name"] for item in defs] == ["memory_read", "memory_patch"]

    patch_def = next(item for item in defs if item["name"] == "memory_patch")
    assert "edits" in patch_def["parameters"]["properties"]
    assert patch_def["parameters"]["required"] == ["path", "edits"]

    read_def = next(item for item in defs if item["name"] == "memory_read")
    assert read_def["parameters"]["required"] == ["path"]


def test_memory_tool_definitions_can_be_filtered() -> None:
    defs = get_memory_tool_definitions(["memory_read", "memory_tag"])
    assert [item["name"] for item in defs] == ["memory_read", "memory_tag"]
