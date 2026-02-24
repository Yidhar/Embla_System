from apiserver.agentic_tool_loop import format_tool_results_for_llm


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
    assert "[记忆索引卡片 1/1 - native: run_cmd (success)]" in formatted
    assert "[tool/status] native: run_cmd (success)" in formatted
    assert "[narrative_summary]" in formatted
    assert "关键错误码已索引" in formatted
    assert "[forensic_artifact_ref] artifact_abc123" in formatted
    assert "[raw_result_ref] artifact_abc123" in formatted
    assert "[fetch_hints] jsonpath:$..error_code, line_range:20-40" in formatted
    assert "[ref_readback] artifact_reader(" in formatted


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
    assert formatted == "[工具结果 1/1 - native: read_file (success)]\nline1\nline2"
    assert "[记忆索引卡片" not in formatted


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
            "tool_name": "ask_guide",
            "status": "error",
            "result": {
                "narrative_summary": "摘要B",
                "raw_result_ref": "artifact_b",
                "fetch_hints": ["line_range:120-180"],
            },
        },
    ]

    formatted = format_tool_results_for_llm(results)
    blocks = formatted.split("\n\n")

    assert len(blocks) == 3
    assert blocks[0].startswith("[记忆索引卡片 1/3 - native: run_cmd (success)]")
    assert blocks[1].startswith("[工具结果 2/3 - native: read_file (success)]")
    assert blocks[2].startswith("[记忆索引卡片 3/3 - mcp: ask_guide (error)]")
    assert "[fetch_hints] jsonpath:$..trace_id, grep:ERROR" in blocks[0]
    assert "[fetch_hints] line_range:120-180" in blocks[2]
