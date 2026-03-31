from __future__ import annotations

import json

from apiserver.llm_service import LLMService


def test_llm_service_formats_json_sse_chunk() -> None:
    service = LLMService()
    chunk = service._format_sse_chunk("content", "hello")
    assert chunk.startswith("data: ")
    payload_text = chunk[len("data: ") :].strip()
    payload = json.loads(payload_text)
    assert payload["type"] == "content"
    assert payload["text"] == "hello"


def test_llm_service_normalizes_raw_tool_schema_to_openai_function() -> None:
    normalized = LLMService._normalize_openai_tool_schema(
        {
            "name": "get_system_status",
            "description": "Return system status.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        }
    )

    assert normalized == {
        "type": "function",
        "function": {
            "name": "get_system_status",
            "description": "Return system status.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    }


def test_llm_service_keeps_wrapped_tool_schema() -> None:
    wrapped = {
        "type": "function",
        "function": {
            "name": "native_call",
            "description": "Execute a native tool.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tool_name": {"type": "string"},
                },
            },
        },
    }

    normalized = LLMService._normalize_openai_tool_schema(wrapped)
    assert normalized == wrapped
