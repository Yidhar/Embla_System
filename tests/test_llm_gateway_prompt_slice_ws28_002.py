from __future__ import annotations

from agents.llm_gateway import (
    LLMGateway,
    GatewayRouteRequest,
    PromptEnvelopeInput,
    PromptSlice,
)


def test_llm_gateway_compose_exposes_prefix_tail_hashes() -> None:
    gateway = LLMGateway()
    request = GatewayRouteRequest(task_type="qa", severity="low", budget_remaining=5.0, path="path-c")
    prompt_input = PromptEnvelopeInput(
        static_header="LEGACY_STATIC",
        long_term_summary="LEGACY_SUMMARY",
        dynamic_messages=[{"role": "user", "content": "explain current deployment posture"}],
        prompt_slices=[
            PromptSlice(
                slice_uid="slice_l0",
                layer="L0_DNA",
                text="DNA CORE",
                owner="system",
                cache_segment="prefix_static",
                priority=10,
            ),
            PromptSlice(
                slice_uid="slice_l2",
                layer="L2_ROLE",
                text="ROLE RULES",
                owner="router",
                cache_segment="prefix_session",
                priority=20,
            ),
            PromptSlice(
                slice_uid="slice_l1_5",
                layer="L1_5_EPISODIC_MEMORY",
                text="MEMORY SNAPSHOT",
                owner="memory",
                cache_segment="tail_dynamic",
                priority=30,
            ),
        ],
    )

    plan = gateway.build_plan(request=request, prompt_input=prompt_input)
    assert plan.compose_decision is not None
    decision = plan.compose_decision
    assert decision.prefix_hash
    assert decision.tail_hash
    assert decision.selected_slices == ["slice_l0", "slice_l2", "slice_l1_5"]
    assert decision.dropped_slices == []


def test_llm_gateway_path_a_drops_execution_dynamic_slices() -> None:
    gateway = LLMGateway()
    request = GatewayRouteRequest(task_type="qa", severity="low", budget_remaining=5.0, path="path-a")
    prompt_input = PromptEnvelopeInput(
        static_header="OUTER STATIC",
        long_term_summary="OUTER SUMMARY",
        dynamic_messages=[{"role": "user", "content": "please run write command"}],
        prompt_slices=[
            PromptSlice(
                slice_uid="slice_task",
                layer="L1_TASK_BASE",
                text="TASK BASE",
                owner="task",
                cache_segment="prefix_static",
                priority=10,
            ),
            PromptSlice(
                slice_uid="slice_exec_policy",
                layer="L3_TOOL_POLICY",
                text="WRITE ENABLED",
                owner="tool_policy",
                cache_segment="tail_dynamic",
                priority=20,
            ),
            PromptSlice(
                slice_uid="legacy_dynamic_message_0",
                layer="L4_RECOVERY",
                text='{"role":"user","content":"please run write command"}',
                owner="execution",
                cache_segment="tail_dynamic",
                priority=30,
            ),
        ],
    )

    plan = gateway.build_plan(request=request, prompt_input=prompt_input)
    assert plan.compose_decision is not None
    decision = plan.compose_decision
    assert "slice_exec_policy" in decision.dropped_slices
    assert "legacy_dynamic_message_0" in decision.dropped_slices
    assert "slice_exec_policy" not in decision.selected_slices
    assert "WRITE ENABLED" not in plan.prompt_envelope.block1_text
    assert "WRITE ENABLED" not in plan.prompt_envelope.block2_text
    assert plan.prompt_envelope.block3_messages == []


def test_llm_gateway_legacy_envelope_behavior_remains_compatible() -> None:
    gateway = LLMGateway(block3_soft_limit_tokens=30)
    request = GatewayRouteRequest(task_type="code_generation", severity="high", budget_remaining=20.0)
    prompt_input = PromptEnvelopeInput(
        static_header="SYSTEM RULES " * 10,
        long_term_summary="LAST 24H SUMMARY " * 8,
        dynamic_messages=[
            {"role": "user", "content": "x" * 200},
            {"role": "assistant", "content": "y" * 120},
        ],
    )

    plan = gateway.build_plan(request=request, prompt_input=prompt_input)
    assert plan.prompt_envelope.block1_text == prompt_input.static_header
    assert plan.prompt_envelope.block2_text == prompt_input.long_term_summary
    assert plan.prompt_envelope.block3_soft_limit_exceeded is True
    assert plan.route.model_tier == "secondary"
