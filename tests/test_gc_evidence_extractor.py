from __future__ import annotations

import json

from system.gc_evidence_extractor import build_gc_fetch_hints, extract_gc_evidence


def test_extract_gc_evidence_from_text_log() -> None:
    log_text = "\n".join(
        [
            "2026-02-24 10:00:00 ERROR trace_id=trace_abc123xyz error_code=ERR_DB_DEADLOCK",
            'File "/srv/app/worker.py", line 42, in process_job',
            "    at com.example.OrderService.handle(OrderService.java:88)",
            "panic: invalid pointer addr=7FFDF0A12010",
            "hex crash @ 0x7ffdf0a12000",
            r"windows log: C:\ProgramData\Embla\logs\agent.log",
        ]
    )

    evidence = extract_gc_evidence(log_text, content_type="text/plain")

    assert "trace_abc123xyz" in evidence.trace_ids
    assert "ERR_DB_DEADLOCK" in evidence.error_codes
    assert "com.example.OrderService.handle" in evidence.stack_tokens
    assert "process_job" in evidence.stack_tokens
    assert "/srv/app/worker.py" in evidence.paths
    assert r"C:\ProgramData\Embla\logs\agent.log" in evidence.paths
    assert "0x7ffdf0a12000" in evidence.hex_addresses
    assert "0x7ffdf0a12010" in evidence.hex_addresses

    hints = build_gc_fetch_hints(evidence, content_type="text/plain")
    assert "line_range:1-100" in hints
    assert "grep:ERROR" in hints
    assert "grep:trace_abc123xyz" in hints
    assert "grep:ERR_DB_DEADLOCK" in hints


def test_extract_gc_evidence_from_json_payload() -> None:
    payload = {
        "trace_id": "trace-json-001",
        "error_code": "ERR_CACHE_MISS",
        "stack": "at Service.run (/srv/app/main.js:10:2)",
        "file_path": "/srv/app/main.js",
        "memory_address": "0xDEADBEEF",
        "nested": {
            "traceId": "trace-json-002",
            "errorCode": 503,
        },
    }
    raw_json = json.dumps(payload, ensure_ascii=False)

    evidence = extract_gc_evidence(raw_json, content_type="application/json")

    assert "trace-json-001" in evidence.trace_ids
    assert "trace-json-002" in evidence.trace_ids
    assert "ERR_CACHE_MISS" in evidence.error_codes
    assert "503" in evidence.error_codes
    assert "Service.run" in evidence.stack_tokens
    assert "/srv/app/main.js" in evidence.paths
    assert "0xdeadbeef" in evidence.hex_addresses

    hints = build_gc_fetch_hints(evidence, content_type="application/json")
    assert "jsonpath:$..error_code" in hints
    assert "jsonpath:$..trace_id" in hints
    assert "grep:trace-json-001" in hints
    assert "grep:ERR_CACHE_MISS" in hints
    assert "grep:0xdeadbeef" in hints
