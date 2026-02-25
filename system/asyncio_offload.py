"""Async helpers for running blocking callables under restricted runtimes."""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import os
import socket
import threading
from functools import partial
from typing import Any, Callable, TypeVar

_T = TypeVar("_T")
logger = logging.getLogger(__name__)

_WAKEUP_CHECK_LOCK = threading.Lock()
_WAKEUP_CHECK_RESULT: bool | None = None
_WAKEUP_CHECK_ERROR: str = ""

_FALLBACK_EXECUTOR_LOCK = threading.Lock()
_FALLBACK_EXECUTOR: concurrent.futures.ThreadPoolExecutor | None = None

_FALLBACK_WARNED_LOCK = threading.Lock()
_FALLBACK_WARNED = False


def _ensure_loopback_no_proxy() -> None:
    hosts: list[str] = []
    existing = os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or ""
    for part in existing.split(","):
        item = part.strip()
        if item:
            hosts.append(item)

    changed = False
    for required in ("localhost", "127.0.0.1", "::1"):
        if required not in hosts:
            hosts.append(required)
            changed = True

    if not hosts:
        return
    if not changed and os.environ.get("NO_PROXY") and os.environ.get("no_proxy"):
        return

    value = ",".join(hosts)
    os.environ["NO_PROXY"] = value
    os.environ["no_proxy"] = value


_ensure_loopback_no_proxy()


def _probe_threadsafe_wakeup() -> tuple[bool, str]:
    try:
        ssock, csock = socket.socketpair()
    except OSError as exc:
        return False, f"socketpair_failed:{exc!r}"

    try:
        try:
            csock.send(b"\0")
        except OSError as exc:
            return False, f"socketpair_send_failed:{exc!r}"
        return True, ""
    finally:
        try:
            ssock.close()
        except OSError:
            pass
        try:
            csock.close()
        except OSError:
            pass


def is_asyncio_thread_wakeup_available() -> bool:
    """Check whether call_soon_threadsafe wakeups are usable in this runtime."""
    global _WAKEUP_CHECK_RESULT, _WAKEUP_CHECK_ERROR
    with _WAKEUP_CHECK_LOCK:
        if _WAKEUP_CHECK_RESULT is None:
            ok, error = _probe_threadsafe_wakeup()
            _WAKEUP_CHECK_RESULT = ok
            _WAKEUP_CHECK_ERROR = error
        return bool(_WAKEUP_CHECK_RESULT)


def _fallback_executor() -> concurrent.futures.ThreadPoolExecutor:
    global _FALLBACK_EXECUTOR
    with _FALLBACK_EXECUTOR_LOCK:
        if _FALLBACK_EXECUTOR is None:
            max_workers = min(32, (os.cpu_count() or 1) + 4)
            _FALLBACK_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
                max_workers=max_workers,
                thread_name_prefix="naga-offload",
            )
        return _FALLBACK_EXECUTOR


def _warn_fallback_once() -> None:
    global _FALLBACK_WARNED
    with _FALLBACK_WARNED_LOCK:
        if _FALLBACK_WARNED:
            return
        _FALLBACK_WARNED = True

    detail = _WAKEUP_CHECK_ERROR or "unknown_error"
    logger.warning(
        "[asyncio_offload] call_soon_threadsafe wakeups are unavailable (%s); using polling fallback executor.",
        detail,
    )


async def offload_blocking(
    func: Callable[..., _T],
    /,
    *args: Any,
    timeout: float | None = None,
    poll_interval: float = 0.01,
    **kwargs: Any,
) -> _T:
    """Run a blocking callable without relying on fragile default-executor shutdown paths."""
    if timeout is not None and timeout < 0:
        raise ValueError("timeout must be >= 0")
    if poll_interval <= 0:
        raise ValueError("poll_interval must be > 0")

    if is_asyncio_thread_wakeup_available():
        worker_coro = asyncio.to_thread(func, *args, **kwargs)
        if timeout is None:
            return await worker_coro
        return await asyncio.wait_for(worker_coro, timeout=timeout)

    _warn_fallback_once()

    call = partial(func, *args, **kwargs) if kwargs else partial(func, *args)
    future = _fallback_executor().submit(call)
    loop = asyncio.get_running_loop()
    deadline = None if timeout is None else loop.time() + timeout

    try:
        while True:
            if future.done():
                return future.result()
            if deadline is not None and loop.time() >= deadline:
                future.cancel()
                raise asyncio.TimeoutError
            await asyncio.sleep(poll_interval)
    except asyncio.CancelledError:
        future.cancel()
        raise
