from __future__ import annotations

from autonomous.router_engine import RouterRequest, TaskRouterEngine


def test_router_engine_adds_prompt_profile_fields_for_read_only_research() -> None:
    router = TaskRouterEngine()
    decision = router.route(
        RouterRequest(
            task_id="ws28-001-readonly-research",
            description="分析文档并整理技术评估结论",
            estimated_complexity="medium",
            risk_level="read_only",
            budget_remaining=6000,
        )
    )

    assert decision.selected_role == "researcher"
    assert decision.selected_model_tier == "secondary"
    assert decision.delegation_intent == "read_only_exploration"
    assert decision.prompt_profile == "outer_readonly_research"
    assert decision.injection_mode == "minimal"
    payload = decision.to_dict()
    assert payload["prompt_profile"] == "outer_readonly_research"
    assert payload["injection_mode"] == "minimal"
    assert payload["delegation_intent"] == "read_only_exploration"


def test_router_engine_keeps_legacy_role_tier_behavior_for_high_risk_path() -> None:
    router = TaskRouterEngine()
    decision = router.route(
        RouterRequest(
            task_id="ws28-001-high-risk",
            description="执行生产环境发布并校验配置",
            estimated_complexity="high",
            risk_level="deploy",
            budget_remaining=16000,
            trace_id="trace-ws28-001",
        )
    )

    # Existing behavior remains unchanged.
    assert decision.selected_role == "sys_admin"
    assert decision.selected_model_tier == "primary"
    # New metadata is attached for prompt routing/injection.
    assert decision.delegation_intent == "core_execution"
    assert decision.prompt_profile == "core_exec_ops"
    assert decision.injection_mode == "hardened"


def test_router_engine_marks_explicit_role_delegate_and_recovery_mode() -> None:
    router = TaskRouterEngine()
    decision = router.route(
        RouterRequest(
            task_id="ws28-001-explicit-recovery",
            description="修复故障后执行回滚预案",
            estimated_complexity="medium",
            requested_role="developer",
            risk_level="read_only",
            budget_remaining=7000,
        )
    )

    assert decision.selected_role == "developer"
    assert decision.delegation_intent == "explicit_role_delegate"
    assert decision.prompt_profile == "explicit_role_delegate"
    assert decision.injection_mode == "recovery"
