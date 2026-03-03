from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any, Dict, List

import agents.tool_loop as tool_loop
import apiserver.llm_service as llm_service_module
from system.config import ToolContractRolloutConfig


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
    assert cfg.mode == "new_stack_only"
    assert cfg.legacy_contract_enabled is False
    assert cfg.new_contract_enabled is True
    assert cfg.snapshot()["decommission_legacy_gate"] is True


def test_tool_contract_rollout_mode_aliases_normalize() -> None:
    legacy_cfg = ToolContractRolloutConfig(mode="legacy")
    dual_cfg = ToolContractRolloutConfig(mode="dual")
    new_cfg = ToolContractRolloutConfig(mode="new")

    assert legacy_cfg.mode == "new_stack_only"
    assert dual_cfg.mode == "new_stack_only"
    assert new_cfg.mode == "new_stack_only"


def test_dual_stack_legacy_payload_is_blocked_after_subagent_cutover(monkeypatch) -> None:
    _set_rollout(monkeypatch, mode="dual_stack", gate=False)
    enforced = tool_loop._enforce_tool_result_schema(
        _legacy_result_payload(),
        call={"tool_name": "read_file"},
        call_id="rollout_dual_1",
        default_service_name="native",
        default_tool_name="read_file",
    )

    assert enforced["status"] == "error"
    assert enforced["error_code"] == "E_LEGACY_CONTRACT_DECOMMISSIONED"
    assert enforced["_contract_rollout"]["used_legacy"] is True
    assert enforced["_contract_rollout"]["used_new"] is False
    assert enforced["_contract_rollout"]["legacy_blocked"] is True


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


def test_upgrade_tool_result_contract_payload_extracts_tagged_sections() -> None:
    upgraded = tool_loop._upgrade_tool_result_contract_payload(
        {
            "status": "success",
            "service_name": "native",
            "tool_name": "run_cmd",
            "result": (
                "[forensic_artifact_ref] artifact_x123\n"
                "[narrative_summary]\n"
                "legacy summary\n"
                "[display_preview]\n"
                "preview summary"
            ),
        }
    )

    assert upgraded["narrative_summary"] == "legacy summary"
    assert upgraded["display_preview"] == "preview summary"
    assert upgraded["forensic_artifact_ref"] == "artifact_x123"
    assert upgraded["raw_result_ref"] == "artifact_x123"


def test_execute_tool_call_with_retry_upgrades_legacy_payload_before_decommission_gate(monkeypatch) -> None:
    _set_rollout(monkeypatch, mode="new_stack_only", gate=True)

    async def _fake_execute_single_tool_call(call: Dict[str, Any], session_id: str) -> Dict[str, Any]:
        _ = (call, session_id)
        return {
            "status": "success",
            "service_name": "native",
            "tool_name": "read_file",
            "result": (
                "[forensic_artifact_ref] artifact_retry_001\n"
                "[narrative_summary]\n"
                "legacy path upgraded"
            ),
        }

    monkeypatch.setattr(tool_loop, "_execute_single_tool_call", _fake_execute_single_tool_call)

    async def _run_once() -> Dict[str, Any]:
        return await tool_loop._execute_tool_call_with_retry(
            {
                "agentType": "native",
                "tool_name": "read_file",
                "path": "README.md",
                "_tool_call_id": "call_retry_upgrade_1",
            },
            "sess_retry_upgrade",
            semaphore=asyncio.Semaphore(1),
            retry_failed=False,
            max_retries=0,
            retry_backoff_seconds=0.0,
        )

    row = asyncio.run(_run_once())
    assert row["status"] == "success"
    assert row.get("error_code") is None
    assert row["narrative_summary"] == "legacy path upgraded"
    assert row["display_preview"] == "legacy path upgraded"
    assert row["forensic_artifact_ref"] == "artifact_retry_001"
    assert row["_contract_rollout"]["legacy_blocked"] is False


