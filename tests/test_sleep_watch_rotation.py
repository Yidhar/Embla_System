from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from system.sleep_watch import wait_for_log_pattern


def _scratch_file(stem: str) -> Path:
    base = Path("scratch")
    base.mkdir(parents=True, exist_ok=True)
    return base / f"ws14_{stem}_{uuid.uuid4().hex}.log"


def test_wait_for_log_pattern_reopens_after_rotate():
    log_file = _scratch_file("rotate")
    rotated_file = Path(f"{log_file}.1")
    log_file.write_text("boot\n", encoding="utf-8")

    async def _scenario():
        task = asyncio.create_task(
            wait_for_log_pattern(
                log_file=log_file,
                pattern="TARGET_WAKE",
                timeout_seconds=5,
                poll_interval_seconds=0.05,
                from_end=False,
            )
        )
        await asyncio.sleep(0.2)
        if rotated_file.exists():
            rotated_file.unlink()
        log_file.replace(rotated_file)
        log_file.write_text("TARGET_WAKE\n", encoding="utf-8")
        return await task

    try:
        result = asyncio.run(_scenario())
        assert result.matched is True
        assert result.reopen_count >= 1
        assert result.reopen_reason == "inode_changed"
    finally:
        if log_file.exists():
            log_file.unlink()
        if rotated_file.exists():
            rotated_file.unlink()


def test_wait_for_log_pattern_reopens_after_truncate():
    log_file = _scratch_file("truncate")
    log_file.write_text("boot\nline\n", encoding="utf-8")

    async def _scenario():
        task = asyncio.create_task(
            wait_for_log_pattern(
                log_file=log_file,
                pattern="TARGET_WAKE",
                timeout_seconds=5,
                poll_interval_seconds=0.05,
                from_end=False,
            )
        )
        await asyncio.sleep(0.2)
        log_file.write_text("", encoding="utf-8")
        await asyncio.sleep(0.2)
        log_file.write_text("TARGET_WAKE\n", encoding="utf-8")
        return await task

    try:
        result = asyncio.run(_scenario())
        assert result.matched is True
        assert result.reopen_count >= 1
        assert result.reopen_reason == "truncated"
    finally:
        if log_file.exists():
            log_file.unlink()


def test_wait_for_log_pattern_recovers_when_file_recreated():
    log_file = _scratch_file("recreated")
    log_file.write_text("boot\n", encoding="utf-8")

    async def _scenario():
        task = asyncio.create_task(
            wait_for_log_pattern(
                log_file=log_file,
                pattern="TARGET_WAKE",
                timeout_seconds=5,
                poll_interval_seconds=0.05,
                from_end=False,
            )
        )
        await asyncio.sleep(0.2)
        log_file.unlink()
        await asyncio.sleep(0.2)
        log_file.write_text("TARGET_WAKE\n", encoding="utf-8")
        return await task

    try:
        result = asyncio.run(_scenario())
        assert result.matched is True
        assert result.reopen_count >= 1
        assert result.reopen_reason == "recreated"
    finally:
        if log_file.exists():
            log_file.unlink()
