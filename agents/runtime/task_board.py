"""TaskBoard engine: MD + SQLite dual-layer storage.

The MD file is the primary interface for LLM agents (read/write).
The SQLite layer provides indexed queries for system-level operations.
Both layers are kept in sync automatically via the TaskBoard API.

MD format example:
    # TaskBoard: tb-001 (backend)
    > Expert: backend | Goal: g-001

    ## 📋 任务列表

    - [x] t-001: AST 解析器 (@dev-α, ✅)
      - files: `file_ast.py`
      - acceptance: 解析 .py 定位函数/类
      - depends: (none)
    - [/] t-002: 乐观锁 (@dev-β, 🔄)
      - files: `file_ast.py`
      - depends: t-001
    - [ ] t-003: 冲突引擎 (未分配)
      - depends: t-001, t-002
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Data Structures ────────────────────────────────────────────

class TaskStatus:
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    DONE = "done"
    FAILED = "failed"


# Checkbox mapping
_STATUS_TO_CHECK = {
    TaskStatus.PENDING: "[ ]",
    TaskStatus.IN_PROGRESS: "[/]",
    TaskStatus.BLOCKED: "[!]",
    TaskStatus.DONE: "[x]",
    TaskStatus.FAILED: "[-]",
}

_CHECK_TO_STATUS = {v: k for k, v in _STATUS_TO_CHECK.items()}

_STATUS_EMOJI = {
    TaskStatus.PENDING: "",
    TaskStatus.IN_PROGRESS: "🔄",
    TaskStatus.BLOCKED: "🚫",
    TaskStatus.DONE: "✅",
    TaskStatus.FAILED: "❌",
}


@dataclass
class TaskItem:
    """A single task on a TaskBoard."""

    task_id: str = ""
    title: str = ""
    status: str = TaskStatus.PENDING
    assigned_to: str = ""
    depends_on: List[str] = field(default_factory=list)
    files: List[str] = field(default_factory=list)
    acceptance: str = ""
    summary: str = ""
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        if not self.task_id:
            self.task_id = f"t-{uuid.uuid4().hex[:6]}"
        now = _utc_now_iso()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "title": self.title,
            "status": self.status,
            "assigned_to": self.assigned_to,
            "depends_on": self.depends_on,
            "files": self.files,
            "acceptance": self.acceptance,
            "summary": self.summary,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class TaskBoard:
    """A collection of tasks managed by an Expert agent."""

    board_id: str = ""
    expert_type: str = ""
    goal_id: str = ""
    title: str = ""
    tasks: List[TaskItem] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        if not self.board_id:
            self.board_id = f"tb-{uuid.uuid4().hex[:6]}"
        now = _utc_now_iso()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now

    def progress_summary(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for t in self.tasks:
            counts[t.status] = counts.get(t.status, 0) + 1
        counts["total"] = len(self.tasks)
        return counts


# ── MD Rendering ───────────────────────────────────────────────

def render_task_board_md(board: TaskBoard) -> str:
    """Render a TaskBoard to Markdown format."""
    lines: List[str] = []
    lines.append(f"# TaskBoard: {board.board_id} ({board.expert_type})")
    lines.append(f"> Expert: {board.expert_type} | Goal: {board.goal_id}")
    lines.append("")
    lines.append("## 📋 任务列表")
    lines.append("")

    for task in board.tasks:
        check = _STATUS_TO_CHECK.get(task.status, "[ ]")
        emoji = _STATUS_EMOJI.get(task.status, "")
        assigned = f" (@{task.assigned_to}," if task.assigned_to else " ("
        status_label = f" {emoji})" if emoji else " )"
        if not task.assigned_to and not emoji:
            assigned = ""
            status_label = ""

        label = f"- {check} {task.task_id}: {task.title}"
        if task.assigned_to or emoji:
            label += f" (@{task.assigned_to}, {emoji})" if task.assigned_to else f" ({emoji})"
        lines.append(label)

        if task.files:
            file_str = ", ".join(f"`{f}`" for f in task.files)
            lines.append(f"  - files: {file_str}")
        if task.acceptance:
            lines.append(f"  - acceptance: {task.acceptance}")
        deps = ", ".join(task.depends_on) if task.depends_on else "(none)"
        lines.append(f"  - depends: {deps}")
        if task.summary:
            lines.append(f"  - summary: {task.summary}")

    lines.append("")

    # Progress section
    progress = board.progress_summary()
    done = progress.get(TaskStatus.DONE, 0)
    in_prog = progress.get(TaskStatus.IN_PROGRESS, 0)
    pending = progress.get(TaskStatus.PENDING, 0)
    blocked = progress.get(TaskStatus.BLOCKED, 0)
    failed = progress.get(TaskStatus.FAILED, 0)
    total = progress.get("total", 0)
    lines.append("## 📊 进度")
    parts = [f"Total: {total}", f"Done: {done}"]
    if in_prog:
        parts.append(f"In Progress: {in_prog}")
    if pending:
        parts.append(f"Pending: {pending}")
    if blocked:
        parts.append(f"Blocked: {blocked}")
    if failed:
        parts.append(f"Failed: {failed}")
    lines.append(f"- {' | '.join(parts)}")
    lines.append("")
    return "\n".join(lines)


# ── MD Parsing ─────────────────────────────────────────────────

_TASK_LINE_RE = re.compile(
    r"^- \[(.)\] (t-[\w]+): (.+?)(?:\s+\(@([\w-]+),\s*([^)]*)\))?$"
)
_META_LINE_RE = re.compile(r"^\s+- (\w+): (.+)$")
_HEADER_RE = re.compile(r"^# TaskBoard: ([\w-]+) \((\w+)\)$")
_META_HEADER_RE = re.compile(r"^> Expert: (\w+) \| Goal: ([\w-]+)$")


def parse_task_board_md(content: str) -> TaskBoard:
    """Parse a TaskBoard MD file back into a TaskBoard object."""
    lines = content.strip().split("\n")
    board = TaskBoard()

    # Parse header
    for line in lines:
        m = _HEADER_RE.match(line)
        if m:
            board.board_id = m.group(1)
            board.expert_type = m.group(2)
            break

    for line in lines:
        m = _META_HEADER_RE.match(line)
        if m:
            board.expert_type = m.group(1)
            board.goal_id = m.group(2)
            break

    # Parse tasks
    current_task: Optional[TaskItem] = None
    for line in lines:
        task_match = _TASK_LINE_RE.match(line)
        if task_match:
            if current_task:
                board.tasks.append(current_task)
            check_char = task_match.group(1)
            check_str = f"[{check_char}]"
            status = _CHECK_TO_STATUS.get(check_str, TaskStatus.PENDING)
            current_task = TaskItem(
                task_id=task_match.group(2),
                title=task_match.group(3).strip(),
                status=status,
                assigned_to=task_match.group(4) or "",
            )
            continue

        if current_task:
            meta_match = _META_LINE_RE.match(line)
            if meta_match:
                key = meta_match.group(1)
                val = meta_match.group(2).strip()
                if key == "files":
                    current_task.files = [f.strip().strip("`") for f in val.split(",")]
                elif key == "acceptance":
                    current_task.acceptance = val
                elif key == "depends":
                    if val != "(none)":
                        current_task.depends_on = [d.strip() for d in val.split(",")]
                elif key == "summary":
                    current_task.summary = val

    if current_task:
        board.tasks.append(current_task)

    return board


# ── SQLite Schema ──────────────────────────────────────────────

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS task_boards (
    board_id TEXT PRIMARY KEY,
    expert_type TEXT NOT NULL DEFAULT '',
    goal_id TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    md_path TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    board_id TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    assigned_to TEXT NOT NULL DEFAULT '',
    depends_on TEXT NOT NULL DEFAULT '[]',
    files TEXT NOT NULL DEFAULT '[]',
    acceptance TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (board_id) REFERENCES task_boards(board_id)
);

CREATE INDEX IF NOT EXISTS idx_tasks_board ON tasks(board_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_assigned ON tasks(assigned_to);
"""


