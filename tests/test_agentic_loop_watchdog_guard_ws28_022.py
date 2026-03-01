from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, Dict, List

import apiserver.agentic_tool_loop as tool_loop
import apiserver.llm_service as llm_service_module


def test_agentic_loop_watchdog_guard_stops_on_consecutive_tool_errors(monkeypatch):
    class _FakeLLMService:
        async def stream_chat_with_context(self, *_args, **_kwargs):
            payload = [
                {
                    "id": "call-watchdog-1",
                    "name": "native_call",
                    "arguments": {
                        "tool_name": "run_cmd",
                        "command": "echo watchdog-loop",
                    },
                }
            ]
            yield tool_loop._format_sse_event("tool_calls", {"text": payload})

    fake_cfg = SimpleNamespace(
        handoff=SimpleNamespace(max_loop_stream=12),
        agentic_loop=SimpleNamespace(
            max_rounds_stream=12,
            enable_summary_round=False,
            max_consecutive_tool_failures=20,
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
            watchdog_guard_enabled=True,
            watchdog_warn_only=False,
            watchdog_sample_per_round=False,
            watchdog_consecutive_error_limit=2,
            watchdog_tool_call_limit_per_minute=1000,
            watchdog_task_cost_limit=99.0,
            watchdog_daily_cost_limit=999.0,
            watchdog_loop_window_seconds=60,
        ),
        api=SimpleNamespace(temperature=0.0),
    )

    async def _fake_execute_tool_calls(
        tool_calls: List[Dict[str, Any]],
        session_id: str,
        *,
        max_parallel_calls: int = 8,
        retry_failed: bool = True,
        max_retries: int = 1,
        retry_backoff_seconds: float = 0.8,
    ) -> List[Dict[str, Any]]:
        _ = (tool_calls, session_id, max_parallel_calls, retry_failed, max_retries, retry_backoff_seconds)
        return [
            {
                "status": "error",
                "service_name": "native",
                "tool_name": "run_cmd",
                "result": "simulated failure",
            }
        ]

    monkeypatch.setattr(tool_loop, "get_config", lambda: fake_cfg)
    monkeypatch.setattr(llm_service_module, "get_llm_service", lambda: _FakeLLMService())
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
            [{"role": "user", "content": "请继续排查并执行命令"}],
            session_id="sess-watchdog-loop",
            max_rounds=8,
        ):
            if isinstance(event, dict):
                collected.append(event)
        return collected

    events = asyncio.run(_collect_events())
    assert events

    guard_events = [event for event in events if event.get("guard_type") == "watchdog_loop_guard"]
    assert guard_events
    assert any(str(item.get("source")) == "loop_cost_guard" for item in guard_events)
    assert any(str(item.get("reason")) == "consecutive_error_limit_exceeded" for item in guard_events)

    verify_errors = [
        event
        for event in events
        if event.get("type") == "tool_stage"
        and event.get("phase") == "verify"
        and event.get("status") == "error"
    ]
    assert verify_errors
    assert str(verify_errors[-1].get("reason", "")).startswith("watchdog_consecutive_error_limit_exceeded")

    round_end_events = [event for event in events if event.get("type") == "round_end"]
    assert round_end_events
    assert round_end_events[-1].get("has_more") is False
