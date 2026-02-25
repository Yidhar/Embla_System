"""
Sleep/watch helpers with safe-regex and rotate-safe reopen semantics.

WS14-007/008:
- regex complexity gate + match timeout budget
- tail -F style reopen when inode/size changes
"""

from __future__ import annotations

import asyncio
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple


@dataclass(frozen=True)
class SleepWatchResult:
    watch_id: str
    matched: bool
    reason: str
    matched_line: str = ""
    elapsed_seconds: float = 0.0
    reopen_count: int = 0
    reopen_reason: str = ""


_UNSAFE_REGEX_PATTERNS = (
    # Nested quantifiers like (a+)+ / (.*)+
    re.compile(r"\((?:[^()\\]|\\.)*[+*](?:[^()\\]|\\.)*\)\s*[+*{]"),
    # Repeated wildcard groups like (.+)+
    re.compile(r"\((?:\.\*|\.\+)\)\s*[+*{]"),
    # Backreferences are expensive and often unnecessary in log watch.
    re.compile(r"\\[1-9]"),
)


def validate_safe_regex(pattern: str, *, max_len: int = 256) -> Tuple[bool, str]:
    text = (pattern or "").strip()
    if not text:
        return False, "pattern is empty"
    if len(text) > max_len:
        return False, f"pattern too long: {len(text)} > {max_len}"

    for unsafe_re in _UNSAFE_REGEX_PATTERNS:
        if unsafe_re.search(text):
            return False, "unsafe regex pattern blocked (potential catastrophic backtracking)"

    try:
        re.compile(text)
    except re.error as exc:
        return False, f"regex compile error: {exc}"

    return True, "ok"


async def wait_for_log_pattern(
    *,
    log_file: Path,
    pattern: str,
    timeout_seconds: int = 3600,
    poll_interval_seconds: float = 0.5,
    from_end: bool = True,
    max_line_chars: int = 4000,
    regex_match_timeout_seconds: float = 0.05,
) -> SleepWatchResult:
    ok, reason = validate_safe_regex(pattern)
    if not ok:
        return SleepWatchResult(
            watch_id=f"watch_{uuid.uuid4().hex[:12]}",
            matched=False,
            reason=reason,
        )

    compiled = re.compile(pattern)
    watch_id = f"watch_{uuid.uuid4().hex[:12]}"
    started_at = time.time()
    deadline = started_at + max(1, int(timeout_seconds))
    try:
        match_budget_seconds = max(0.001, float(regex_match_timeout_seconds))
    except (TypeError, ValueError):
        match_budget_seconds = 0.05
    current_inode: Optional[int] = None
    current_position = 0
    initialized = False
    missing_since_initialized = False
    reopen_count = 0
    reopen_reason = ""

    def _record_reopen(reason: str) -> None:
        nonlocal current_position, reopen_count, reopen_reason
        current_position = 0
        reopen_count += 1
        reopen_reason = reason

    def _safe_match(line: str) -> bool:
        # Keep matching in-process: some runtime environments do not allow background
        # worker threads for asyncio.to_thread(), which can stall watcher shutdown.
        # validate_safe_regex() already blocks known catastrophic patterns.
        try:
            return bool(compiled.search(line))
        except re.error:
            return False

    while True:
        now_ts = time.time()
        if now_ts >= deadline:
            return SleepWatchResult(
                watch_id=watch_id,
                matched=False,
                reason="timeout",
                elapsed_seconds=now_ts - started_at,
                reopen_count=reopen_count,
                reopen_reason=reopen_reason,
            )

        if not log_file.exists():
            if initialized:
                missing_since_initialized = True
            await asyncio.sleep(max(0.05, poll_interval_seconds))
            continue

        try:
            stat = log_file.stat()
        except Exception:
            await asyncio.sleep(max(0.05, poll_interval_seconds))
            continue

        inode = int(getattr(stat, "st_ino", 0))
        size = int(getattr(stat, "st_size", 0))
        recreated = initialized and missing_since_initialized
        rotated = current_inode is not None and inode and inode != current_inode
        truncated = initialized and size < current_position
        if recreated:
            _record_reopen("recreated")
        elif rotated:
            _record_reopen("inode_changed")
        elif truncated:
            _record_reopen("truncated")
        missing_since_initialized = False
        current_inode = inode if inode else current_inode

        got_new_data = False
        budget_exhausted = False
        try:
            with log_file.open("r", encoding="utf-8", errors="ignore") as fh:
                if not initialized and from_end and current_position == 0:
                    fh.seek(0, 2)
                    current_position = int(fh.tell())
                else:
                    fh.seek(max(0, min(current_position, size)), 0)

                match_round_started = time.perf_counter()
                while True:
                    line = fh.readline()
                    if not line:
                        break
                    got_new_data = True
                    current_position = int(fh.tell())
                    candidate = line.rstrip("\n")[:max(64, int(max_line_chars))]
                    if _safe_match(candidate):
                        return SleepWatchResult(
                            watch_id=watch_id,
                            matched=True,
                            reason="matched",
                            matched_line=candidate,
                            elapsed_seconds=time.time() - started_at,
                            reopen_count=reopen_count,
                            reopen_reason=reopen_reason,
                        )
                    if (time.perf_counter() - match_round_started) >= match_budget_seconds:
                        budget_exhausted = True
                        break
        except Exception:
            await asyncio.sleep(max(0.05, poll_interval_seconds))
            continue
        finally:
            initialized = True

        if budget_exhausted or not got_new_data:
            await asyncio.sleep(max(0.05, poll_interval_seconds))


__all__ = ["SleepWatchResult", "validate_safe_regex", "wait_for_log_pattern"]
