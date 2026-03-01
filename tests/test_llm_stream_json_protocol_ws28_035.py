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