def test_execute_tool_call_with_retry_upgrades_empty_legacy_payload_before_decommission_gate(monkeypatch) -> None:
    _set_rollout(monkeypatch, mode="new_stack_only", gate=True)

    async def _fake_execute_single_tool_call(call: Dict[str, Any], session_id: str) -> Dict[str, Any]:
        _ = (call, session_id)
        return {
            "status": "success",
            "service_name": "mcp",
            "tool_name": "dummy_tool",
            "result": None,
        }

    monkeypatch.setattr(tool_loop, "_execute_single_tool_call", _fake_execute_single_tool_call)

    async def _run_once() -> Dict[str, Any]:
        return await tool_loop._execute_tool_call_with_retry(
            {
                "agentType": "mcp",
                "service_name": "dummy",
                "tool_name": "dummy_tool",
                "_tool_call_id": "call_retry_upgrade_empty_1",
            },
            "sess_retry_upgrade_empty",
            semaphore=asyncio.Semaphore(1),
            retry_failed=False,
            max_retries=0,
            retry_backoff_seconds=0.0,
        )

    row = asyncio.run(_run_once())
    assert row["status"] == "success"
    assert row.get("error_code") is None
    assert row["_contract_rollout"]["legacy_blocked"] is False
    assert row["narrative_summary"]
    assert row["display_preview"]


def test_execute_mcp_call_emits_new_contract_fields(monkeypatch) -> None:
    class _FakeManager:
        async def unified_call(self, service_name: str, call: Dict[str, Any]) -> str:
            _ = (service_name, call)
            return json.dumps(
                {
                    "status": "ok",
                    "result": "mcp completed",
                    "forensic_artifact_ref": "artifact_mcp_001",
                },
                ensure_ascii=False,
            )

    import mcpserver.mcp_manager as mcp_manager_module

    monkeypatch.setattr(mcp_manager_module, "get_mcp_manager", lambda: _FakeManager())

    async def _run_mcp_call() -> Dict[str, Any]:
        return await tool_loop._execute_mcp_call(
            {
                "agentType": "mcp",
                "service_name": "dummy-service",
                "tool_name": "dummy-tool",
                "_tool_call_id": "call_mcp_upgrade_1",
            }
        )

    row = asyncio.run(_run_mcp_call())
    assert row["status"] == "success"
    assert row["narrative_summary"] == "mcp completed"
    assert row["display_preview"] == "mcp completed"
    assert row["forensic_artifact_ref"] == "artifact_mcp_001"
    assert row["raw_result_ref"] == "artifact_mcp_001"


def test_extract_mcp_call_status_supports_none_and_dict_payloads() -> None:
    status, detail = tool_loop._extract_mcp_call_status(None)
    assert status == "ok"
    assert "empty mcp response" in detail

    status2, detail2 = tool_loop._extract_mcp_call_status({"status": "error", "message": "boom"})
    assert status2 == "error"
    assert detail2 == "boom"


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
        async for event in tool_loop.run_agentic_loop(
            [{"role": "user", "content": "读取 README"}],
            session_id="sess-rollout-meta",
            max_rounds=1,
        ):
            if isinstance(event, dict):
                events.append(event)
        return events

    events = asyncio.run(_collect_events())
    assert events

    snapshot_events = [event for event in events if event.get("type") == "contract_rollout_snapshot"]
    assert snapshot_events
    assert snapshot_events[0]["snapshot"]["mode"] == "new_stack_only"

    tool_result_events = [event for event in events if event.get("type") == "tool_results"]
    assert tool_result_events
    metadata = tool_result_events[0].get("metadata", {})
    assert metadata["contract_rollout"]["snapshot"]["mode"] == "new_stack_only"
    assert metadata["contract_rollout"]["stats"]["legacy_payload_count"] >= 1


