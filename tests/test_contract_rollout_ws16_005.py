from __future__ import annotations

import asyncio
import base64
import json
from types import SimpleNamespace
from typing import Any, Dict, List

import apiserver.agentic_tool_loop as tool_loop
import apiserver.llm_service as llm_service_module
from system.config import ToolContractRolloutConfig


def _decode_sse_payload(chunk: str) -> Dict[str, Any] | None:
    if not chunk.startswith("data: "):
        return None
    payload_text = chunk[6:].strip()
    if not payload_text or payload_text == "[DONE]":
        return None
    decoded = base64.b64decode(payload_text).decode("utf-8")
    return json.loads(decoded)


def _set_rollout(monkeypatch, *, mode: str, gate: bool, emit_metadata: bool = True) -> None:
    fake_cfg = SimpleNamespace(
        tool_contract_rollout=SimpleNamespace(
            mode=mode,
            decommission_legacy_gate=gate,
            emit_observability_metadata=emit_metadata,
        )
    )
    monkeypatch.setattr(tool_loop, "get_config", lambda: fake_cfg)


def _legacy_result_payload() -> Dict[str, Any]:
    return {
        "status": "success",
        "service_name": "native",
        "tool_name": "read_file",
        "result": "legacy-ok",
    }


def test_tool_contract_rollout_config_defaults() -> None:
    cfg = ToolContractRolloutConfig()
    assert cfg.mode == "dual_stack"
    assert cfg.legacy_contract_enabled is True
    assert cfg.new_contract_enabled is True
    assert cfg.snapshot()["decommission_legacy_gate"] is False


def test_tool_contract_rollout_mode_aliases_normalize() -> None:
    legacy_cfg = ToolContractRolloutConfig(mode="legacy")
    dual_cfg = ToolContractRolloutConfig(mode="dual")
    new_cfg = ToolContractRolloutConfig(mode="new")

    assert legacy_cfg.mode == "legacy_only"
    assert dual_cfg.mode == "dual_stack"
    assert new_cfg.mode == "new_stack_only"


def test_dual_stack_backfills_new_contract_fields(monkeypatch) -> None:
    _set_rollout(monkeypatch, mode="dual_stack", gate=False)
    enforced = tool_loop._enforce_tool_result_schema(
        _legacy_result_payload(),
        call={"tool_name": "read_file"},
        call_id="rollout_dual_1",
        default_service_name="native",
        default_tool_name="read_file",
    )

    assert enforced["status"] == "success"
    assert enforced["result"] == "legacy-ok"
    assert enforced["narrative_summary"] == "legacy-ok"
    assert enforced["display_preview"] == "legacy-ok"
    assert enforced["_contract_rollout"]["used_legacy"] is True
    assert enforced["_contract_rollout"]["used_new"] is True
    assert enforced["_contract_rollout"]["legacy_blocked"] is False


def test_new_stack_only_blocks_legacy_only_result(monkeypatch) -> None:
    _set_rollout(monkeypatch, mode="new_stack_only", gate=True)
    enforced = tool_loop._enforce_tool_result_schema(
        _legacy_result_payload(),
        call={"tool_name": "read_file"},
        call_id="rollout_new_1",
        default_service_name="native",
        default_tool_name="read_file",
    )

    assert enforced["status"] == "error"
    assert enforced["error_code"] == "E_LEGACY_CONTRACT_DECOMMISSIONED"
    assert "legacy-only result blocked by decommission gate" in enforced["result"]
    assert enforced["_contract_rollout"]["legacy_blocked"] is True


def test_new_stack_only_accepts_new_contract_payload(monkeypatch) -> None:
    _set_rollout(monkeypatch, mode="new_stack_only", gate=True)
    enforced = tool_loop._enforce_tool_result_schema(
        {
            "status": "success",
            "service_name": "native",
            "tool_name": "read_file",
            "narrative_summary": "new-ok",
            "forensic_artifact_ref": "artifact_123",
        },
        call={"tool_name": "read_file"},
        call_id="rollout_new_2",
        default_service_name="native",
        default_tool_name="read_file",
    )

    assert enforced["status"] == "success"
    assert "result" not in enforced
    assert enforced["_contract_rollout"]["used_legacy"] is False
    assert enforced["_contract_rollout"]["used_new"] is True
    summary = tool_loop._summarize_results_for_frontend(
        [enforced],
        500,
        rollout=tool_loop.ToolContractRolloutRuntime(
            mode="new_stack_only",
            decommission_legacy_gate=True,
        ),
    )[0]
    assert "result" not in summary
    assert summary["narrative_summary"] == "new-ok"


def test_agentic_loop_emits_rollout_snapshot_and_tool_results_metadata(monkeypatch) -> None:
    class _FakeLLMService:
        async def stream_chat_with_context(self, *_args, **_kwargs):
            payload = [
                {
                    "id": "rollout_call_1",
                    "name": "native_call",
                    "arguments": {"tool_name": "read_file", "path": "README.md"},
                }
            ]
            yield tool_loop._format_sse_event("tool_calls", {"text": payload})

    fake_cfg = SimpleNamespace(
        handoff=SimpleNamespace(max_loop_stream=1),
        agentic_loop=SimpleNamespace(
            max_rounds_stream=1,
            enable_summary_round=False,
            max_consecutive_tool_failures=2,
            max_consecutive_validation_failures=2,
            max_consecutive_no_tool_rounds=2,
            inject_no_tool_feedback=False,
            tool_result_preview_chars=500,
            emit_workflow_stage_events=False,
            max_parallel_tool_calls=1,
            retry_failed_tool_calls=False,
            max_tool_retries=0,
            retry_backoff_seconds=0.0,
            gc_budget_guard_enabled=False,
            gc_budget_repeat_threshold=2,
            gc_budget_window_size=4,
        ),
        api=SimpleNamespace(temperature=0.0),
        tool_contract_rollout=SimpleNamespace(
            mode="dual_stack",
            decommission_legacy_gate=False,
            emit_observability_metadata=True,
        ),
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
        return [_legacy_result_payload()]

    monkeypatch.setattr(tool_loop, "get_config", lambda: fake_cfg)
    monkeypatch.setattr(llm_service_module, "get_llm_service", lambda: _FakeLLMService())
    monkeypatch.setattr(tool_loop, "execute_tool_calls", _fake_execute_tool_calls)
    monkeypatch.setattr(
        tool_loop,
        "_maybe_execute_gc_reader_followup",
        lambda *_args, **_kwargs: asyncio.sleep(0, result=[]),
    )
    monkeypatch.setattr(tool_loop, "archive_tool_results_for_session", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(tool_loop, "build_reinjection_context", lambda **_kwargs: "")

    async def _collect_events() -> List[Dict[str, Any]]:
        events: List[Dict[str, Any]] = []
        async for chunk in tool_loop.run_agentic_loop(
            [{"role": "user", "content": "读取 README"}],
            session_id="sess-rollout-meta",
            max_rounds=1,
        ):
            payload = _decode_sse_payload(chunk)
            if payload:
                events.append(payload)
        return events

    events = asyncio.run(_collect_events())
    assert events

    snapshot_events = [event for event in events if event.get("type") == "contract_rollout_snapshot"]
    assert snapshot_events
    assert snapshot_events[0]["snapshot"]["mode"] == "dual_stack"

    tool_result_events = [event for event in events if event.get("type") == "tool_results"]
    assert tool_result_events
    metadata = tool_result_events[0].get("metadata", {})
    assert metadata["contract_rollout"]["snapshot"]["mode"] == "dual_stack"
    assert metadata["contract_rollout"]["stats"]["legacy_payload_count"] >= 1
