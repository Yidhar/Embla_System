from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, Dict, List

import agents.tool_loop as tool_loop
import apiserver.llm_service as llm_service_module
from system.gc_budget_guard import GCBudgetGuard, GCBudgetGuardConfig


def _gc_error_result(*, artifact_ref: str, query: str = "$..trace_id") -> Dict[str, Any]:
    return {
        "status": "error",
        "service_name": "native",
        "tool_name": "artifact_reader",
        "result": f"执行失败: Artifact not found: {artifact_ref}",
        "tool_call": {
            "agentType": "native",
            "tool_name": "artifact_reader",
            "forensic_artifact_ref": artifact_ref,
            "mode": "jsonpath",
            "query": query,
        },
    }


def _gc_success_result(*, artifact_ref: str = "artifact_ok") -> Dict[str, Any]:
    return {
        "status": "success",
        "service_name": "native",
        "tool_name": "artifact_reader",
        "result": "[artifact_id] artifact_ok\n[content]\nok",
        "tool_call": {
            "agentType": "native",
            "tool_name": "artifact_reader",
            "forensic_artifact_ref": artifact_ref,
            "mode": "preview",
        },
    }


def test_gc_budget_guard_hits_on_repeated_failure():
    guard = GCBudgetGuard(GCBudgetGuardConfig(repeat_threshold=2, window_size=4))
    first = _gc_error_result(artifact_ref="artifact_missing")
    second = _gc_error_result(artifact_ref="artifact_missing")

    signal1 = guard.observe_result(first)
    signal2 = guard.observe_result(second)

    assert signal1 is not None
    assert signal1.guard_hit is False
    assert signal2 is not None
    assert signal2.guard_hit is True
    assert signal2.stop_reason == "gc_budget_guard_hit"
    assert signal2.repeat_count == 2
    assert second.get("guard_hit") is True
    assert second.get("guard_stop_reason") == "gc_budget_guard_hit"
    assert guard.snapshot()["gc_guard_hits"] == 1


def test_gc_budget_guard_success_resets_repeat_streak():
    guard = GCBudgetGuard(GCBudgetGuardConfig(repeat_threshold=2, window_size=4))

    signal1 = guard.observe_result(_gc_error_result(artifact_ref="artifact_missing"))
    assert signal1 is not None and signal1.guard_hit is False

    success_signal = guard.observe_result(_gc_success_result())
    assert success_signal is None

    signal2 = guard.observe_result(_gc_error_result(artifact_ref="artifact_missing"))
    assert signal2 is not None
    assert signal2.guard_hit is False
    assert signal2.repeat_count == 1


def test_gc_budget_guard_ignores_bridge_suggestion_success():
    guard = GCBudgetGuard(GCBudgetGuardConfig(repeat_threshold=2, window_size=4))

    round1 = [
        _gc_error_result(artifact_ref="artifact_missing"),
        {
            "status": "success",
            "service_name": "gc_reader_bridge",
            "tool_name": "artifact_reader_suggestion",
            "result": "[gc_reader_bridge] 自动证据回读已降级为建议。",
            "tool_call": {"tool_name": "artifact_reader"},
        },
    ]
    round2 = [
        _gc_error_result(artifact_ref="artifact_missing"),
    ]

    signal1 = guard.observe_round(round1)
    signal2 = guard.observe_round(round2)

    assert signal1 is None
    assert signal2 is not None
    assert signal2.guard_hit is True
    assert signal2.repeat_count == 2


def test_agentic_loop_emits_gc_guard_signal_and_stops(monkeypatch):
    class _FakeLLMService:
        async def stream_chat_with_context(self, *_args, **_kwargs):
            payload = [
                {
                    "id": "call-gc-1",
                    "name": "native_call",
                    "arguments": {
                        "tool_name": "artifact_reader",
                        "forensic_artifact_ref": "artifact_missing",
                        "mode": "jsonpath",
                        "query": "$..trace_id",
                    },
                },
                {
                    "id": "call-ok-1",
                    "name": "native_call",
                    "arguments": {"tool_name": "read_file", "path": "README.md"},
                },
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
            gc_budget_guard_enabled=True,
            gc_budget_repeat_threshold=2,
            gc_budget_window_size=4,
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
        _ = (session_id, max_parallel_calls, retry_failed, max_retries, retry_backoff_seconds)
        outputs: List[Dict[str, Any]] = []
        for call in tool_calls:
            tool_name = str(call.get("tool_name") or "")
            if tool_name == "artifact_reader":
                outputs.append(_gc_error_result(artifact_ref="artifact_missing"))
            else:
                outputs.append(
                    {
                        "status": "success",
                        "service_name": "native",
                        "tool_name": tool_name,
                        "result": "ok",
                        "tool_call": call,
                    }
                )
        return outputs

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
            [{"role": "user", "content": "请读取日志并继续分析"}],
            session_id="sess-gc-guard",
            max_rounds=8,
        ):
            if isinstance(event, dict):
                collected.append(event)
        return collected

    events = asyncio.run(_collect_events())
    assert events

    guard_events = [event for event in events if event.get("guard_type") == "gc_budget_guard"]
    assert guard_events
    assert guard_events[-1].get("guard_hit") is True
    assert guard_events[-1].get("stop_reason") == "gc_budget_guard_hit"
    assert int(guard_events[-1].get("repeat_count", 0)) >= 2

    verify_errors = [
        event
        for event in events
        if event.get("type") == "tool_stage"
        and event.get("phase") == "verify"
        and event.get("status") == "error"
    ]
    assert verify_errors
    assert verify_errors[-1].get("reason") == "gc_budget_guard_hit"

    round_end_events = [event for event in events if event.get("type") == "round_end"]
    assert round_end_events
    assert round_end_events[-1].get("has_more") is False
