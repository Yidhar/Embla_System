from __future__ import annotations

from agents.router_engine import RouterRequest, TaskRouterEngine


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
    assert payload["workflow_entry_state"] == "planned"
    assert payload["controlled_execution_plan"]["schema_version"] == "ws28_router_workflow_engine.v1"


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
    assert decision.controlled_execution_plan["guardrails"]["requires_human_approval"] is True


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


def test_router_engine_marks_trivial_core_execution_as_fast_track() -> None:
    router = TaskRouterEngine()
    decision = router.route(
        RouterRequest(
            task_id="ws30-fast-track-trivial",
            description="修复一个拼写错误并更新单行注释",
            estimated_complexity="low",
            complexity_hint="trivial",
            risk_level="write_repo",
        )
    )

    assert decision.delegation_intent == "core_execution"
    assert decision.complexity_hint == "trivial"
    assert decision.core_route == "fast_track"
    assert decision.fast_track_candidate is True
    route_contract = decision.controlled_execution_plan.get("route_contract") or {}
    assert route_contract.get("core_route") == "fast_track"


def test_router_engine_blocks_fast_track_for_deploy_risk_even_if_trivial_hint() -> None:
    router = TaskRouterEngine()
    decision = router.route(
        RouterRequest(
            task_id="ws30-fast-track-high-risk",
            description="快速发布生产环境补丁",
            estimated_complexity="low",
            complexity_hint="trivial",
            risk_level="deploy",
        )
    )

    assert decision.delegation_intent == "core_execution"
    assert decision.complexity_hint == "trivial"
    assert decision.core_route == "standard"
    assert decision.fast_track_candidate is False
