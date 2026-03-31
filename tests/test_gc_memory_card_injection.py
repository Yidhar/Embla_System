import json

from agents.tool_loop import format_tool_results_for_llm


def test_format_tool_results_uses_memory_index_card_when_ref_present():
    results = [
        {
            "service_name": "native",
            "tool_name": "run_cmd",
            "status": "success",
            "result": (
                "[forensic_artifact_ref] artifact_abc123\n"
                "[raw_result_ref] artifact_abc123\n"
                "[fetch_hints] jsonpath:$..error_code, line_range:20-40\n"
                "[narrative_summary]\n"
                "命令执行完成，关键错误码已索引。"
            ),
        }
    ]

    formatted = format_tool_results_for_llm(results)
    payload = json.loads(formatted)
    assert payload["schema"] == "agentic_tool_results.v2"
    assert payload["total_results"] == 1
    result = payload["results"][0]
    assert result["status"] == "success"
    assert result["service_name"] == "native"
    assert result["tool_name"] == "run_cmd"
    assert "[记忆索引卡片 1/1 - native: run_cmd (success)]" in result["memory_card"]
    assert "[tool/status] native: run_cmd (success)" in result["memory_card"]
    assert "[narrative_summary]" in result["memory_card"]
    assert "关键错误码已索引" in result["memory_card"]
    assert "[forensic_artifact_ref] artifact_abc123" in result["memory_card"]
    assert "[raw_result_ref] artifact_abc123" in result["memory_card"]
    assert "[fetch_hints] jsonpath:$..error_code, line_range:20-40" in result["memory_card"]
    assert "[ref_readback] artifact_reader(" in result["memory_card"]


def test_format_tool_results_without_ref_keeps_legacy_format():
    results = [
        {
            "service_name": "native",
            "tool_name": "read_file",
            "status": "success",
            "result": "line1\nline2",
        }
    ]

    formatted = format_tool_results_for_llm(results)
    payload = json.loads(formatted)
    assert payload["schema"] == "agentic_tool_results.v2"
    assert payload["total_results"] == 1
    result = payload["results"][0]
    assert result["service_name"] == "native"
    assert result["tool_name"] == "read_file"
    assert result["result_text"] == "line1\nline2"
    assert result["memory_card"] == ""


def test_format_tool_results_multi_item_aggregation_is_stable():
    results = [
        {
            "service_name": "native",
            "tool_name": "run_cmd",
            "status": "success",
            "result": "structured payload archived",
            "narrative_summary": "摘要A",
            "forensic_artifact_ref": "artifact_a",
            "fetch_hints": ["jsonpath:$..trace_id", "grep:ERROR"],
        },
        {
            "service_name": "native",
            "tool_name": "read_file",
            "status": "success",
            "result": "short text",
        },
        {
            "service_name": "mcp",
            "tool_name": "today_weather",
            "status": "error",
            "result": {
                "narrative_summary": "摘要B",
                "raw_result_ref": "artifact_b",
                "fetch_hints": ["line_range:120-180"],
            },
        },
    ]

    formatted = format_tool_results_for_llm(results)
    payload = json.loads(formatted)
    assert payload["schema"] == "agentic_tool_results.v2"
    assert payload["total_results"] == 3

    rows = payload["results"]
    assert len(rows) == 3
    assert rows[0]["memory_card"].startswith("[记忆索引卡片 1/3 - native: run_cmd (success)]")
    assert rows[1]["memory_card"] == ""
    assert rows[1]["result_text"] == "short text"
    assert rows[2]["memory_card"].startswith("[记忆索引卡片 3/3 - mcp: today_weather (error)]")
    assert "[fetch_hints] jsonpath:$..trace_id, grep:ERROR" in rows[0]["memory_card"]
    assert "[fetch_hints] line_range:120-180" in rows[2]["memory_card"]
