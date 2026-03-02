from __future__ import annotations

import asyncio
import json
import zipfile
from pathlib import Path

from mcpserver.agent_office_doc.agent_office_doc import OfficeDocAgent
from mcpserver.agent_playwright_master.agent_playwright_master import PlaywrightMasterAgent
from mcpserver.agent_vision.agent_vision import VisionAgent
from mcpserver.mcp_registry import clear_registry, scan_and_register_mcp_agents


def _write_min_docx(path: Path) -> None:
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>"
        "<w:p><w:r><w:t>Hello Embla</w:t></w:r></w:p>"
        "<w:p><w:r><w:t>Office Parser</w:t></w:r></w:p>"
        "</w:body>"
        "</w:document>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", document_xml)


def _write_min_xlsx(path: Path) -> None:
    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        "<sheets><sheet name=\"Sheet1\" sheetId=\"1\" r:id=\"rId1\"/></sheets>"
        "</workbook>"
    )
    rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        "<Relationship Id=\"rId1\" "
        "Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet\" "
        "Target=\"worksheets/sheet1.xml\"/>"
        "</Relationships>"
    )
    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        "<sheetData>"
        "<row r=\"1\"><c r=\"A1\" t=\"inlineStr\"><is><t>name</t></is></c><c r=\"B1\" t=\"inlineStr\"><is><t>value</t></is></c></row>"
        "<row r=\"2\"><c r=\"A2\" t=\"inlineStr\"><is><t>alpha</t></is></c><c r=\"B2\"><v>123</v></c></row>"
        "</sheetData>"
        "</worksheet>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/_rels/workbook.xml.rels", rels_xml)
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)


def test_playwright_agent_requires_url() -> None:
    agent = PlaywrightMasterAgent()
    raw = asyncio.run(agent.handle_handoff({"tool_name": "open_url"}))
    payload = json.loads(raw)
    assert payload["status"] == "error"
    assert "url" in payload["message"]


def test_playwright_agent_success_with_monkeypatch(monkeypatch) -> None:
    agent = PlaywrightMasterAgent()

    async def _fake_execute_action(**kwargs):
        return {
            "action": kwargs["action"],
            "url": kwargs["url"],
            "final_url": kwargs["url"],
            "title": "Example Domain",
        }

    monkeypatch.setattr(agent, "_execute_action", _fake_execute_action)
    raw = asyncio.run(agent.handle_handoff({"tool_name": "open_url", "url": "https://example.com"}))
    payload = json.loads(raw)
    assert payload["status"] == "ok"
    assert payload["data"]["title"] == "Example Domain"


def test_vision_agent_inspect_image_and_qa() -> None:
    agent = VisionAgent()
    tiny_png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO6xg1kAAAAASUVORK5CYII="

    inspect_raw = asyncio.run(
        agent.handle_handoff(
            {
                "tool_name": "inspect_image",
                "image_base64": tiny_png,
            }
        )
    )
    inspect_payload = json.loads(inspect_raw)
    assert inspect_payload["status"] == "ok"
    assert inspect_payload["data"]["metadata"]["width"] == 1
    assert inspect_payload["data"]["metadata"]["height"] == 1


def test_vision_agent_image_qa_uses_multimodal_when_available(monkeypatch) -> None:
    agent = VisionAgent()
    tiny_png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO6xg1kAAAAASUVORK5CYII="
    emitted_events: list[tuple[str, dict]] = []

    class _DummyStore:
        def emit(self, event_type, payload, **kwargs):  # noqa: ANN001
            emitted_events.append((str(event_type), dict(payload)))

    monkeypatch.setattr(
        agent,
        "_resolve_multimodal_runtime",
        lambda task: {
            "api_key": "sk-test",
            "base_url": "http://127.0.0.1:9999/v1",
            "model": "gpt-4o-mini",
            "timeout_seconds": 30.0,
            "max_tokens": 256,
            "temperature": 0.2,
            "reasoning_effort": "",
            "extra_headers": {},
            "extra_body": {},
        },
    )

    async def _fake_multimodal_qa(**kwargs):
        assert kwargs["question"] == "这张图里有什么？"
        return "这是一个 1x1 的测试图片。", {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}

    monkeypatch.setattr(agent, "_ask_multimodal_qa", _fake_multimodal_qa)
    monkeypatch.setattr(agent, "_get_event_store", lambda: _DummyStore())

    qa_raw = asyncio.run(
        agent.handle_handoff(
            {
                "tool_name": "image_qa",
                "image_base64": tiny_png,
                "question": "这张图里有什么？",
            }
        )
    )
    qa_payload = json.loads(qa_raw)
    assert qa_payload["status"] == "ok"
    assert qa_payload["data"]["qa_mode"] == "multimodal_llm"
    assert qa_payload["data"]["answer"] == "这是一个 1x1 的测试图片。"
    assert qa_payload["data"]["llm_usage"]["total_tokens"] == 18
    assert emitted_events
    assert emitted_events[-1][0] == "VisionMultimodalQASucceeded"


