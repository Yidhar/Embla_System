"""Native tools runtime hardening tests (WS13/WS14 path)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from apiserver.native_tools import NativeToolExecutor


def test_workspace_txn_apply_rolls_back_on_invalid_change():
    executor = NativeToolExecutor()
    a_path = Path("scratch/tmp_txn_a.txt")
    b_path = Path("scratch/tmp_txn_b.txt")
    a_path.parent.mkdir(parents=True, exist_ok=True)
    a_path.write_text("A_ORIGINAL", encoding="utf-8")
    b_path.write_text("B_ORIGINAL", encoding="utf-8")

    result = asyncio.run(
        executor.execute(
            {
                "tool_name": "workspace_txn_apply",
                "contract_id": "contract_txn_001",
                "changes": [
                    {"path": str(a_path).replace("\\", "/"), "content": "A_NEW", "mode": "overwrite"},
                    {"path": str(b_path).replace("\\", "/"), "content": "B_NEW", "mode": "invalid_mode"},
                ],
            },
            session_id="sess-txn-1",
        )
    )

    assert result["status"] == "error"
    assert "workspace transaction failed" in str(result["result"]).lower()
    assert a_path.read_text(encoding="utf-8") == "A_ORIGINAL"
    assert b_path.read_text(encoding="utf-8") == "B_ORIGINAL"


def test_workspace_txn_apply_requires_contract_for_parallel_changes():
    executor = NativeToolExecutor()
    a_path = Path("scratch/tmp_txn_contract_a.txt")
    b_path = Path("scratch/tmp_txn_contract_b.txt")
    a_path.parent.mkdir(parents=True, exist_ok=True)

    result = asyncio.run(
        executor.execute(
            {
                "tool_name": "workspace_txn_apply",
                "changes": [
                    {"path": str(a_path).replace("\\", "/"), "content": "A", "mode": "overwrite"},
                    {"path": str(b_path).replace("\\", "/"), "content": "B", "mode": "overwrite"},
                ],
            },
            session_id="sess-txn-2",
        )
    )
    assert result["status"] == "error"
    assert "contract gate blocked" in str(result["result"]).lower()


def test_sleep_and_watch_blocks_redos_pattern():
    executor = NativeToolExecutor()
    log_file = Path("scratch/tmp_watch_redos.log")
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.write_text("boot\n", encoding="utf-8")

    result = asyncio.run(
        executor.execute(
            {
                "tool_name": "sleep_and_watch",
                "log_file": str(log_file).replace("\\", "/"),
                "regex": "(a+)+$",
                "timeout_seconds": 1,
            },
            session_id="sess-watch-redos",
        )
    )
    assert result["status"] == "success"
    assert "unsafe regex pattern blocked" in str(result["result"]).lower()


def test_sleep_and_watch_handles_log_rotate():
    executor = NativeToolExecutor()
    log_file = Path("scratch/tmp_watch_rotate.log")
    rotated_file = Path("scratch/tmp_watch_rotate.log.1")
    log_file.parent.mkdir(parents=True, exist_ok=True)
    if rotated_file.exists():
        rotated_file.unlink()
    log_file.write_text("boot\n", encoding="utf-8")

    async def _scenario():
        task = asyncio.create_task(
            executor.execute(
                {
                    "tool_name": "sleep_and_watch",
                    "log_file": str(log_file).replace("\\", "/"),
                    "pattern": "TARGET_WAKE",
                    "timeout_seconds": 5,
                    "poll_interval_seconds": 0.1,
                    "from_end": False,
                },
                session_id="sess-watch-rotate",
            )
        )
        await asyncio.sleep(0.3)
        log_file.replace(rotated_file)
        log_file.write_text("new log\nTARGET_WAKE reached\n", encoding="utf-8")
        return await task

    result = asyncio.run(_scenario())
    assert result["status"] == "success"
    assert "[matched] True" in str(result["result"])


def test_killswitch_plan_requires_oob_allowlist():
    executor = NativeToolExecutor()
    result = asyncio.run(
        executor.execute(
            {
                "tool_name": "killswitch_plan",
                "mode": "freeze",
            },
            session_id="sess-ks-1",
        )
    )
    assert result["status"] == "error"
    assert "oob_allowlist" in str(result["result"]).lower()


def test_killswitch_plan_generates_oob_marker():
    executor = NativeToolExecutor()
    result = asyncio.run(
        executor.execute(
            {
                "tool_name": "killswitch_plan",
                "mode": "freeze",
                "oob_allowlist": ["10.0.0.0/24", "198.51.100.10/32"],
            },
            session_id="sess-ks-2",
        )
    )
    assert result["status"] == "success"
    text = str(result["result"])
    assert "OOB_ALLOWLIST_ENFORCED" in text
    assert "10.0.0.0/24" in text
