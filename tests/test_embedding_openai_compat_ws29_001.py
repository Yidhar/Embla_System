from __future__ import annotations

import sys
import types
from types import SimpleNamespace

from summer_memory import embedding_openai_compat as emb


def _build_fake_config(
    *,
    emb_api_base: str = "",
    emb_api_key: str = "",
    emb_model: str = "text-embedding-v4",
    emb_dimensions: int = 1024,
    emb_encoding: str = "float",
    emb_max_tokens: int = 8192,
    emb_timeout: int = 30,
    api_base: str = "https://example.invalid/v1",
    api_key: str = "sk-main",
):
    return SimpleNamespace(
        embedding=SimpleNamespace(
            api_base=emb_api_base,
            api_key=emb_api_key,
            model=emb_model,
            dimensions=emb_dimensions,
            encoding_format=emb_encoding,
            max_input_tokens=emb_max_tokens,
            request_timeout_seconds=emb_timeout,
        ),
        api=SimpleNamespace(
            base_url=api_base,
            api_key=api_key,
        ),
    )


def test_resolve_embedding_runtime_config_fallback_to_api(monkeypatch):
    monkeypatch.setattr(
        emb,
        "get_config",
        lambda: _build_fake_config(emb_api_base="", emb_api_key="", emb_model=""),
    )

    runtime = emb.resolve_embedding_runtime_config()
    assert runtime.api_base == "https://example.invalid/v1"
    assert runtime.api_key == "sk-main"
    assert runtime.model == "text-embedding-v4"
    assert runtime.dimensions == 1024
    assert runtime.encoding_format == "float"
    assert runtime.max_input_tokens == 8192
    assert runtime.request_timeout_seconds == 30
    assert runtime.ready is True


def test_embed_texts_openai_compat_success_and_truncation(monkeypatch):
    captured: dict = {}

    class FakeEmbeddings:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                data=[
                    SimpleNamespace(index=0, embedding=[0.1, 0.2, 0.3]),
                    SimpleNamespace(index=1, embedding=[0.4, 0.5, 0.6]),
                ],
                usage=SimpleNamespace(prompt_tokens=12, total_tokens=12),
                model="text-embedding-v4",
            )

    class FakeOpenAI:
        def __init__(self, *, api_key: str, base_url: str, timeout: int):
            captured["client"] = {
                "api_key": api_key,
                "base_url": base_url,
                "timeout": timeout,
            }
            self.embeddings = FakeEmbeddings()

    monkeypatch.setattr(
        emb,
        "get_config",
        lambda: _build_fake_config(
            emb_api_base="https://embed.local/v1",
            emb_api_key="sk-embed",
            emb_max_tokens=3,
        ),
    )
    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=FakeOpenAI))

    long_text = "abcdefghij" * 20
    vectors, meta = emb.embed_texts_openai_compat([long_text, "短文本"])

    assert vectors == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    assert meta["ok"] is True
    assert meta["count"] == 2
    assert meta["usage"]["total_tokens"] == 12
    assert captured["client"]["base_url"] == "https://embed.local/v1"
    assert captured["client"]["api_key"] == "sk-embed"
    assert captured["dimensions"] == 1024
    assert captured["encoding_format"] == "float"
    assert len(captured["input"][0]) < len(long_text)


def test_embed_texts_openai_compat_returns_incomplete_when_missing_key(monkeypatch):
    monkeypatch.setattr(
        emb,
        "get_config",
        lambda: _build_fake_config(
            emb_api_base="https://embed.local/v1",
            emb_api_key="",
            api_key="",
        ),
    )
    vectors, meta = emb.embed_texts_openai_compat(["hello"])
    assert vectors == [None]
    assert meta["ok"] is False
    assert meta["error"] == "embedding_config_incomplete"
