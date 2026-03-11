from __future__ import annotations

from types import SimpleNamespace

from apiserver.llm_service import LLMService


def test_build_reasoning_effort_params_for_gpt5_family() -> None:
    service = LLMService()

    assert service._build_reasoning_effort_params(
        model_name="openai/gpt-5.2",
        reasoning_effort="high",
    ) == {"reasoning_effort": "high"}
    assert service._build_reasoning_effort_params(
        model_name="openai/gpt-5-mini",
        reasoning_effort="low",
    ) == {"reasoning_effort": "low"}
    assert service._build_reasoning_effort_params(
        model_name="openai/gpt-5.2",
        reasoning_effort="xhigh",
    ) == {"reasoning_effort": "xhigh"}


def test_build_reasoning_effort_params_ignores_invalid_or_unsupported() -> None:
    service = LLMService()

    assert service._build_reasoning_effort_params(
        model_name="openai/gpt-4.1",
        reasoning_effort="high",
    ) == {}
    assert service._build_reasoning_effort_params(
        model_name="openai/gpt-5.2",
        reasoning_effort="extreme",
    ) == {}
    assert service._build_reasoning_effort_params(
        model_name="openai/gpt-5.2",
        reasoning_effort="",
    ) == {}


def test_resolve_reasoning_effort_priority_override_then_global_then_legacy() -> None:
    cfg = SimpleNamespace(reasoning_effort="low", thinking_intensity="high")

    assert LLMService._resolve_reasoning_effort(config_api=cfg, override_value="medium") == "medium"
    assert LLMService._resolve_reasoning_effort(config_api=cfg, override_value="") == "low"

    fallback_cfg = SimpleNamespace(reasoning_effort="", thinking_intensity="high")
    assert LLMService._resolve_reasoning_effort(config_api=fallback_cfg, override_value=None) == "high"


def test_resolve_reasoning_effort_accepts_xhigh() -> None:
    cfg = SimpleNamespace(reasoning_effort="xhigh", thinking_intensity="medium")
    assert LLMService._resolve_reasoning_effort(config_api=cfg, override_value=None) == "xhigh"
    assert LLMService._resolve_reasoning_effort(config_api=cfg, override_value="xhigh") == "xhigh"
