"""Unit tests for TaskBoard engine — Phase 1.3 verification."""

from __future__ import annotations

import tempfile
import os

import pytest

from agents.runtime.task_board import (
    TaskBoard,
    TaskBoardEngine,
    TaskItem,
    TaskStatus,
    parse_task_board_md,
    render_task_board_md,
)


@pytest.fixture
def engine(tmp_path):
    e = TaskBoardEngine(
        boards_dir=str(tmp_path / "boards"),
        db_path=str(tmp_path / "task_boards.db"),
    )
    yield e
    e.close()


def _sample_tasks():
    return [
        TaskItem(task_id="t-001", title="AST 解析器", status=TaskStatus.DONE, assigned_to="dev-a",
                 files=["file_ast.py"], acceptance="解析 .py 定位函数", depends_on=[]),
        TaskItem(task_id="t-002", title="乐观锁校验", status=TaskStatus.IN_PROGRESS, assigned_to="dev-b",
                 files=["file_ast.py"], depends_on=["t-001"]),
        TaskItem(task_id="t-003", title="冲突引擎", status=TaskStatus.PENDING,
                 depends_on=["t-001", "t-002"]),
    ]


# ── MD Rendering Tests ────────────────────────────────────────

class TestMDRendering:

    def test_render_basic(self):
        board = TaskBoard(board_id="tb-001", expert_type="backend", goal_id="g-001", tasks=_sample_tasks())
        md = render_task_board_md(board)
        assert "# TaskBoard: tb-001 (backend)" in md
        assert "[x] t-001:" in md
        assert "[/] t-002:" in md
        assert "[ ] t-003:" in md
        assert "📊 进度" in md
        assert "Total: 3" in md

    def test_render_includes_files_and_deps(self):
        board = TaskBoard(board_id="tb-001", expert_type="backend", tasks=_sample_tasks())
        md = render_task_board_md(board)
        assert "`file_ast.py`" in md
        assert "depends: t-001, t-002" in md
        assert "depends: (none)" in md

    def test_render_empty_board(self):
        board = TaskBoard(board_id="tb-empty", expert_type="ops")
        md = render_task_board_md(board)
        assert "# TaskBoard: tb-empty (ops)" in md
        assert "Total: 0" in md


# ── MD Parsing Tests ───────────────────────────────────────────

class TestMDParsing:

    def test_roundtrip(self):
        original = TaskBoard(board_id="tb-001", expert_type="backend", goal_id="g-001", tasks=_sample_tasks())
        md = render_task_board_md(original)
        parsed = parse_task_board_md(md)

        assert parsed.board_id == "tb-001"
        assert parsed.expert_type == "backend"
        assert parsed.goal_id == "g-001"
        assert len(parsed.tasks) == 3

    def test_parse_statuses(self):
        original = TaskBoard(board_id="tb-st", expert_type="test", tasks=_sample_tasks())
        md = render_task_board_md(original)
        parsed = parse_task_board_md(md)

        statuses = {t.task_id: t.status for t in parsed.tasks}
        assert statuses["t-001"] == TaskStatus.DONE
        assert statuses["t-002"] == TaskStatus.IN_PROGRESS
        assert statuses["t-003"] == TaskStatus.PENDING

    def test_parse_dependencies(self):
        original = TaskBoard(board_id="tb-dep", expert_type="be", tasks=_sample_tasks())
        md = render_task_board_md(original)
        parsed = parse_task_board_md(md)

        deps = {t.task_id: t.depends_on for t in parsed.tasks}
        assert deps["t-001"] == []
        assert deps["t-002"] == ["t-001"]
        assert deps["t-003"] == ["t-001", "t-002"]


# ── TaskBoardEngine Tests ─────────────────────────────────────

