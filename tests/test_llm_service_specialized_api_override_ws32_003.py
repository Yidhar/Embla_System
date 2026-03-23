from __future__ import annotations

from types import SimpleNamespace

from apiserver.llm_service import LLMService


def test_llm_service_resolves_specialized_api_override(monkeypatch) -> None:
    fake_config = SimpleNamespace(
        api=SimpleNamespace(
            specialized=SimpleNamespace(
                context_compression=SimpleNamespace(
                    api_key="compression-key",
                    base_url="https://compression.example/v1",
                    model="compression-model",
                    provider="openai_compatible",
                    protocol="auto",
                    reasoning_effort="medium",
                )
            )
        )
    )
    monkeypatch.setattr("apiserver.llm_service.get_config", lambda: fake_config)
    monkeypatch.setattr("system.config.get_config", lambda: fake_config)

    override = LLMService.get_specialized_api_override("context_compression")

    assert override == {
        "api_key": "compression-key",
        "api_base": "https://compression.example/v1",
        "model": "compression-model",
        "provider": "openai_compatible",
        "protocol": "auto",
        "reasoning_effort": "medium",
    }


def test_llm_service_specialized_api_override_falls_back_by_omission(monkeypatch) -> None:
    fake_config = SimpleNamespace(
        api=SimpleNamespace(
            specialized=SimpleNamespace(
                context_compression=SimpleNamespace(
                    api_key="",
                    base_url="",
                    model="",
                    provider="",
                    protocol="",
                    reasoning_effort="",
                    thinking_intensity="",
                )
            )
        )
    )
    monkeypatch.setattr("apiserver.llm_service.get_config", lambda: fake_config)
    monkeypatch.setattr("system.config.get_config", lambda: fake_config)

    assert LLMService.get_specialized_api_override("context_compression") is None
