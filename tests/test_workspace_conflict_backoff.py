"""Workspace conflict ticket/backoff tests for NGA-WS12-004."""

from __future__ import annotations

import asyncio
import hashlib
import re
from pathlib import Path

from apiserver.native_tools import NativeToolExecutor


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _extract_error_value(text: str, key: str) -> str:
    m = re.search(rf"{re.escape(key)}=([a-zA-Z0-9_./-]+)", text)
    assert m is not None, f"missing {key} in: {text}"
    return m.group(1)


def _run_conflict_apply(executor: NativeToolExecutor, target: Path, *, base_content: str, attempt: int) -> dict:
    current_content = "alpha\nbeta-concurrent\ngamma\n"
    incoming_content = "alpha\nbeta-agent\ngamma\n"
    target.write_text(current_content, encoding="utf-8")
    base_hash = _sha256(base_content)
    return asyncio.run(
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
                        "conflict_backoff": {
                            "base_ms": 100,
                            "max_ms": 220,
                            "attempt": attempt,
                            "jitter_ratio": 0.25,
                        },
                    }
                ],
            },
            session_id=f"sess-conflict-backoff-{attempt}",
        )
    )


def test_workspace_conflict_backoff_is_monotonic_and_capped():
    executor = NativeToolExecutor()
    target = Path("scratch/tmp_conflict_backoff_monotonic.txt")
    target.parent.mkdir(parents=True, exist_ok=True)
    base_content = "alpha\nbeta\ngamma\n"

    backoffs = []
    for attempt in [1, 2, 3, 4, 5]:
        result = _run_conflict_apply(executor, target, base_content=base_content, attempt=attempt)
        assert result["status"] == "error"
        text = str(result["result"])
        backoffs.append(int(_extract_error_value(text, "backoff_ms")))

    assert backoffs == sorted(backoffs)
    assert all(v <= 220 for v in backoffs)
    assert backoffs[-1] == 220


def test_workspace_conflict_ticket_is_reproducible_for_same_signature():
    executor = NativeToolExecutor()
    target = Path("scratch/tmp_conflict_ticket_stable.txt")
    target.parent.mkdir(parents=True, exist_ok=True)
    base_content = "alpha\nbeta\ngamma\n"

    result1 = _run_conflict_apply(executor, target, base_content=base_content, attempt=2)
    result2 = _run_conflict_apply(executor, target, base_content=base_content, attempt=2)

    assert result1["status"] == "error"
    assert result2["status"] == "error"
    text1 = str(result1["result"])
    text2 = str(result2["result"])
    assert _extract_error_value(text1, "conflict_ticket") == _extract_error_value(text2, "conflict_ticket")
    assert _extract_error_value(text1, "conflict_signature") == _extract_error_value(text2, "conflict_signature")


def test_workspace_txn_success_has_no_conflict_metadata():
    executor = NativeToolExecutor()
    target = Path("scratch/tmp_conflict_success_no_metadata.txt")
    target.parent.mkdir(parents=True, exist_ok=True)

    base_content = "alpha\nbeta\ngamma\n"
    target.write_text(base_content, encoding="utf-8")
    base_hash = _sha256(base_content)
    updated_content = "alpha\nbeta\ngamma-updated\n"

    result = asyncio.run(
        executor.execute(
            {
                "tool_name": "workspace_txn_apply",
                "changes": [
                    {
                        "path": str(target).replace("\\", "/"),
                        "content": updated_content,
                        "mode": "overwrite",
                        "original_file_hash": base_hash,
                        "original_content": base_content,
                        "conflict_backoff": {
                            "base_ms": 100,
                            "max_ms": 200,
                            "attempt": 3,
                        },
                    }
                ],
            },
            session_id="sess-conflict-success",
        )
    )

    assert result["status"] == "success"
    text = str(result["result"]).lower()
    assert "conflict_ticket" not in text
    assert "backoff_ms" not in text
    assert target.read_text(encoding="utf-8") == updated_content
