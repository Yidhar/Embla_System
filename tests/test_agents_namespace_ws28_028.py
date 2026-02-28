from __future__ import annotations

from agents import Goal, MetaAgentRuntime, RouterRequest, TaskRouterEngine
from agents.memory import GCPipelineConfig


def test_agents_namespace_aliases_resolve() -> None:
    runtime = MetaAgentRuntime()
    goal = Goal(goal_id="goal-1", description="修复一次告警并验证")
    tasks = runtime.accept_goal(goal)
    assert len(tasks) >= 1

    router = TaskRouterEngine()
    decision = router.route(
        RouterRequest(
            task_id="task-1",
            description="修复 API bug 并补测试",
            risk_level="write_repo",
        )
    )
    assert decision.task_id == "task-1"
    assert decision.selected_role

    config = GCPipelineConfig()
    assert config.max_total_records > 0
