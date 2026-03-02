"""Expert Agent — domain-specialized task planner and Dev orchestrator.

Spawned by the Core Agent for a specific capability domain (backend, frontend, etc.).
Creates detailed TaskBoards, spawns Dev agents, and coordinates Review.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from agents.runtime.agent_session import AgentSessionStore, AgentStatus
from agents.runtime.mailbox import AgentMailbox
from agents.runtime.parent_tools import handle_parent_tool_call
from agents.runtime.task_board import TaskBoardEngine, TaskItem, TaskStatus

logger = logging.getLogger(__name__)


@dataclass
class ExpertAgentConfig:
    """Configuration for an Expert Agent instance."""

    expert_type: str = "backend"
    prompt_blocks: List[str] = field(default_factory=list)
    tool_subset: List[str] = field(default_factory=list)
    model_tier: str = "primary"
    prompt_profile: str = ""


class ExpertAgent:
    """Expert Agent: domain-specialized planner and orchestrator.

    Responsibilities:
        - Create detailed TaskBoard from assigned scope
        - Analyze task dependencies → determine parallelism
        - Spawn multiple Dev agents with appropriate toolsets
        - Monitor Dev progress via poll + message reading
        - Relay inter-Dev communication
        - Spawn Review agent when all tasks complete
        - Aggregate results and report to Core
    """

    def __init__(
        self,
        *,
        config: Optional[ExpertAgentConfig] = None,
        session_id: str = "",
        store: Optional[AgentSessionStore] = None,
        mailbox: Optional[AgentMailbox] = None,
        task_board_engine: Optional[TaskBoardEngine] = None,
    ) -> None:
        self._config = config or ExpertAgentConfig()
        self._session_id = session_id
        self._store = store or AgentSessionStore(db_path=":memory:")
        self._mailbox = mailbox or AgentMailbox(db_path=":memory:")
        self._task_board = task_board_engine
        self._board_id: str = ""

    @property
    def board_id(self) -> str:
        return self._board_id

    def plan_tasks(self, scope: str) -> List[TaskItem]:
        """Create a TaskBoard from the assigned scope.

        In production, this would use LLM to generate granular tasks.
        This implementation provides heuristic task splitting.
        """
        # Split scope lines into individual task items
        tasks: List[TaskItem] = []
        lines = [l.strip().lstrip("- ") for l in scope.split("\n") if l.strip() and not l.strip().startswith("[")]
        prev_id = ""
        for i, line in enumerate(lines):
            if not line or line.startswith(">"):
                continue
            task = TaskItem(
                task_id=f"t-{i+1:03d}",
                title=line[:100],
                status=TaskStatus.PENDING,
                depends_on=[prev_id] if prev_id else [],
            )
            tasks.append(task)
            prev_id = task.task_id

        # Create board if engine available
        if self._task_board and tasks:
            board = self._task_board.create_board(
                expert_type=self._config.expert_type,
                tasks=tasks,
            )
            self._board_id = board.board_id
            logger.info("Expert %s created board %s with %d tasks", self._session_id, board.board_id, len(tasks))

        return tasks

    def spawn_devs(
        self,
        tasks: List[TaskItem],
        *,
        prompt_blocks: Optional[List[str]] = None,
        memory_hints: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Spawn Dev agents for independent tasks.

        Groups tasks by dependency — independent tasks get parallel Devs.
        """
        results = []
        # Find tasks with no unfinished dependencies
        pending_ids = {t.task_id for t in tasks if t.status == TaskStatus.PENDING}

        for task in tasks:
            if task.status != TaskStatus.PENDING:
                continue
            # Check if all dependencies are done
            unmet = [d for d in task.depends_on if d in pending_ids]
            if unmet:
                continue  # will be spawned later when deps complete

            blocks = list(prompt_blocks or self._config.prompt_blocks)
            task_desc = f"Task {task.task_id}: {task.title}"
            if task.acceptance:
                task_desc += f"\nAcceptance: {task.acceptance}"
            if task.files:
                task_desc += f"\nFiles: {', '.join(task.files)}"
            if memory_hints:
                task_desc += f"\nRelevant experience: {', '.join(memory_hints)}"

            result = handle_parent_tool_call(
                "spawn_child_agent",
                {
                    "role": "dev",
                    "task_description": task_desc,
                    "prompt_blocks": blocks,
                    "tool_subset": list(self._config.tool_subset),
                },
                parent_session_id=self._session_id,
                store=self._store,
                mailbox=self._mailbox,
            )
            result["task_id"] = task.task_id

            # Assign dev to task
            if self._task_board and self._board_id:
                self._task_board.update_task(
                    self._board_id, task.task_id,
                    assigned_to=result.get("agent_id", ""),
                    status=TaskStatus.IN_PROGRESS,
                )
            results.append(result)

        return results

    def spawn_review(self) -> Dict[str, Any]:
        """Spawn a Review agent to verify all completed tasks."""
        task_desc = f"Review TaskBoard {self._board_id}: verify completeness, consistency, and correctness."
        if self._task_board and self._board_id:
            md = self._task_board.read_board_md(self._board_id)
            task_desc += f"\n\nTaskBoard:\n{md}"

        return handle_parent_tool_call(
            "spawn_child_agent",
            {
                "role": "review",
                "task_description": task_desc,
                "prompt_blocks": ["roles/code_reviewer.md"],
            },
            parent_session_id=self._session_id,
            store=self._store,
            mailbox=self._mailbox,
        )

    def check_progress(self) -> Dict[str, Any]:
        """Check the status of all spawned Dev agents."""
        children = self._store.list_children(self._session_id)
        devs = [c for c in children if c.role == "dev"]
        reviews = [c for c in children if c.role == "review"]

        dev_statuses = {
            "running": sum(1 for d in devs if d.status == AgentStatus.RUNNING),
            "waiting": sum(1 for d in devs if d.status == AgentStatus.WAITING),
            "total": len(devs),
        }

        board_progress = None
        if self._task_board and self._board_id:
            board = self._task_board.get_board(self._board_id)
            if board:
                board_progress = board.progress_summary()

        return {
            "expert_id": self._session_id,
            "expert_type": self._config.expert_type,
            "board_id": self._board_id,
            "dev_agents": dev_statuses,
            "review_agents": len(reviews),
            "board_progress": board_progress,
            "all_devs_done": all(d.status == AgentStatus.WAITING for d in devs) if devs else False,
        }

    def aggregate_results(self) -> str:
        """Aggregate all Dev reports into a summary for Core."""
        children = self._store.list_children(self._session_id)
        msgs = self._mailbox.read(self._session_id)

        parts = [f"## Expert Report: {self._config.expert_type}\n"]

        if self._task_board and self._board_id:
            board = self._task_board.get_board(self._board_id)
            if board:
                progress = board.progress_summary()
                parts.append(f"Tasks: {progress.get('done', 0)}/{progress.get('total', 0)} completed\n")

        for child in children:
            child_reports = [m for m in msgs if m.from_id == child.session_id]
            parts.append(f"### {child.role} ({child.session_id})")
            parts.append(f"Status: {child.status.value}")
            if child_reports:
                parts.append(f"Report: {child_reports[-1].content}")
            parts.append("")

        return "\n".join(parts)


__all__ = ["ExpertAgent", "ExpertAgentConfig"]
