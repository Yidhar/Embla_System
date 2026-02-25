"""
WS11-003 integration coverage for native run_cmd structured artifact envelope.
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
from pathlib import Path

from apiserver.native_tools import NativeToolExecutor
import system.artifact_store as artifact_store_module
from system.artifact_store import ArtifactStore, ArtifactStoreConfig
from system.native_executor import CommandResult


def _build_large_json_payload() -> str:
    records = []
    for idx in range(420):
        records.append(
            {
                "trace_id": f"trace-{idx:04d}",
                "error_code": f"E{500 + (idx % 10)}",
                "message": "connection timeout while syncing workspace transaction state",
            }
        )
    payload = {"records": records}
    raw = json.dumps(payload, ensure_ascii=False)
    assert len(raw) > 8000
    return raw


def test_run_cmd_structured_stdout_packs_artifact_envelope(monkeypatch):
    artifact_root = Path("scratch/ws11_003_artifacts")
    shutil.rmtree(artifact_root, ignore_errors=True)

    try:
        store = ArtifactStore(
            ArtifactStoreConfig(
                artifact_root=artifact_root,
                max_total_size_mb=64,
                max_single_artifact_mb=16,
                max_artifact_count=256,
            )
        )
        monkeypatch.setattr(artifact_store_module, "_artifact_store", store)

        executor = NativeToolExecutor()
        stdout_payload = _build_large_json_payload()

        async def fake_execute_shell(*_args, **_kwargs):
            return CommandResult(returncode=0, stdout=stdout_payload, stderr="")

        monkeypatch.setattr(executor.executor, "execute_shell", fake_execute_shell)

        result = asyncio.run(
            executor.execute(
                {
                    "tool_name": "run_cmd",
                    "command": "echo synthetic-json",
                    "_tool_call_id": "call_ws11_003",
                    "_trace_id": "trace_ws11_003",
                },
                session_id="sess_ws11_003",
            )
        )

        assert result["status"] == "success"
        text = str(result["result"])
        assert "[content_type] application/json" in text
        assert "[forensic_artifact_ref] artifact_" in text
        assert "[raw_result_ref] artifact_" in text
        assert "[fetch_hints]" in text
        assert "[critical_evidence]" in text
        assert "jsonpath:$..error_code" in text
        assert "trace-" in text
        assert "E50" in text
        assert "[display_preview]" in text

        match = re.search(r"\[raw_result_ref\]\s+(artifact_[a-z0-9]+)", text)
        assert match is not None
        artifact_id = match.group(1)

        ok, _, content = store.retrieve(artifact_id)
        assert ok is True
        data = json.loads(content)
        assert data["records"][0]["trace_id"] == "trace-0000"
        assert data["records"][0]["error_code"].startswith("E")
    finally:
        shutil.rmtree(artifact_root, ignore_errors=True)
