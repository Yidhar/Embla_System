from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path

import system.sleep_watch as sleep_watch_module
from system.sleep_watch import wait_for_log_pattern


def _scratch_file(stem: str) -> Path:
    base = Path("scratch")
    base.mkdir(parents=True, exist_ok=True)
    return base / f"ws17_{stem}_{uuid.uuid4().hex}.log"


def _cleanup_paths(*paths: Path) -> None:
    for path in paths:
        if path.exists():
            path.unlink()


def _install_slow_regex(monkeypatch, *, pattern: str, sleep_seconds: float) -> None:
    real_compile = sleep_watch_module.re.compile

    class _SlowRegex:
        def search(self, _line: str):
            time.sleep(sleep_seconds)
            return None

    def _fake_compile(value: str, *args, **kwargs):
        if value == pattern:
            return _SlowRegex()
        return real_compile(value, *args, **kwargs)

    monkeypatch.setattr(sleep_watch_module.re, "compile", _fake_compile)


def test_wait_for_log_pattern_redos_like_match_returns_timeout(monkeypatch):
    log_file = _scratch_file("redos_timeout")
    pattern = "CHAOS_REDOS_SLOW_PATTERN"
    log_file.write_text("start line\n", encoding="utf-8")
    _install_slow_regex(monkeypatch, pattern=pattern, sleep_seconds=0.25)

    started = time.perf_counter()
    try:
        result = asyncio.run(
            wait_for_log_pattern(
                log_file=log_file,
                pattern=pattern,
                timeout_seconds=1,
                poll_interval_seconds=0.05,
                from_end=False,
                regex_match_timeout_seconds=0.01,
            )
        )
    finally:
        _cleanup_paths(log_file)
    elapsed = time.perf_counter() - started

    assert result.matched is False
    assert result.reason == "timeout"
    assert elapsed < 2.5


def test_wait_for_log_pattern_reopens_after_multi_round_rotate_truncate():
    log_file = _scratch_file("multi_rotate_truncate")
    rotated_file_1 = Path(f"{log_file}.1")
    rotated_file_2 = Path(f"{log_file}.2")
    _cleanup_paths(rotated_file_1, rotated_file_2)
    log_file.write_text("boot\n", encoding="utf-8")

    async def _scenario():
        task = asyncio.create_task(
            wait_for_log_pattern(
                log_file=log_file,
                pattern="TARGET_WAKE",
                timeout_seconds=6,
                poll_interval_seconds=0.05,
                from_end=False,
            )
        )
        await asyncio.sleep(0.2)

        log_file.replace(rotated_file_1)
        log_file.write_text("after rotate 1\n", encoding="utf-8")
        await asyncio.sleep(0.2)

        log_file.write_text("", encoding="utf-8")
        await asyncio.sleep(0.2)

        log_file.replace(rotated_file_2)
        log_file.write_text("after rotate 2\nTARGET_WAKE\n", encoding="utf-8")
        return await task

    try:
        result = asyncio.run(_scenario())
        assert result.matched is True
        assert result.reopen_count >= 2
        assert result.reopen_reason in {"inode_changed", "truncated", "recreated"}
    finally:
        _cleanup_paths(log_file, rotated_file_1, rotated_file_2)


def test_wait_for_log_pattern_regex_match_timeout_budget_limits_blocking(monkeypatch):
    log_file = _scratch_file("match_budget")
    pattern = "CHAOS_BUDGET_SLOW_PATTERN"
    log_file.write_text("".join(f"line-{idx}\n" for idx in range(12)), encoding="utf-8")
    _install_slow_regex(monkeypatch, pattern=pattern, sleep_seconds=0.2)

    async def _run_once(match_budget: float):
        started = time.perf_counter()
        result = await wait_for_log_pattern(
            log_file=log_file,
            pattern=pattern,
            timeout_seconds=1,
            poll_interval_seconds=0.05,
            from_end=False,
            regex_match_timeout_seconds=match_budget,
        )
        return result, time.perf_counter() - started

    try:
        slow_result, slow_elapsed = asyncio.run(_run_once(0.3))
        fast_result, fast_elapsed = asyncio.run(_run_once(0.01))
    finally:
        _cleanup_paths(log_file)

    assert slow_result.reason == "timeout"
    assert fast_result.reason == "timeout"
    assert fast_elapsed < slow_elapsed
    assert (slow_elapsed - fast_elapsed) >= 0.25
    assert fast_elapsed < 1.8
