"""
Native tools integration tests for WS11/WS12/WS17 hardening path.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from apiserver.native_tools import NativeToolExecutor
from system.artifact_store import ArtifactStore, ArtifactStoreConfig, ContentType
import system.artifact_store as artifact_store_module


@pytest.fixture
def isolated_artifact_store(tmp_path, monkeypatch):
    store = ArtifactStore(
        ArtifactStoreConfig(
            artifact_root=tmp_path / "artifacts",
            max_total_size_mb=64,
            max_single_artifact_mb=16,
            max_artifact_count=200,
        )
    )
    monkeypatch.setattr(artifact_store_module, "_artifact_store", store)
    return store


def test_artifact_reader_jsonpath_roundtrip(isolated_artifact_store):
    payload = {
        "records": [
            {"trace_id": "trace-1", "error_code": 500},
            {"trace_id": "trace-2", "error_code": 404},
        ]
    }
    ok, _, meta = isolated_artifact_store.store(
        content=json.dumps(payload, ensure_ascii=False),
        content_type=ContentType.APPLICATION_JSON,
        source_tool="unit_test",
        source_call_id="call_test",
        source_trace_id="trace_test",
    )
    assert ok is True
    assert meta is not None

    executor = NativeToolExecutor()
    result = asyncio.run(
        executor.execute(
            {
                "tool_name": "artifact_reader",
                "artifact_id": meta.artifact_id,
                "mode": "jsonpath",
                "query": "$..trace_id",
            },
            session_id="sess-1",
        )
    )

    assert result["status"] == "success"
    text = str(result["result"])
    assert "[artifact_id]" in text
    assert "trace-1" in text
    assert "trace-2" in text


def test_write_file_blocks_test_poisoning():
    executor = NativeToolExecutor()
    poison_path = Path("tests/tmp_poison_guard_case.py")
    if poison_path.exists():
        poison_path.unlink()

    result = asyncio.run(
        executor.execute(
            {
                "tool_name": "write_file",
                "path": str(poison_path).replace("\\", "/"),
                "content": "def test_poisoned():\n    assert True\n",
                "mode": "overwrite",
            },
            session_id="sess-poison",
        )
    )

    assert result["status"] == "error"
    assert "Anti-Test-Poisoning blocked write" in str(result["result"])
    assert poison_path.exists() is False


def test_file_ast_skeleton_and_chunk_read():
    executor = NativeToolExecutor()
    sample_path = Path("tests/tmp_ast_sample.py")
    sample_path.write_text(
        "\n".join(
            [
                "import os",
                "from pathlib import Path",
                "",
                "class Sample:",
                "    def run(self):",
                "        return 1",
                "",
                "def helper(a, b):",
                "    return a + b",
            ]
        ),
        encoding="utf-8",
    )

    try:
        skeleton = asyncio.run(
            executor.execute(
                {"tool_name": "file_ast_skeleton", "path": str(sample_path).replace("\\", "/")},
                session_id="sess-ast",
            )
        )
        assert skeleton["status"] == "success"
        skeleton_text = str(skeleton["result"])
        assert "[symbols]" in skeleton_text
        assert "class Sample" in skeleton_text
        assert "def helper" in skeleton_text

        chunk = asyncio.run(
            executor.execute(
                {
                    "tool_name": "file_ast_chunk_read",
                    "path": str(sample_path).replace("\\", "/"),
                    "start_line": 4,
                    "end_line": 8,
                    "context_before": 1,
                    "context_after": 1,
                },
                session_id="sess-ast",
            )
        )
        assert chunk["status"] == "success"
        chunk_text = str(chunk["result"])
        assert "[requested_range] 4-8" in chunk_text
        assert ">>    4: class Sample:" in chunk_text
    finally:
        if sample_path.exists():
            sample_path.unlink()
