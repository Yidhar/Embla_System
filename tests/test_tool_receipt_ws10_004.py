from __future__ import annotations

import asyncio
import json

import agents.tool_loop as tool_loop


def test_build_tool_receipt_error_path_uses_context_and_defaults() -> None:
    call = {
        "agentType": "native",
        "tool_name": "run_cmd",
        "_trace_id": "trace_ws10_receipt_1",
        "_risk_level": "write_repo",
        "_execution_scope": "global",
        "_requires_global_mutex": True,
        "estimated_token_cost": 120,
        "budget_remaining": "900",
        "_context_metadata": {"idempotency_key": "idem_ws10_receipt_1"},
    }
    result = {
        "status": "error",
        "service_name": "native",
        "tool_name": "run_cmd",
        "error_code": "E_SCHEMA_OUTPUT_INVALID",
        "forensic_artifact_ref": "artifact_ws10_receipt_1",
    }

    receipt = tool_loop._build_tool_receipt(call, result)

    assert receipt["version"] == "ws10-004-v1"
    assert receipt["trace_id"] == "trace_ws10_receipt_1"
    assert receipt["idempotency_key"] == "idem_ws10_receipt_1"
    assert receipt["risk_level"] == "write_repo"
    assert receipt["execution_scope"] == "global"
    assert receipt["requires_global_mutex"] is True
    assert receipt["budget"]["estimated_token_cost"] == 120
    assert receipt["budget"]["budget_remaining"] == 900
    assert receipt["result"]["status"] == "error"
    assert receipt["result"]["error_code"] == "E_SCHEMA_OUTPUT_INVALID"
    assert receipt["result"]["forensic_artifact_ref"] == "artifact_ws10_receipt_1"
    assert "tool_execution_failed" in receipt["risk_items"]
    assert "high_risk_action:write_repo" in receipt["risk_items"]
    assert "global_mutex_required" in receipt["risk_items"]
    assert receipt["next_steps"] == ["inspect_error_and_retry", "read_artifact_with_artifact_reader"]


def test_build_tool_receipt_success_default_next_steps_for_read_only() -> None:
    call = {
        "agentType": "native",
        "tool_name": "read_file",
        "_risk_level": "read_only",
        "_execution_scope": "local",
        "_requires_global_mutex": False,
    }
    result = {
        "status": "success",
        "service_name": "native",
        "tool_name": "read_file",
        "result": "ok",
    }

    receipt = tool_loop._build_tool_receipt(call, result)
    assert receipt["result"]["status"] == "success"
    assert receipt["risk_items"] == []
    assert receipt["next_steps"] == ["continue_next_planned_step"]


def test_execute_tool_call_with_retry_attaches_tool_receipt(monkeypatch) -> None:
    async def _fake_execute(call: dict, session_id: str) -> dict:
        _ = session_id
        return {
            "tool_call": call,
            "status": "success",
            "service_name": "native",
            "tool_name": "read_file",
            "result": "ok",
        }

    monkeypatch.setattr(tool_loop, "_execute_single_tool_call", _fake_execute)

    call = {
        "agentType": "native",
        "tool_name": "read_file",
        "path": "README.md",
        "_trace_id": "trace_ws10_receipt_2",
    }
    row = asyncio.run(
        tool_loop._execute_tool_call_with_retry(
            call,
            "sess_ws10_receipt_2",
            semaphore=asyncio.Semaphore(1),
            retry_failed=False,
            max_retries=0,
            retry_backoff_seconds=0.0,
        )
    )

    assert row["status"] == "success"
    receipt = row.get("tool_receipt")
    assert isinstance(receipt, dict)
    assert receipt["trace_id"] == "trace_ws10_receipt_2"
    assert receipt["tool_name"] == "read_file"
    assert receipt["result"]["status"] == "success"


def test_summarize_results_for_frontend_backfills_tool_receipt() -> None:
    result_rows = [
        {
            "tool_call": {
                "agentType": "native",
                "tool_name": "write_file",
                "_risk_level": "write_repo",
                "_execution_scope": "local",
            },
            "status": "success",
            "service_name": "native",
            "tool_name": "write_file",
            "narrative_summary": "patched file",
            "display_preview": "patched file",
        }
    ]
    summaries = tool_loop._summarize_results_for_frontend(
        result_rows,
        500,
        rollout=tool_loop.ToolContractRolloutRuntime(),
    )

    assert len(summaries) == 1
    receipt = summaries[0].get("tool_receipt")
    assert isinstance(receipt, dict)
    assert receipt["risk_level"] == "write_repo"
    assert "run_post_change_verification" in receipt["next_steps"]


def test_format_tool_results_for_llm_includes_tool_receipt_block() -> None:
    row = {
        "status": "success",
        "service_name": "native",
        "tool_name": "read_file",
        "result": "done",
    }
    call = {
        "agentType": "native",
        "tool_name": "read_file",
        "_risk_level": "read_only",
        "_execution_scope": "local",
    }
    row["tool_receipt"] = tool_loop._build_tool_receipt(call, row)

    formatted = tool_loop.format_tool_results_for_llm([row])
    payload = json.loads(formatted)
    assert payload["schema"] == "agentic_tool_results.v2"
    assert payload["total_results"] == 1
    result = payload["results"][0]
    assert result["status"] == "success"
    assert result["service_name"] == "native"
    assert result["tool_name"] == "read_file"
    assert result["tool_receipt"]["risk_level"] == "read_only"
    assert result["tool_receipt"]["result"]["status"] == "success"
    assert result["tool_receipt"]["next_steps"] == ["continue_next_planned_step"]
