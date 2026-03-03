from __future__ import annotations

import asyncio

import agents.tool_loop as tool_loop
from system.gc_reader_bridge import build_gc_reader_followup_plan


def _build_tagged_result(
    *,
    status: str,
    ref: str,
    fetch_hints: str,
    truncated: bool = True,
) -> dict:
    return {
        "service_name": "native",
        "tool_name": "run_cmd",
        "status": status,
        "result": (
            f"[truncated] {str(truncated).lower()}\n"
            f"[forensic_artifact_ref] {ref}\n"
            f"[raw_result_ref] {ref}\n"
            f"[fetch_hints] {fetch_hints}\n"
            "[display_preview]\n"
            "preview text"
        ),
    }


def test_gc_reader_followup_plan_builds_line_range_call_from_hints():
    results = [
        _build_tagged_result(
            status="error",
            ref="artifact_cmd_001",
            fetch_hints="jsonpath:$..error_code, line_range:120-180",
            truncated=True,
        )
    ]

    plan = build_gc_reader_followup_plan(results, round_num=2)

    assert plan.call is not None
    call = plan.call
    assert call["tool_name"] == "artifact_reader"
    assert call["forensic_artifact_ref"] == "artifact_cmd_001"
    assert call["mode"] == "line_range"
    assert call["start_line"] == 120
    assert call["end_line"] == 180
    assert call["_gc_reader_bridge"] is True
    assert call["_tool_call_id"] == "gc_reader_bridge_r2_1"


def test_gc_reader_followup_plan_limits_to_one_call_and_prioritizes_error_result():
    results = [
        _build_tagged_result(
            status="success",
            ref="artifact_ok",
            fetch_hints="line_range:1-40",
            truncated=True,
        ),
        _build_tagged_result(
            status="error",
            ref="artifact_err",
            fetch_hints="grep:RootCause",
            truncated=True,
        ),
    ]

    plan = build_gc_reader_followup_plan(results, round_num=3)

    assert plan.call is not None
    assert plan.call["forensic_artifact_ref"] == "artifact_err"
    assert plan.call["tool_name"] == "artifact_reader"


def test_gc_reader_followup_plan_degrades_to_suggestion_when_preview_is_sufficient():
    results = [
        {
            "service_name": "native",
            "tool_name": "run_cmd",
            "status": "success",
            "forensic_artifact_ref": "artifact_small_preview",
            "fetch_hints": ["grep:ERROR"],
            "result": "small preview available",
        }
    ]

    plan = build_gc_reader_followup_plan(results, round_num=1)

    assert plan.call is None
    assert plan.reason == "preview_sufficient"
    assert "artifact_reader(" in plan.suggestion


def test_gc_reader_followup_plan_triggers_for_error_even_without_truncated_marker():
    results = [
        {
            "service_name": "native",
            "tool_name": "run_cmd",
            "status": "error",
            "forensic_artifact_ref": "artifact_error_focus",
            "fetch_hints": ["grep:Traceback"],
            "result": "command failed",
        }
    ]

    plan = build_gc_reader_followup_plan(results, round_num=5)

    assert plan.call is not None
    assert plan.call["tool_name"] == "artifact_reader"
    assert plan.call["forensic_artifact_ref"] == "artifact_error_focus"
    assert plan.call["mode"] == "grep"


def test_maybe_execute_gc_reader_followup_executes_at_most_one_call(monkeypatch):
    captured = []

    async def fake_execute_tool_calls(tool_calls, session_id, **kwargs):
        captured.append((tool_calls, session_id, kwargs))
        return [
            {
                "tool_call": tool_calls[0],
                "result": "[artifact_id] artifact_cmd_001\n[content]\nline",
                "status": "success",
                "service_name": "native",
                "tool_name": "artifact_reader",
            }
        ]

    monkeypatch.setattr(tool_loop, "execute_tool_calls", fake_execute_tool_calls)
    primary_results = [
        _build_tagged_result(
            status="error",
            ref="artifact_cmd_001",
            fetch_hints="line_range:88-132",
            truncated=True,
        )
    ]

    followups = asyncio.run(tool_loop._maybe_execute_gc_reader_followup(primary_results, "sess_gc_1", round_num=6))

    assert len(captured) == 1
    tool_calls, session_id, kwargs = captured[0]
    assert session_id == "sess_gc_1"
    assert len(tool_calls) == 1
    assert tool_calls[0]["tool_name"] == "artifact_reader"
    assert tool_calls[0]["_gc_reader_bridge"] is True
    assert kwargs["max_parallel_calls"] == 1
    assert kwargs["retry_failed"] is False
    assert len(followups) == 1
    assert followups[0]["tool_name"] == "artifact_reader"


def test_maybe_execute_gc_reader_followup_appends_suggestion_when_readback_fails(monkeypatch):
    async def fake_execute_tool_calls(tool_calls, session_id, **kwargs):
        return [
            {
                "tool_call": tool_calls[0],
                "result": "执行失败: artifact missing",
                "status": "error",
                "service_name": "native",
                "tool_name": "artifact_reader",
            }
        ]

    monkeypatch.setattr(tool_loop, "execute_tool_calls", fake_execute_tool_calls)
    primary_results = [
        _build_tagged_result(
            status="error",
            ref="artifact_missing",
            fetch_hints="line_range:20-40",
            truncated=True,
        )
    ]

    followups = asyncio.run(tool_loop._maybe_execute_gc_reader_followup(primary_results, "sess_gc_2", round_num=7))

    assert len(followups) == 2
    assert followups[0]["status"] == "error"
    assert followups[1]["service_name"] == "gc_reader_bridge"
    assert followups[1]["tool_name"] == "artifact_reader_suggestion"
    assert "[suggested_call] artifact_reader(" in str(followups[1]["result"])
