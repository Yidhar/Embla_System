from __future__ import annotations

from autonomous.llm_gateway import LLMGateway, GatewayRouteRequest, PromptEnvelopeInput


def test_llm_gateway_routes_by_task_type_severity_and_budget() -> None:
    gateway = LLMGateway(
        model_map={
            "primary": "openai/primary-large",
            "secondary": "openai/secondary-mini",
            "local": "local/log-parser-7b",
        }
    )

    primary = gateway.route(
        GatewayRouteRequest(task_type="code_generation", severity="critical", budget_remaining=15.0)
    )
    secondary = gateway.route(
        GatewayRouteRequest(task_type="memory_cleanup", severity="low", budget_remaining=8.0)
    )
    local = gateway.route(
        GatewayRouteRequest(task_type="heavy_log_parse", severity="medium", budget_remaining=30.0)
    )

    assert primary.model_tier == "primary"
    assert primary.model_id == "openai/primary-large"
    assert secondary.model_tier == "secondary"
    assert secondary.model_id == "openai/secondary-mini"
    assert local.model_tier == "local"
    assert local.model_id == "local/log-parser-7b"


def test_llm_gateway_prompt_envelope_uses_three_block_cache_policy() -> None:
    gateway = LLMGateway(block3_soft_limit_tokens=30)
    prompt_input = PromptEnvelopeInput(
        static_header="SYSTEM RULES " * 10,
        long_term_summary="LAST 24H SUMMARY " * 8,
        dynamic_messages=[
            {"role": "user", "content": "x" * 200},
            {"role": "assistant", "content": "y" * 120},
        ],
    )
    plan = gateway.build_plan(
        request=GatewayRouteRequest(task_type="code_generation", severity="high", budget_remaining=20.0),
        prompt_input=prompt_input,
    )

    assert plan.prompt_envelope.block1_cache == "ephemeral"
    assert plan.prompt_envelope.block2_cache == "ephemeral"
    assert plan.prompt_envelope.block3_cache == "none"
    assert plan.prompt_envelope.block3_soft_limit_exceeded is True
    assert plan.route.model_tier == "secondary"
    assert "requires GC before primary" in plan.route.reason


def test_llm_gateway_cache_hits_reduce_effective_tokens_and_latency() -> None:
    now = [1000.0]
    gateway = LLMGateway(
        block3_soft_limit_tokens=5000,
        block1_ttl_seconds=3600,
        block2_ttl_seconds=3600,
        now_fn=lambda: now[0],
    )
    prompt_input = PromptEnvelopeInput(
        static_header="DNA STATIC HEADER " * 60,
        long_term_summary="SUMMARY BLOCK " * 40,
        dynamic_messages=[{"role": "user", "content": "latest question"}],
    )
    request = GatewayRouteRequest(task_type="qa", severity="low", budget_remaining=6.0)

    first = gateway.build_plan(request=request, prompt_input=prompt_input)
    now[0] += 1.0
    second = gateway.build_plan(request=request, prompt_input=prompt_input)

    assert first.cache_outcome.block1_hit is False
    assert first.cache_outcome.block2_hit is False
    assert second.cache_outcome.block1_hit is True
    assert second.cache_outcome.block2_hit is True
    assert second.metrics.effective_prompt_tokens < first.metrics.effective_prompt_tokens
    assert second.metrics.estimated_latency_ms < first.metrics.estimated_latency_ms


def test_llm_gateway_local_tier_has_zero_api_cost_estimate() -> None:
    gateway = LLMGateway()
    plan = gateway.build_plan(
        request=GatewayRouteRequest(task_type="heavy_log_parse", severity="medium", budget_remaining=1.5),
        prompt_input=PromptEnvelopeInput(
            static_header="STATIC",
            long_term_summary="SUMMARY",
            dynamic_messages=[{"role": "user", "content": "parse giant k8s logs"}],
        ),
    )

    assert plan.route.model_tier == "local"
    assert plan.metrics.estimated_cost_units == 0.0
