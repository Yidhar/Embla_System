import asyncio
from types import SimpleNamespace

import summer_memory.quintuple_extractor as extractor_mod
from summer_memory.quintuple_extractor import (
    _build_json_fallback_prompt,
    _build_structured_messages,
    _extract_quintuples_local,
    _resolve_completion_timeout_seconds,
    _resolve_extraction_model,
    _resolve_extraction_temperature,
    extract_quintuples_async,
    get_extraction_runtime_status,
)


def test_quintuple_structured_messages_use_canonical_prompt_assets() -> None:
    messages = _build_structured_messages("小明在公园里踢足球。")

    assert messages[0]["role"] == "system"
    assert "专业的中文文本信息抽取专家" in messages[0]["content"]
    assert "五元组格式为" in messages[0]["content"]
    assert messages[1]["role"] == "user"
    assert "小明在公园里踢足球。" in messages[1]["content"]
    assert "{text}" not in messages[1]["content"]


def test_quintuple_json_fallback_prompt_uses_canonical_prompt_asset() -> None:
    prompt = _build_json_fallback_prompt("如果我是鸟，我会飞到月球。")

    assert "JSON 数组格式返回" in prompt
    assert "如果我是鸟，我会飞到月球。" in prompt
    assert "除了 JSON 数据" in prompt
    assert "{text}" not in prompt


def test_quintuple_local_fallback_extracts_basic_shell_facts() -> None:
    rows = _extract_quintuples_local(
        "用户: 请读取 README.md 并检查五元组提取是否稳定\n"
        "Embla: 我先查询系统状态。\n"
        "[tool_calls] memory_read, get_system_status\n"
        "Embla: 记忆文件会写到 memory/domain/api_shell_flow_smoke_20260316_c.md\n"
    )

    assert ("用户", "person", "关注", "五元组提取", "topic") in rows
    assert ("Embla", "assistant", "调用", "memory_read", "tool") in rows
    assert ("Embla", "assistant", "调用", "get_system_status", "tool") in rows
    assert ("会话", "session", "引用", "README.md", "artifact") in rows
    assert ("会话", "session", "引用", "memory/domain/api_shell_flow_smoke_20260316_c.md", "artifact") in rows


def test_quintuple_extractor_prefers_grag_specific_generation_settings(monkeypatch) -> None:
    monkeypatch.setattr(
        extractor_mod,
        "config",
        SimpleNamespace(
            api=SimpleNamespace(model="global-model", max_tokens=8192),
            grag=SimpleNamespace(
                extraction_model="memory-fast-model",
                extraction_temperature=1.4,
                base_timeout=55,
            ),
        ),
    )

    assert _resolve_extraction_model() == "memory-fast-model"
    assert _resolve_extraction_temperature() == 1.4
    assert _resolve_completion_timeout_seconds() == 55


def test_quintuple_extractor_prefers_specialized_api_target(monkeypatch) -> None:
    fake_config = SimpleNamespace(
        api=SimpleNamespace(
            api_key="global-key",
            base_url="https://global.example/v1",
            model="global-model",
            specialized=SimpleNamespace(
                quintuple_extraction=SimpleNamespace(
                    api_key="extract-key",
                    base_url="https://extract.example/v1",
                    model="extract-model",
                )
            ),
        ),
        grag=SimpleNamespace(
            extraction_model="legacy-extract-model",
            extraction_temperature=1.0,
            extraction_timeout=20,
            extraction_retries=0,
            base_timeout=40,
        ),
    )
    monkeypatch.setattr(extractor_mod, "config", fake_config)
    import system.config as _sys_config_mod
    monkeypatch.setattr(_sys_config_mod, "get_config", lambda: fake_config)

    assert extractor_mod._resolve_extraction_api_key() == "extract-key"
    assert extractor_mod._resolve_extraction_base_url() == "https://extract.example/v1"
    assert _resolve_extraction_model() == "extract-model"


def test_quintuple_async_entry_uses_structured_path(monkeypatch) -> None:
    async def _structured(text: str, *, timeout_seconds=None, max_retries=None):
        del text, timeout_seconds, max_retries
        return [("用户", "person", "关注", "五元组提取", "topic")]

    async def _fallback(text: str, *, timeout_seconds=None, max_retries=None):
        raise AssertionError("fallback should not be called")

    monkeypatch.setattr(extractor_mod, "_extract_quintuples_async_structured", _structured)
    monkeypatch.setattr(extractor_mod, "_extract_quintuples_async_fallback", _fallback)

    result = asyncio.run(extract_quintuples_async("用户关注五元组提取"))

    assert result == [("用户", "person", "关注", "五元组提取", "topic")]


def test_quintuple_async_timeout_records_explicit_upstream_warning(monkeypatch) -> None:
    class APITimeoutError(Exception):
        pass

    class _Completions:
        async def parse(self, **kwargs):  # type: ignore[no-untyped-def]
            del kwargs
            raise APITimeoutError()

    fake_client = SimpleNamespace(beta=SimpleNamespace(chat=SimpleNamespace(completions=_Completions())))

    monkeypatch.setattr(
        extractor_mod,
        "_LAST_EXTRACTION_RUNTIME_STATUS",
        {"last_success": {}, "last_upstream_timeout": {}},
    )
    monkeypatch.setattr(
        extractor_mod,
        "config",
        SimpleNamespace(
            api=SimpleNamespace(model="global-model", max_tokens=8192, api_key="sk-test", base_url="https://example.com/v1"),
            grag=SimpleNamespace(
                extraction_timeout=3,
                extraction_retries=0,
                extraction_model="memory-fast-model",
                extraction_temperature=1.0,
                base_timeout=8,
            ),
        ),
    )
    monkeypatch.setattr(extractor_mod, "_build_async_client", lambda: fake_client)

    async def _fallback(text: str, *, timeout_seconds=None, max_retries=None):
        del timeout_seconds, max_retries
        return extractor_mod._extract_quintuples_local(text)

    monkeypatch.setattr(extractor_mod, "_extract_quintuples_async_fallback", _fallback)

    result = asyncio.run(extract_quintuples_async("用户: 请读取 README.md 并关注五元组提取"))
    runtime_status = get_extraction_runtime_status()

    assert ("用户", "person", "关注", "五元组提取", "topic") in result
    timeout_info = runtime_status["last_upstream_timeout"]
    assert timeout_info["reason_code"] == "upstream_api_timeout"
    assert timeout_info["model"] == "memory-fast-model"
    assert timeout_info["endpoint"] == "https://example.com/v1"
    assert "上游模型 API 超时" in timeout_info["message"]