def test_vision_agent_image_qa_fallback_when_llm_unavailable(monkeypatch) -> None:
    agent = VisionAgent()
    tiny_png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO6xg1kAAAAASUVORK5CYII="
    emitted_events: list[tuple[str, dict]] = []

    class _DummyStore:
        def emit(self, event_type, payload, **kwargs):  # noqa: ANN001
            emitted_events.append((str(event_type), dict(payload)))

    monkeypatch.setattr(agent, "_resolve_multimodal_runtime", lambda task: None)
    monkeypatch.setattr(agent, "_get_event_store", lambda: _DummyStore())

    qa_raw = asyncio.run(
        agent.handle_handoff(
            {
                "tool_name": "image_qa",
                "image_base64": tiny_png,
                "question": "这张图尺寸是多少？",
            }
        )
    )
    qa_payload = json.loads(qa_raw)
    assert qa_payload["status"] == "ok"
    assert qa_payload["data"]["qa_mode"] == "metadata_fallback"
    assert "1x1" in qa_payload["data"]["answer"]
    assert emitted_events
    assert emitted_events[-1][0] == "VisionMultimodalQAFallback"


def test_vision_agent_image_qa_emits_error_event_when_llm_call_fails(monkeypatch) -> None:
    agent = VisionAgent()
    tiny_png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO6xg1kAAAAASUVORK5CYII="
    emitted_events: list[tuple[str, dict]] = []

    class _DummyStore:
        def emit(self, event_type, payload, **kwargs):  # noqa: ANN001
            emitted_events.append((str(event_type), dict(payload)))

    monkeypatch.setattr(
        agent,
        "_resolve_multimodal_runtime",
        lambda task: {
            "api_key": "sk-secret",
            "base_url": "https://example.com/v1",
            "model": "gpt-4o-mini",
            "timeout_seconds": 20.0,
            "max_tokens": 128,
            "temperature": 0.2,
            "reasoning_effort": "",
            "extra_headers": {},
            "extra_body": {},
        },
    )

    async def _fake_fail(**kwargs):
        raise RuntimeError("upstream timeout sk-secret")

    monkeypatch.setattr(agent, "_ask_multimodal_qa", _fake_fail)
    monkeypatch.setattr(agent, "_get_event_store", lambda: _DummyStore())

    qa_raw = asyncio.run(
        agent.handle_handoff(
            {
                "tool_name": "image_qa",
                "image_base64": tiny_png,
                "question": "这张图尺寸是多少？",
            }
        )
    )
    qa_payload = json.loads(qa_raw)
    assert qa_payload["status"] == "ok"
    assert qa_payload["data"]["qa_mode"] == "metadata_fallback"
    assert qa_payload["data"]["llm_error"]
    assert "sk-secret" not in qa_payload["data"]["llm_error"]
    assert emitted_events
    assert emitted_events[-1][0] == "VisionMultimodalQAError"


def test_office_doc_agent_read_docx(tmp_path: Path) -> None:
    agent = OfficeDocAgent()
    docx_path = tmp_path / "demo.docx"
    _write_min_docx(docx_path)

    raw = asyncio.run(
        agent.handle_handoff(
            {
                "tool_name": "read_docx",
                "path": str(docx_path),
            }
        )
    )
    payload = json.loads(raw)
    assert payload["status"] == "ok"
    assert payload["data"]["file_type"] == "docx"
    assert "Hello Embla" in payload["data"]["content_text"]


def test_office_doc_agent_read_xlsx(tmp_path: Path) -> None:
    agent = OfficeDocAgent()
    xlsx_path = tmp_path / "demo.xlsx"
    _write_min_xlsx(xlsx_path)

    raw = asyncio.run(
        agent.handle_handoff(
            {
                "tool_name": "read_xlsx",
                "path": str(xlsx_path),
                "sheet_name": "Sheet1",
            }
        )
    )
    payload = json.loads(raw)
    assert payload["status"] == "ok"
    assert payload["data"]["file_type"] == "xlsx"
    assert payload["data"]["sheet_name"] == "Sheet1"
    assert payload["data"]["rows"][0]["A1"] == "name"


def test_registry_contains_second_batch_services() -> None:
    clear_registry()
    try:
        registered = scan_and_register_mcp_agents("mcpserver")
        assert "playwright_master" in registered
        assert "vision" in registered
        assert "office_doc" in registered
    finally:
        clear_registry()
