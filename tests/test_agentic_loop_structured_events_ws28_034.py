from __future__ import annotations

import asyncio
import base64
import json
from types import SimpleNamespace
from typing import Any, Dict, List

import apiserver.agentic_tool_loop as tool_loop
import apiserver.llm_service as llm_service_module


def _policy(max_rounds: int, *, enable_summary_round: bool) -> tool_loop.AgenticLoopPolicy:
    return tool_loop.AgenticLoopPolicy(
        max_rounds=max_rounds,
        enable_summary_round=enable_summary_round,
        max_consecutive_tool_failures=5,
        max_consecutive_validation_failures=2,
        max_consecutive_no_tool_rounds=1,
        inject_no_tool_feedback=False,
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


def test_run_agentic_loop_events_emits_terminal_receipt(monkeypatch):
    class _NoToolLLM:
        async def stream_chat_with_context(self, *_args, **_kwargs):
            yield tool_loop._format_sse_event("content", {"text": "继续分析"})

    fake_cfg = SimpleNamespace(api=SimpleNamespace(temperature=0.0))
    monkeypatch.setattr(tool_loop, "get_config", lambda: fake_cfg)
    monkeypatch.setattr(tool_loop, "_resolve_agentic_loop_policy", lambda _max_rounds: _policy(2, enable_summary_round=True))
    monkeypatch.setattr(tool_loop, "_build_agentic_loop_watchdog", lambda: None)
    monkeypatch.setattr(llm_service_module, "get_llm_service", lambda: _NoToolLLM())
    monkeypatch.setattr(tool_loop, "archive_tool_results_for_session", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(tool_loop, "build_reinjection_context", lambda **_kwargs: "")
    monkeypatch.setattr(
        tool_loop,
        "_maybe_execute_gc_reader_followup",
        lambda *_args, **_kwargs: asyncio.sleep(0, result=[]),
    )

    async def _collect() -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        async for event in tool_loop.run_agentic_loop_events(
            [{"role": "user", "content": "推进任务"}],
            session_id="sess-events-1",
            max_rounds=2,
        ):
            rows.append(event)
        return rows

    events = asyncio.run(_collect())
    assert events
    assert any(str(row.get("type")) == "round_end" for row in events)

    receipts = [row for row in events if str(row.get("type")) == "execution_receipt"]
    assert receipts
    receipt = receipts[-1]
    assert receipt["stop_reason"] == "completion_not_submitted"
    assert receipt["submit_result_called"] is False


def test_run_agentic_loop_receipt_carries_submit_state_handoff(monkeypatch):
    class _SubmitCompletionLLM:
        async def stream_chat_with_context(self, *_args, **_kwargs):
            payload = [
                {
                    "id": "submit-result-structured-1",
                    "name": "SubmitResult_Tool",
                    "arguments": {
                        "task_completed": True,
                        "outcome_code": "PATCH_APPLIED",
                        "completion_summary": "变更已应用并通过验证",
                        "deliverables": ["patch", "tests"],
                        "artifact_refs": ["scratch/reports/ws28_receipt.json"],
                        "state_patch": {"tests_passed": True, "changed_files": 3},
                    },
                }
            ]
            yield tool_loop._format_sse_event("tool_calls", {"text": payload})

    fake_cfg = SimpleNamespace(api=SimpleNamespace(temperature=0.0))
    monkeypatch.setattr(tool_loop, "get_config", lambda: fake_cfg)
    monkeypatch.setattr(tool_loop, "_resolve_agentic_loop_policy", lambda _max_rounds: _policy(3, enable_summary_round=True))
    monkeypatch.setattr(tool_loop, "_build_agentic_loop_watchdog", lambda: None)
    monkeypatch.setattr(llm_service_module, "get_llm_service", lambda: _SubmitCompletionLLM())
    monkeypatch.setattr(tool_loop, "execute_tool_calls", lambda *_args, **_kwargs: asyncio.sleep(0, result=[]))
    monkeypatch.setattr(tool_loop, "archive_tool_results_for_session", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(tool_loop, "build_reinjection_context", lambda **_kwargs: "")
    monkeypatch.setattr(
        tool_loop,
        "_maybe_execute_gc_reader_followup",
        lambda *_args, **_kwargs: asyncio.sleep(0, result=[]),
    )

    receipt = asyncio.run(
        tool_loop.run_agentic_loop_receipt(
            [{"role": "user", "content": "完成后提交结构化收据"}],
            session_id="sess-events-2",
            max_rounds=3,
        )
    )
    assert receipt
    assert receipt["type"] == "execution_receipt"
    assert receipt["task_completed"] is True
    assert receipt["submit_result_called"] is True
    assert receipt["submit_result_round"] == 1
    assert receipt["agent_state"]["outcome_code"] == "PATCH_APPLIED"
    assert receipt["agent_state"]["artifact_refs"] == ["scratch/reports/ws28_receipt.json"]
    assert receipt["agent_state"]["state_patch"]["tests_passed"] is True


def test_decode_sse_payload_json_only_rejects_legacy_base64() -> None:
    payload = {"type": "content", "text": "json-only"}
    json_chunk = f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
    assert tool_loop._decode_sse_payload(json_chunk) == payload

    legacy_text = base64.b64encode(json.dumps(payload, ensure_ascii=False).encode("utf-8")).decode("ascii")
    legacy_chunk = f"data: {legacy_text}\n\n"
    assert tool_loop._decode_sse_payload(legacy_chunk) is None
