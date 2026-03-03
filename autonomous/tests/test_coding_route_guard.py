from agents.tool_loop import _apply_coding_route_guard
from system.coding_intent import requires_core_execution_for_messages


def test_requires_core_execution_for_direct_coding_request():
    messages = [{"role": "user", "content": "Please implement a new API endpoint in apiserver/api_server.py"}]
    assert requires_core_execution_for_messages(messages) is True


def test_requires_core_execution_for_followup_with_recent_coding_context():
    messages = [
        {"role": "user", "content": "Refactor apiserver/agentic_tool_loop.py and add tests."},
        {"role": "assistant", "content": "I will call mcp_call and native_call tools for this change."},
        {"role": "user", "content": "continue"},
    ]
    assert requires_core_execution_for_messages(messages) is True


def test_requires_core_execution_is_false_for_non_coding_request():
    messages = [{"role": "user", "content": "What is the weather in Tokyo today?"}]
    assert requires_core_execution_for_messages(messages) is False


def test_apply_coding_route_guard_is_noop_after_retirement():
    actionable_calls = [
        {"agentType": "native", "tool_name": "read_file", "path": "README.md"},
        {"agentType": "native", "tool_name": "write_file", "path": "demo.txt", "content": "x"},
    ]

    guarded_calls, blocked_mutating = _apply_coding_route_guard(
        actionable_calls,
        latest_user_request="Implement the requested change.",
    )

    assert guarded_calls == actionable_calls
    assert blocked_mutating == 0

