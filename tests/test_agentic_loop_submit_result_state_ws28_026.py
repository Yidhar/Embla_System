from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, Dict, List

import apiserver.agentic_tool_loop as tool_loop
import apiserver.llm_service as llm_service_module


def _policy(max_rounds: int) -> tool_loop.AgenticLoopPolicy:
    return tool_loop.AgenticLoopPolicy(
        max_rounds=max_rounds,
        enable_summary_round=False,
        max_consecutive_tool_failures=5,
        max_consecutive_validation_failures=2,
        max_consecutive_no_tool_rounds=2,
        inject_no_tool_feedback=True,
        tool_result_preview_chars=500,
        emit_workflow_stage_events=True,
        max_parallel_tool_calls=4,
        retry_failed_tool_calls=False,
        max_tool_retries=0,
        retry_backoff_seconds=0.0,
        gc_budget_guard_enabled=False,
        gc_budget_repeat_threshold=3,
        gc_budget_window_size=6,
    )


def test_agentic_loop_no_tool_does_not_end_without_submit_result(monkeypatch):
    class _NoToolLLM:
        async def stream_chat_with_context(self, *_args, **_kwargs):
            yield tool_loop._format_sse_event("content", {"text": "继续分析"})

    fake_cfg = SimpleNamespace(api=SimpleNamespace(temperature=0.0))
    monkeypatch.setattr(tool_loop, "get_config", lambda: fake_cfg)
    monkeypatch.setattr(tool_loop, "_resolve_agentic_loop_policy", lambda _max_rounds: _policy(3))
    monkeypatch.setattr(tool_loop, "_build_agentic_loop_watchdog", lambda: None)
    monkeypatch.setattr(llm_service_module, "get_llm_service", lambda: _NoToolLLM())
    monkeypatch.setattr(tool_loop, "archive_tool_results_for_session", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(tool_loop, "build_reinjection_context", lambda **_kwargs: "")
    monkeypatch.setattr(
        tool_loop,
        "_maybe_execute_gc_reader_followup",
        lambda *_args, **_kwargs: asyncio.sleep(0, result=[]),
    )

    async def _collect_events() -> List[Dict[str, Any]]:
        collected: List[Dict[str, Any]] = []
        async for event in tool_loop.run_agentic_loop(
            [{"role": "user", "content": "继续推进修复"}],
            session_id="sess-submit-required-1",
            max_rounds=3,
        ):
            if isinstance(event, dict):
                collected.append(event)
        return collected

    events = asyncio.run(_collect_events())
    assert events

    verify_success_reasons = [
        str(event.get("reason", ""))
        for event in events
        if event.get("type") == "tool_stage"
        and event.get("phase") == "verify"
        and event.get("status") == "success"
    ]
    assert "await_submit_result_tool" in verify_success_reasons

    verify_error_reasons = [
        str(event.get("reason", ""))
        for event in events
        if event.get("type") == "tool_stage"
        and event.get("phase") == "verify"
        and event.get("status") == "error"
    ]
    assert verify_error_reasons
    assert verify_error_reasons[-1] == "completion_not_submitted"
    assert "no_tool_calls" not in verify_error_reasons

    round_end_events = [event for event in events if event.get("type") == "round_end"]
    assert round_end_events
    assert round_end_events[-1].get("has_more") is False


def test_agentic_loop_stops_when_submit_result_marks_completed(monkeypatch):
    class _SubmitCompletionLLM:
        async def stream_chat_with_context(self, *_args, **_kwargs):
            payload = [
                {
                    "id": "submit-result-1",
                    "name": "SubmitResult_Tool",
                    "arguments": {
                        "task_completed": True,
                        "final_answer": "已完成修复并通过验证",
                        "deliverables": ["patch", "tests"],
                    },
                }
            ]
            yield tool_loop._format_sse_event("tool_calls", {"text": payload})

    execute_call_counter = {"count": 0}

    async def _fake_execute_tool_calls(*_args, **_kwargs):
        execute_call_counter["count"] += 1
        return []

    fake_cfg = SimpleNamespace(api=SimpleNamespace(temperature=0.0))
    monkeypatch.setattr(tool_loop, "get_config", lambda: fake_cfg)
    monkeypatch.setattr(tool_loop, "_resolve_agentic_loop_policy", lambda _max_rounds: _policy(4))
    monkeypatch.setattr(tool_loop, "_build_agentic_loop_watchdog", lambda: None)
    monkeypatch.setattr(llm_service_module, "get_llm_service", lambda: _SubmitCompletionLLM())
    monkeypatch.setattr(tool_loop, "execute_tool_calls", _fake_execute_tool_calls)
    monkeypatch.setattr(tool_loop, "archive_tool_results_for_session", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(tool_loop, "build_reinjection_context", lambda **_kwargs: "")
    monkeypatch.setattr(
        tool_loop,
        "_maybe_execute_gc_reader_followup",
        lambda *_args, **_kwargs: asyncio.sleep(0, result=[]),
    )

    async def _collect_events() -> List[Dict[str, Any]]:
        collected: List[Dict[str, Any]] = []
        async for event in tool_loop.run_agentic_loop(
            [{"role": "user", "content": "修复后提交结果"}],
            session_id="sess-submit-required-2",
            max_rounds=4,
        ):
            if isinstance(event, dict):
                collected.append(event)
        return collected

    events = asyncio.run(_collect_events())
    assert events
    assert execute_call_counter["count"] == 0

    verify_success = [
        event
        for event in events
        if event.get("type") == "tool_stage"
        and event.get("phase") == "verify"
        and event.get("status") == "success"
        and event.get("reason") == "submitted_completion"
    ]
    assert verify_success

    tool_results_events = [event for event in events if event.get("type") == "tool_results"]
    assert tool_results_events
    latest_results = tool_results_events[-1].get("results") or []
    assert any(str(row.get("tool_name", "")) == "SubmitResult_Tool" for row in latest_results)

    round_end_events = [event for event in events if event.get("type") == "round_end"]
    assert round_end_events
    assert round_end_events[-1].get("has_more") is False


def test_agentic_loop_honors_no_tool_threshold_before_max_rounds(monkeypatch):
    class _NoToolLLM:
        async def stream_chat_with_context(self, *_args, **_kwargs):
            yield tool_loop._format_sse_event("content", {"text": "继续分析，不调用工具"})

    fake_cfg = SimpleNamespace(api=SimpleNamespace(temperature=0.0))
    monkeypatch.setattr(tool_loop, "get_config", lambda: fake_cfg)
    monkeypatch.setattr(tool_loop, "_resolve_agentic_loop_policy", lambda _max_rounds: _policy(8))
    monkeypatch.setattr(tool_loop, "_build_agentic_loop_watchdog", lambda: None)
    monkeypatch.setattr(llm_service_module, "get_llm_service", lambda: _NoToolLLM())
    monkeypatch.setattr(tool_loop, "archive_tool_results_for_session", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(tool_loop, "build_reinjection_context", lambda **_kwargs: "")
    monkeypatch.setattr(
        tool_loop,
        "_maybe_execute_gc_reader_followup",
        lambda *_args, **_kwargs: asyncio.sleep(0, result=[]),
    )

    async def _collect_events() -> List[Dict[str, Any]]:
        collected: List[Dict[str, Any]] = []
        async for event in tool_loop.run_agentic_loop(
            [{"role": "user", "content": "推进但始终无工具调用"}],
            session_id="sess-submit-threshold-1",
            max_rounds=8,
        ):
            if isinstance(event, dict):
                collected.append(event)
        return collected

    events = asyncio.run(_collect_events())
    verify_errors = [
        event
        for event in events
        if event.get("type") == "tool_stage"
        and event.get("phase") == "verify"
        and event.get("status") == "error"
    ]
    assert verify_errors
    assert verify_errors[-1].get("reason") == "completion_not_submitted"

    round_end_events = [event for event in events if event.get("type") == "round_end"]
    assert len(round_end_events) == 2
    assert round_end_events[-1].get("has_more") is False