def test_agentic_loop_contract_state_transitions_seed_to_execution(monkeypatch) -> None:
    class _FakeLLMService:
        async def stream_chat_with_context(self, *_args, **_kwargs):
            payload = [
                {
                    "id": "rollout_call_exec_1",
                    "name": "native_call",
                    "arguments": {"tool_name": "write_file", "path": "scratch/x.txt", "content": "x"},
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

    captured_calls: List[Dict[str, Any]] = []

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
        captured_calls.extend(tool_calls)
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
        async for event in tool_loop.run_agentic_loop(
            [{"role": "user", "content": "修复这个写入错误并提交补丁"}],
            session_id="sess-rollout-contract-state",
            max_rounds=1,
        ):
            if isinstance(event, dict):
                events.append(event)
        return events

    events = asyncio.run(_collect_events())
    contract_events = [event for event in events if event.get("type") == "contract_state"]
    assert len(contract_events) >= 2
    transitions = [str(event.get("transition") or "") for event in contract_events]
    assert "seed_initialized" in transitions
    assert "seed_to_execution" in transitions

    upgraded = next(event for event in contract_events if event.get("transition") == "seed_to_execution")
    assert upgraded.get("contract_stage") == "execution"
    assert upgraded.get("execution_contract_id")
    assert upgraded.get("execution_contract_checksum")
    assert float(upgraded.get("contract_upgrade_latency_ms") or 0.0) >= 0.0

    assert captured_calls
    first_call = captured_calls[0]
    assert first_call.get("_contract_id")
    assert first_call.get("_contract_checksum")
    assert first_call.get("_contract_stage") == "execution"


def test_agentic_loop_parallel_missing_checksum_downgrades_to_readonly(monkeypatch) -> None:
    class _FakeLLMService:
        async def stream_chat_with_context(self, *_args, **_kwargs):
            payload = [
                {
                    "id": "rollout_call_gate_1",
                    "name": "native_call",
                    "arguments": {"tool_name": "write_file", "path": "scratch/a.txt", "content": "a"},
                },
                {
                    "id": "rollout_call_gate_2",
                    "name": "native_call",
                    "arguments": {
                        "tool_name": "workspace_txn_apply",
                        "changes": [{"path": "scratch/b.txt", "content": "b"}],
                    },
                },
                {
                    "id": "rollout_call_gate_3",
                    "name": "native_call",
                    "arguments": {"tool_name": "read_file", "path": "README.md"},
                },
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
            max_parallel_tool_calls=3,
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

    captured_calls: List[Dict[str, Any]] = []

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
        captured_calls.extend(tool_calls)
        return [
            {
                "status": "success",
                "service_name": "native",
                "tool_name": str(call.get("tool_name") or "unknown"),
                "result": "ok",
            }
            for call in tool_calls
        ]

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
        async for event in tool_loop.run_agentic_loop(
            [{"role": "user", "content": "请先读取并分析仓库结构"}],
            session_id="sess-rollout-gate-readonly",
            max_rounds=1,
        ):
            if isinstance(event, dict):
                events.append(event)
        return events

    events = asyncio.run(_collect_events())
    assert captured_calls
    assert len(captured_calls) == 1
    assert captured_calls[0]["tool_name"] == "read_file"
    assert all(str(call.get("tool_name") or "") not in {"write_file", "workspace_txn_apply"} for call in captured_calls)

    gate_events = [event for event in events if event.get("type") == "contract_gate"]
    assert gate_events
    gate_payload = gate_events[0]
    assert gate_payload.get("readonly_downgraded") is True
    assert gate_payload.get("force_serial") is False
    assert gate_payload.get("dropped_mutating_calls") == 2
    assert gate_payload.get("reason") == "contract_checksum_missing_parallel_write_downgraded_to_readonly"

    tool_result_events = [event for event in events if event.get("type") == "tool_results"]
    assert tool_result_events
    summaries = tool_result_events[0].get("results", [])
    assert any(str(row.get("service_name") or "") == "tool_protocol" for row in summaries)
