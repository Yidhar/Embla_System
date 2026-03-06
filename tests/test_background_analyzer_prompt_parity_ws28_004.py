from __future__ import annotations

from system.background_analyzer import (
    ConversationAnalyzer,
    _PROMPT_ROUTE_ENGINE,
    _build_router_request_for_messages,
    _derive_prompt_route_metadata,
)


def test_background_analyzer_prompt_route_metadata_parity_with_router_engine() -> None:
    messages = [
        {"role": "user", "content": "请修复 API 返回字段并补充测试用例"},
    ]
    request = _build_router_request_for_messages(messages)
    decision = _PROMPT_ROUTE_ENGINE.route(request)
    route_meta = _derive_prompt_route_metadata(messages)

    assert route_meta["prompt_profile"] == decision.prompt_profile
    assert route_meta["injection_mode"] == decision.injection_mode
    assert route_meta["delegation_intent"] == decision.delegation_intent
    assert route_meta["selected_role"] == decision.selected_role


def test_background_analyzer_prompt_route_metadata_for_read_only_route() -> None:
    messages = [
        {"role": "user", "content": "帮我分析这份运维文档的关键结论，不要修改任何代码"},
    ]
    route_meta = _derive_prompt_route_metadata(messages)

    assert route_meta["delegation_intent"] == "read_only_exploration"
    assert route_meta["injection_mode"] == "minimal"
    assert route_meta["prompt_profile"] in {"shell_readonly_research", "shell_readonly_general"}


def test_background_analyzer_build_prompt_includes_router_hint(monkeypatch) -> None:
    def fake_get_prompt(name: str, **kwargs):
        if name == "conversation_analyzer_prompt":
            return (
                "BASE"
                f"|profile={kwargs.get('prompt_profile')}"
                f"|mode={kwargs.get('injection_mode')}"
                f"|intent={kwargs.get('delegation_intent')}"
                f"|role={kwargs.get('selected_role')}"
            )
        if name == "tool_dispatch_prompt":
            return (
                "DISPATCH"
                f"|profile={kwargs.get('prompt_profile')}"
                f"|mode={kwargs.get('injection_mode')}"
            )
        raise AssertionError(f"unexpected prompt name: {name}")

    monkeypatch.setattr("system.background_analyzer.get_prompt", fake_get_prompt)

    analyzer = ConversationAnalyzer.__new__(ConversationAnalyzer)
    analyzer._get_mcp_tools_description = lambda: "MCP_TOOLS"
    messages = [{"role": "user", "content": "请修复 mcp 接口并补回归"}]

    prompt = ConversationAnalyzer._build_prompt(analyzer, messages)
    route_meta = _derive_prompt_route_metadata(messages)

    assert f"prompt_profile={route_meta['prompt_profile']}" in prompt
    assert f"injection_mode={route_meta['injection_mode']}" in prompt
    assert f"delegation_intent={route_meta['delegation_intent']}" in prompt
    assert f"selected_role={route_meta['selected_role']}" in prompt