# ── TaskBoard Engine ───────────────────────────────────────────

class TaskBoardEngine:
    """Dual-layer TaskBoard manager: MD files + SQLite index.

    Usage:
        engine = TaskBoardEngine(
            boards_dir="memory/working/boards",
            db_path="scratch/runtime/task_boards.db",
        )
        board = engine.create_board(expert_type="backend", goal_id="g-001", tasks=[...])
        md_content = engine.read_board_md(board.board_id)
        engine.update_task(board.board_id, "t-001", status="done", summary="completed")
        results = engine.query_tasks(status="blocked")
    """

    def __init__(
        self,
        *,
        boards_dir: str | Path = "memory/working/boards",
        db_path: str | Path | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._boards_dir = Path(boards_dir)
        self._boards_dir.mkdir(parents=True, exist_ok=True)

        resolved_db = str(db_path) if db_path else ":memory:"
        if db_path and str(db_path) != ":memory:":
            Path(resolved_db).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(resolved_db, check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(_SCHEMA_SQL)
        self._db.commit()

    # ── Board CRUD ─────────────────────────────────────────────

    def create_board(
        self,
        *,
        expert_type: str,
        goal_id: str = "",
        title: str = "",
        tasks: Optional[List[TaskItem]] = None,
        board_id: str = "",
    ) -> TaskBoard:
        """Create a new TaskBoard with optional initial tasks."""
        board = TaskBoard(
            board_id=board_id or "",
            expert_type=expert_type,
            goal_id=goal_id,
            title=title or f"TaskBoard ({expert_type})",
            tasks=list(tasks or []),
        )
        md_path = self._board_md_path(board.board_id)

        with self._lock:
            # Write MD
            md_content = render_task_board_md(board)
            md_path.write_text(md_content, encoding="utf-8")

            # Write SQLite
            self._persist_board(board, str(md_path))
            for task in board.tasks:
                self._persist_task(board.board_id, task)

        logger.info("Created board %s (%s) with %d tasks", board.board_id, expert_type, len(board.tasks))
        return board

    def get_board(self, board_id: str) -> Optional[TaskBoard]:
        """Get a TaskBoard by ID from SQLite."""
        with self._lock:
            cursor = self._db.execute(
                "SELECT board_id, expert_type, goal_id, title, created_at, updated_at "
                "FROM task_boards WHERE board_id = ?",
                (board_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None

            board = TaskBoard(
                board_id=row[0],
                expert_type=row[1],
                goal_id=row[2],
                title=row[3],
                created_at=row[4],
                updated_at=row[5],
            )

            tasks_cursor = self._db.execute(
                "SELECT task_id, title, status, assigned_to, depends_on, files, "
                "acceptance, summary, created_at, updated_at "
                "FROM tasks WHERE board_id = ? ORDER BY created_at ASC",
                (board_id,),
            )
            for tr in tasks_cursor.fetchall():
                board.tasks.append(TaskItem(
                    task_id=tr[0],
                    title=tr[1],
                    status=tr[2],
                    assigned_to=tr[3],
                    depends_on=json.loads(tr[4]),
                    files=json.loads(tr[5]),
                    acceptance=tr[6],
                    summary=tr[7],
                    created_at=tr[8],
                    updated_at=tr[9],
                ))
            return board

    def read_board_md(self, board_id: str) -> str:
        """Read the MD content for a TaskBoard (what the LLM sees)."""
        md_path = self._board_md_path(board_id)
        if not md_path.exists():
            return ""
        return md_path.read_text(encoding="utf-8")

    def add_task(self, board_id: str, task: TaskItem) -> TaskItem:
        """Add a task to an existing board."""
        with self._lock:
            self._persist_task(board_id, task)
            self._rebuild_md(board_id)
        logger.info("Added task %s to board %s", task.task_id, board_id)
        return task

    def update_task(
        self,
        board_id: str,
        task_id: str,
        *,
        status: Optional[str] = None,
        assigned_to: Optional[str] = None,
        summary: Optional[str] = None,
        files_changed: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Update a task's fields. Syncs both SQLite and MD."""
        now = _utc_now_iso()
        updates: List[str] = []
        params: List[Any] = []

        if status is not None:
            updates.append("status = ?")
            params.append(status)
        if assigned_to is not None:
            updates.append("assigned_to = ?")
            params.append(assigned_to)
        if summary is not None:
            updates.append("summary = ?")
            params.append(summary)
        if files_changed is not None:
            updates.append("files = ?")
            params.append(json.dumps(files_changed, ensure_ascii=False))

        if not updates:
            return {"updated": False, "reason": "no fields to update"}

        updates.append("updated_at = ?")
        params.append(now)
        params.extend([task_id, board_id])

        with self._lock:
            self._db.execute(
                f"UPDATE tasks SET {', '.join(updates)} WHERE task_id = ? AND board_id = ?",
                params,
            )
            self._db.execute(
                "UPDATE task_boards SET updated_at = ? WHERE board_id = ?",
                (now, board_id),
            )
            self._db.commit()
            self._rebuild_md(board_id)

        logger.info("Updated task %s on board %s", task_id, board_id)
        return {"updated": True, "task_id": task_id, "board_id": board_id}

    # ── Queries ────────────────────────────────────────────────

    def query_tasks(
        self,
        *,
        board_id: Optional[str] = None,
        status: Optional[str] = None,
        assigned_to: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Query tasks with optional filters."""
        conditions: List[str] = []
        params: List[Any] = []

        if board_id:
            conditions.append("board_id = ?")
            params.append(board_id)
        if status:
            conditions.append("status = ?")
            params.append(status)
        if assigned_to:
            conditions.append("assigned_to = ?")
            params.append(assigned_to)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        with self._lock:
            cursor = self._db.execute(
                f"SELECT task_id, board_id, title, status, assigned_to, depends_on, "
                f"files, acceptance, summary, updated_at FROM tasks {where} ORDER BY created_at ASC",
                params,
            )
            return [
                {
                    "task_id": r[0],
                    "board_id": r[1],
                    "title": r[2],
                    "status": r[3],
                    "assigned_to": r[4],
                    "depends_on": json.loads(r[5]),
                    "files": json.loads(r[6]),
                    "acceptance": r[7],
                    "summary": r[8],
                    "updated_at": r[9],
                }
                for r in cursor.fetchall()
            ]

    def list_boards(self) -> List[Dict[str, Any]]:
        """List all boards with progress summaries."""
        with self._lock:
            cursor = self._db.execute(
                "SELECT board_id, expert_type, goal_id, title, created_at, updated_at FROM task_boards"
            )
            boards = []
            for r in cursor.fetchall():
                tc = self._db.execute(
                    "SELECT status, COUNT(*) FROM tasks WHERE board_id = ? GROUP BY status",
                    (r[0],),
                )
                progress = {row[0]: row[1] for row in tc.fetchall()}
                progress["total"] = sum(progress.values())
                boards.append({
                    "board_id": r[0],
                    "expert_type": r[1],
                    "goal_id": r[2],
                    "title": r[3],
                    "progress": progress,
                    "created_at": r[4],
                    "updated_at": r[5],
                })
            return boards

    def close(self) -> None:
        self._db.close()

    # ── Private ────────────────────────────────────────────────

    def _board_md_path(self, board_id: str) -> Path:
        return self._boards_dir / f"task_board_{board_id}.md"

    def _persist_board(self, board: TaskBoard, md_path: str) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO task_boards (board_id, expert_type, goal_id, title, md_path, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (board.board_id, board.expert_type, board.goal_id, board.title, md_path, board.created_at, board.updated_at),
        )
        self._db.commit()

    def _persist_task(self, board_id: str, task: TaskItem) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO tasks "
            "(task_id, board_id, title, status, assigned_to, depends_on, files, acceptance, summary, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                task.task_id, board_id, task.title, task.status, task.assigned_to,
                json.dumps(task.depends_on, ensure_ascii=False),
                json.dumps(task.files, ensure_ascii=False),
                task.acceptance, task.summary, task.created_at, task.updated_at,
            ),
        )
        self._db.commit()

    def _rebuild_md(self, board_id: str) -> None:
        """Rebuild the MD file from SQLite state."""
        board = self.get_board(board_id)
        if not board:
            return
        md_path = self._board_md_path(board_id)
        md_content = render_task_board_md(board)
        md_path.write_text(md_content, encoding="utf-8")


__all__ = [
    "TaskBoard",
    "TaskBoardEngine",
    "TaskItem",
    "TaskStatus",
    "parse_task_board_md",
    "render_task_board_md",
]