class TestTaskBoardEngine:

    def test_create_and_get(self, engine):
        board = engine.create_board(expert_type="backend", goal_id="g-001", tasks=_sample_tasks())
        assert board.board_id.startswith("tb-")
        assert len(board.tasks) == 3

        fetched = engine.get_board(board.board_id)
        assert fetched is not None
        assert fetched.expert_type == "backend"
        assert len(fetched.tasks) == 3

    def test_read_md(self, engine):
        board = engine.create_board(expert_type="backend", tasks=_sample_tasks())
        md = engine.read_board_md(board.board_id)
        assert "# TaskBoard:" in md
        assert "[x] t-001:" in md

    def test_update_task_status(self, engine):
        board = engine.create_board(expert_type="backend", tasks=_sample_tasks())
        result = engine.update_task(board.board_id, "t-002", status=TaskStatus.DONE, summary="hash check works")
        assert result["updated"] is True

        fetched = engine.get_board(board.board_id)
        t002 = next(t for t in fetched.tasks if t.task_id == "t-002")
        assert t002.status == TaskStatus.DONE
        assert t002.summary == "hash check works"

        # Verify MD was also updated
        md = engine.read_board_md(board.board_id)
        # t-002 should now show [x] not [/]
        assert "[x] t-002:" in md

    def test_update_task_assigned(self, engine):
        board = engine.create_board(expert_type="be", tasks=_sample_tasks())
        engine.update_task(board.board_id, "t-003", assigned_to="dev-c", status=TaskStatus.IN_PROGRESS)
        fetched = engine.get_board(board.board_id)
        t003 = next(t for t in fetched.tasks if t.task_id == "t-003")
        assert t003.assigned_to == "dev-c"
        assert t003.status == TaskStatus.IN_PROGRESS

    def test_add_task(self, engine):
        board = engine.create_board(expert_type="backend", tasks=_sample_tasks())
        new_task = TaskItem(task_id="t-004", title="集成测试", depends_on=["t-001", "t-002", "t-003"])
        engine.add_task(board.board_id, new_task)

        fetched = engine.get_board(board.board_id)
        assert len(fetched.tasks) == 4
        t004 = next(t for t in fetched.tasks if t.task_id == "t-004")
        assert t004.title == "集成测试"

    def test_query_by_status(self, engine):
        engine.create_board(expert_type="be", tasks=_sample_tasks(), board_id="tb-q1")
        done = engine.query_tasks(status=TaskStatus.DONE)
        assert len(done) == 1
        assert done[0]["task_id"] == "t-001"

        pending = engine.query_tasks(status=TaskStatus.PENDING)
        assert len(pending) == 1

    def test_query_by_assigned(self, engine):
        engine.create_board(expert_type="be", tasks=_sample_tasks(), board_id="tb-q2")
        devb = engine.query_tasks(assigned_to="dev-b")
        assert len(devb) == 1
        assert devb[0]["task_id"] == "t-002"

    def test_query_by_board(self, engine):
        engine.create_board(expert_type="be", tasks=_sample_tasks(), board_id="tb-q3")
        engine.create_board(expert_type="fe", tasks=[TaskItem(task_id="t-fe-1", title="UI")], board_id="tb-q4")
        
        be_tasks = engine.query_tasks(board_id="tb-q3")
        assert len(be_tasks) == 3
        fe_tasks = engine.query_tasks(board_id="tb-q4")
        assert len(fe_tasks) == 1

    def test_list_boards(self, engine):
        engine.create_board(expert_type="backend", tasks=_sample_tasks(), board_id="tb-l1")
        engine.create_board(expert_type="testing", tasks=[], board_id="tb-l2")

        boards = engine.list_boards()
        assert len(boards) == 2
        be_board = next(b for b in boards if b["board_id"] == "tb-l1")
        assert be_board["progress"]["total"] == 3
        assert be_board["progress"].get("done", 0) == 1

    def test_progress_summary(self, engine):
        board = engine.create_board(expert_type="be", tasks=_sample_tasks())
        progress = board.progress_summary()
        assert progress["total"] == 3
        assert progress[TaskStatus.DONE] == 1
        assert progress[TaskStatus.IN_PROGRESS] == 1
        assert progress[TaskStatus.PENDING] == 1

    def test_md_file_created(self, engine, tmp_path):
        board = engine.create_board(expert_type="backend", tasks=_sample_tasks())
        md_path = tmp_path / "boards" / f"task_board_{board.board_id}.md"
        assert md_path.exists()
        content = md_path.read_text(encoding="utf-8")
        assert "# TaskBoard:" in content

    def test_nonexistent_board_returns_none(self, engine):
        assert engine.get_board("tb-nonexistent") is None
        assert engine.read_board_md("tb-nonexistent") == ""
