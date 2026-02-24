from __future__ import annotations

from autonomous.meta_agent_runtime import Goal, MetaAgentRuntime, TaskFeedback


def test_meta_agent_can_decompose_typical_incident_goal() -> None:
    runtime = MetaAgentRuntime()
    goal = Goal(
        goal_id="goal-incident-001",
        description="""
        - 排查 nginx 502 错误根因
        - 修复相关 API 服务异常
        - 验证恢复效果并记录复盘
        """.strip(),
    )

    tasks = runtime.accept_goal(goal)
    assert len(tasks) == 3
    assert tasks[0].priority == 1
    assert tasks[1].priority == 2
    assert tasks[2].priority == 3
    assert tasks[0].target_role == "sys_admin"
    assert tasks[1].target_role == "developer"
    assert tasks[2].target_role in {"researcher", "sys_admin", "developer"}


def test_meta_agent_dispatch_respects_dependencies() -> None:
    routed_task_ids: list[str] = []

    def _dispatch(task):
        routed_task_ids.append(task.task_id)
        return {"accepted": True, "route": {"role": task.target_role}}

    runtime = MetaAgentRuntime(dispatch_fn=_dispatch)
    goal = Goal(goal_id="goal-incident-002", description="排查告警并修复服务并完成验证")
    tasks = runtime.accept_goal(goal)

    receipts = runtime.dispatch_goal(goal.goal_id)
    dispatched_ids = [receipt.task_id for receipt in receipts if receipt.dispatched]
    assert dispatched_ids == routed_task_ids

    order = {task_id: idx for idx, task_id in enumerate(routed_task_ids)}
    for task in tasks:
        for dep in task.dependencies:
            assert order[dep] < order[task.task_id]


def test_meta_agent_reflection_and_recovery_entrypoint() -> None:
    runtime = MetaAgentRuntime()
    goal = Goal(goal_id="goal-incident-003", description="检查部署问题; 回滚失败版本; 验证服务恢复")
    tasks = runtime.accept_goal(goal)

    runtime.collect_feedback(
        goal.goal_id,
        TaskFeedback(task_id=tasks[0].task_id, success=True, summary="诊断完成"),
    )
    runtime.collect_feedback(
        goal.goal_id,
        TaskFeedback(task_id=tasks[1].task_id, success=False, summary="回滚失败", details={"reason": "permission_denied"}),
    )

    reflection = runtime.reflect(goal.goal_id)
    assert reflection.progress_ratio > 0
    assert tasks[1].task_id in reflection.failed_task_ids
    assert reflection.retry_recommendations

    snapshot = runtime.build_recovery_snapshot(goal.goal_id)
    recovered = MetaAgentRuntime()
    recovered_goal_id = recovered.recover_from_snapshot(snapshot)
    recovered_reflection = recovered.reflect(recovered_goal_id)
    assert recovered_goal_id == goal.goal_id
    assert tasks[1].task_id in recovered_reflection.failed_task_ids
