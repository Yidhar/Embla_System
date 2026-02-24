"""Workspace semantic rebase tests for NGA-WS12-003."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

from apiserver.native_tools import NativeToolExecutor
from system.subagent_contract import build_contract_checksum


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_workspace_txn_apply_semantic_rebase_merges_non_overlapping_conflict():
    executor = NativeToolExecutor()
    target = Path("scratch/tmp_semantic_rebase_success.txt")
    target.parent.mkdir(parents=True, exist_ok=True)

    base_content = "alpha\nbeta\ngamma\n"
    target.write_text(base_content, encoding="utf-8")
    base_hash = _sha256(base_content)

    # Simulate concurrent writer changing a different line after caller read baseline.
    current_content = "alpha\nbeta\ngamma-concurrent\n"
    target.write_text(current_content, encoding="utf-8")

    incoming_content = "alpha-agent\nbeta\ngamma\n"
    result = asyncio.run(
        executor.execute(
            {
                "tool_name": "workspace_txn_apply",
                "changes": [
                    {
                        "path": str(target).replace("\\", "/"),
                        "content": incoming_content,
                        "mode": "overwrite",
                        "original_file_hash": base_hash,
                        "original_content": base_content,
                    }
                ],
            },
            session_id="sess-sem-rebase-ok",
        )
    )

    assert result["status"] == "success"
    result_text = str(result["result"])
    assert "[semantic_rebased_files] 1" in result_text
    assert "conflict_ticket" not in result_text
    assert "backoff_ms" not in result_text
    assert target.read_text(encoding="utf-8") == "alpha-agent\nbeta\ngamma-concurrent\n"


def test_workspace_txn_apply_semantic_rebase_fails_on_overlapping_conflict_without_pollution():
    executor = NativeToolExecutor()
    target = Path("scratch/tmp_semantic_rebase_fail.txt")
    stable = Path("scratch/tmp_semantic_rebase_rollback_guard.txt")
    target.parent.mkdir(parents=True, exist_ok=True)

    base_content = "alpha\nbeta\ngamma\n"
    target.write_text(base_content, encoding="utf-8")
    base_hash = _sha256(base_content)
    stable.write_text("stable-original\n", encoding="utf-8")

    # Concurrent writer changes the same line as incoming update.
    current_content = "alpha\nbeta-concurrent\ngamma\n"
    target.write_text(current_content, encoding="utf-8")

    incoming_content = "alpha\nbeta-agent\ngamma\n"
    contract_id = "contract-sem-rebase-rollback"
    changed_paths = sorted(
        [
            str(stable).replace("\\", "/"),
            str(target).replace("\\", "/"),
        ]
    )
    contract_checksum = build_contract_checksum(contract_id, schema={"paths": changed_paths})
    result = asyncio.run(
        executor.execute(
            {
                "tool_name": "workspace_txn_apply",
                "contract_id": contract_id,
                "contract_checksum": contract_checksum,
                "changes": [
                    {
                        "path": str(stable).replace("\\", "/"),
                        "content": "stable-updated\n",
                        "mode": "overwrite",
                    },
                    {
                        "path": str(target).replace("\\", "/"),
                        "content": incoming_content,
                        "mode": "overwrite",
                        "original_file_hash": base_hash,
                        "original_content": base_content,
                    }
                ],
            },
            session_id="sess-sem-rebase-fail",
        )
    )

    assert result["status"] == "error"
    result_text = str(result["result"]).lower()
    assert "semantic rebase failed" in result_text
    assert "conflict_ticket=" in result_text
    assert "backoff_ms=" in result_text
    assert stable.read_text(encoding="utf-8") == "stable-original\n"
    assert target.read_text(encoding="utf-8") == current_content
