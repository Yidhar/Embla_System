from apiserver.agentic_tool_loop import _apply_codex_first_guard
from system.coding_intent import requires_codex_for_messages


def test_requires_codex_for_direct_coding_request():
    messages = [{"role": "user", "content": "Please implement a new API endpoint in apiserver/api_server.py"}]
    assert requires_codex_for_messages(messages) is True


def test_requires_codex_for_followup_with_recent_coding_context():
    messages = [
        {"role": "user", "content": "Refactor apiserver/agentic_tool_loop.py and add tests."},
        {"role": "assistant", "content": "I will use codex-cli ask-codex to execute this change."},
        {"role": "user", "content": "continue"},
    ]
    assert requires_codex_for_messages(messages) is True


def test_requires_codex_is_false_for_non_coding_request():
    messages = [{"role": "user", "content": "What is the weather in Tokyo today?"}]
    assert requires_codex_for_messages(messages) is False


def test_apply_codex_first_guard_injects_forced_codex_call():
    actionable_calls = [
        {"agentType": "native", "tool_name": "read_file", "path": "README.md"},
        {"agentType": "native", "tool_name": "write_file", "path": "demo.txt", "content": "x"},
    ]

    guarded_calls, codex_engaged, blocked_mutating = _apply_codex_first_guard(
        actionable_calls,
        requires_codex=True,
        codex_engaged=False,
        latest_user_request="Implement the requested change.",
        round_num=3,
    )

    assert codex_engaged is True
    assert blocked_mutating == 1
    assert guarded_calls[0]["agentType"] == "mcp"
    assert guarded_calls[0]["service_name"] == "codex-cli"
    assert guarded_calls[0]["tool_name"] == "ask-codex"
    assert any(call.get("tool_name") == "read_file" for call in guarded_calls[1:])
    assert all(call.get("tool_name") != "write_file" for call in guarded_calls[1:])


def test_apply_codex_first_guard_keeps_existing_codex_call():
    actionable_calls = [
        {
            "agentType": "mcp",
            "service_name": "codex-cli",
            "tool_name": "ask-codex",
            "message": "fix bug",
        }
    ]

    guarded_calls, codex_engaged, blocked_mutating = _apply_codex_first_guard(
        actionable_calls,
        requires_codex=True,
        codex_engaged=False,
        latest_user_request="Fix bug",
        round_num=1,
    )

    assert guarded_calls == actionable_calls
    assert codex_engaged is True
    assert blocked_mutating == 0
