"""WS19-001 meta-agent runtime skeleton."""

from __future__ import annotations

import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Goal:
    goal_id: str
    description: str
    context_files: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=_utc_iso)


@dataclass
class SubTask:
    task_id: str
    parent_goal_id: str
    description: str
    target_role: str
    priority: int
    estimated_complexity: str
    dependencies: List[str] = field(default_factory=list)
    context_files: List[str] = field(default_factory=list)
    success_criteria: str = ""
    status: str = "pending"


@dataclass(frozen=True)
class TaskFeedback:
    task_id: str
    success: bool
    summary: str
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReflectionResult:
    goal_id: str
    summary: str
    progress_ratio: float
    failed_task_ids: List[str]
    retry_recommendations: List[str]


@dataclass(frozen=True)
class DispatchReceipt:
    task_id: str
    dispatched: bool
    target_role: str
    blocked_by: List[str] = field(default_factory=list)
    route_metadata: Dict[str, Any] = field(default_factory=dict)


DispatchFn = Callable[[SubTask], Dict[str, Any]]


class MetaAgentRuntime:
    """Goal decomposition + dispatch + reflection + recovery entrypoint."""

    def __init__(self, *, dispatch_fn: Optional[DispatchFn] = None) -> None:
        self._dispatch_fn = dispatch_fn or self._default_dispatch
        self._goals: Dict[str, Goal] = {}
        self._task_trees: Dict[str, List[SubTask]] = {}
        self._feedback: Dict[str, List[TaskFeedback]] = {}

    @staticmethod
    def _default_dispatch(task: SubTask) -> Dict[str, Any]:
        return {"accepted": True, "route": {"role": task.target_role}}

    def accept_goal(self, goal: Goal) -> List[SubTask]:
        tasks = self.prioritize(self.decompose_goal(goal))
        self._goals[goal.goal_id] = goal
        self._task_trees[goal.goal_id] = tasks
        self._feedback.setdefault(goal.goal_id, [])
        return tasks

    def decompose_goal(self, goal: Goal) -> List[SubTask]:
        fragments = self._split_goal(goal.description)
        if not fragments:
            fragments = [goal.description.strip() or "执行目标"]

        tasks: List[SubTask] = []
        for idx, fragment in enumerate(fragments, start=1):
            description = fragment.strip()
            if not description:
                continue
            role = self._infer_role(description)
            complexity = self._infer_complexity(description)
            dependencies = [tasks[-1].task_id] if idx > 1 and tasks else []
            tasks.append(
                SubTask(
                    task_id=f"task_{uuid.uuid4().hex[:10]}",
                    parent_goal_id=goal.goal_id,
                    description=description,
                    target_role=role,
                    priority=idx,
                    estimated_complexity=complexity,
                    dependencies=dependencies,
                    context_files=list(goal.context_files),
                    success_criteria=f"完成子任务: {description}",
                )
            )

        return tasks

    def prioritize(self, tasks: List[SubTask]) -> List[SubTask]:
        return sorted(tasks, key=lambda item: (item.priority, len(item.dependencies), item.task_id))

    def dispatch_goal(self, goal_id: str) -> List[DispatchReceipt]:
        tasks = list(self._task_trees.get(goal_id, []))
        completed = {task.task_id for task in tasks if task.status == "completed"}
        receipts: List[DispatchReceipt] = []
        progress_made = True

        while progress_made:
            progress_made = False
            for task in self.prioritize(tasks):
                if task.status != "pending":
                    continue

                blocked_by = [dep for dep in task.dependencies if dep not in completed]
                if blocked_by:
                    receipts.append(
                        DispatchReceipt(
                            task_id=task.task_id,
                            dispatched=False,
                            target_role=task.target_role,
                            blocked_by=blocked_by,
                            route_metadata={"reason": "dependency_not_ready"},
                        )
                    )
                    continue

                route = self._dispatch_fn(task)
                accepted = bool((route or {}).get("accepted", True))
                task.status = "in_progress" if accepted else "failed"
                receipts.append(
                    DispatchReceipt(
                        task_id=task.task_id,
                        dispatched=accepted,
                        target_role=task.target_role,
                        route_metadata=route or {},
                    )
                )
                progress_made = True

        self._task_trees[goal_id] = tasks
        return receipts

    def collect_feedback(self, goal_id: str, feedback: TaskFeedback) -> None:
        tasks = self._task_trees.get(goal_id, [])
        for task in tasks:
            if task.task_id != feedback.task_id:
                continue
            task.status = "completed" if feedback.success else "failed"
            break
        self._feedback.setdefault(goal_id, []).append(feedback)
        self._task_trees[goal_id] = tasks

    def reflect(self, goal_id: str) -> ReflectionResult:
        tasks = self._task_trees.get(goal_id, [])
        total = len(tasks)
        completed = [task.task_id for task in tasks if task.status == "completed"]
        failed = [task.task_id for task in tasks if task.status == "failed"]
        progress_ratio = 0.0 if total == 0 else len(completed) / total

        if failed:
            summary = f"目标 {goal_id} 有失败子任务，需要重试或策略调整"
        elif progress_ratio >= 1.0 and total > 0:
            summary = f"目标 {goal_id} 已完成"
        else:
            summary = f"目标 {goal_id} 正在推进中"

        retry = [f"重试任务 {task_id} 并补充上下文证据" for task_id in failed]
        return ReflectionResult(
            goal_id=goal_id,
            summary=summary,
            progress_ratio=progress_ratio,
            failed_task_ids=failed,
            retry_recommendations=retry,
        )

    def build_recovery_snapshot(self, goal_id: str) -> Dict[str, Any]:
        goal = self._goals.get(goal_id)
        tasks = self._task_trees.get(goal_id, [])
        feedback = self._feedback.get(goal_id, [])
        return {
            "goal": asdict(goal) if goal else {"goal_id": goal_id, "description": "", "context_files": [], "created_at": _utc_iso()},
            "tasks": [asdict(task) for task in tasks],
            "feedback": [asdict(item) for item in feedback],
            "snapshot_ts": _utc_iso(),
        }

    def recover_from_snapshot(self, snapshot: Dict[str, Any]) -> str:
        goal_payload = snapshot.get("goal") if isinstance(snapshot.get("goal"), dict) else {}
        goal = Goal(
            goal_id=str(goal_payload.get("goal_id") or f"goal_{uuid.uuid4().hex[:8]}"),
            description=str(goal_payload.get("description") or ""),
            context_files=list(goal_payload.get("context_files") or []),
            created_at=str(goal_payload.get("created_at") or _utc_iso()),
        )

        recovered_tasks: List[SubTask] = []
        for raw_task in snapshot.get("tasks") or []:
            if not isinstance(raw_task, dict):
                continue
            recovered_tasks.append(
                SubTask(
                    task_id=str(raw_task.get("task_id") or f"task_{uuid.uuid4().hex[:10]}"),
                    parent_goal_id=str(raw_task.get("parent_goal_id") or goal.goal_id),
                    description=str(raw_task.get("description") or ""),
                    target_role=str(raw_task.get("target_role") or "researcher"),
                    priority=max(1, int(raw_task.get("priority") or 1)),
                    estimated_complexity=str(raw_task.get("estimated_complexity") or "medium"),
                    dependencies=list(raw_task.get("dependencies") or []),
                    context_files=list(raw_task.get("context_files") or []),
                    success_criteria=str(raw_task.get("success_criteria") or ""),
                    status=str(raw_task.get("status") or "pending"),
                )
            )

        recovered_feedback: List[TaskFeedback] = []
        for item in snapshot.get("feedback") or []:
            if not isinstance(item, dict):
                continue
            recovered_feedback.append(
                TaskFeedback(
                    task_id=str(item.get("task_id") or ""),
                    success=bool(item.get("success")),
                    summary=str(item.get("summary") or ""),
                    details=dict(item.get("details") or {}),
                )
            )

        self._goals[goal.goal_id] = goal
        self._task_trees[goal.goal_id] = self.prioritize(recovered_tasks)
        self._feedback[goal.goal_id] = recovered_feedback
        return goal.goal_id

    @staticmethod
    def _split_goal(description: str) -> List[str]:
        text = str(description or "").strip()
        if not text:
            return []

        bullet_lines = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if re.match(r"^[-*•]\s+", line):
                bullet_lines.append(re.sub(r"^[-*•]\s+", "", line).strip())
        if bullet_lines:
            return bullet_lines

        fragments = re.split(r"[；;。.!?\n]+|(?:\s+and\s+)", text)
        cleaned = [fragment.strip() for fragment in fragments if fragment.strip()]
        return cleaned

    @staticmethod
    def _infer_role(description: str) -> str:
        lowered = description.lower()
        if any(token in lowered for token in ("nginx", "k8s", "kubernetes", "docker", "cpu", "memory", "disk", "网络")):
            return "sys_admin"
        if any(token in lowered for token in ("代码", "code", "api", "refactor", "bug", "测试", "test", "patch")):
            return "developer"
        return "researcher"

    @staticmethod
    def _infer_complexity(description: str) -> str:
        length = len(description)
        lowered = description.lower()
        if length > 100 or any(token in lowered for token in ("重构", "refactor", "migrate", "migration", "体系")):
            return "high"
        if length > 45 or any(token in lowered for token in ("排查", "investigate", "analyze", "verify")):
            return "medium"
        return "low"
