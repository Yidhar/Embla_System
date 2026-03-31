import asyncio
import threading
import time

import pytest

from system import asyncio_offload


def test_offload_blocking_prefers_asyncio_to_thread_when_wakeup_available(monkeypatch) -> None:
    monkeypatch.setattr(asyncio_offload, "is_asyncio_thread_wakeup_available", lambda: True)
    called = {"count": 0}

    async def _fake_to_thread(func, *args, **kwargs):
        called["count"] += 1
        return func(*args, **kwargs)

    monkeypatch.setattr(asyncio_offload.asyncio, "to_thread", _fake_to_thread)

    async def _run() -> int:
        return await asyncio_offload.offload_blocking(lambda x: x + 1, 41)

    assert asyncio.run(_run()) == 42
    assert called["count"] == 1


def test_offload_blocking_polling_fallback_runs_in_worker_thread(monkeypatch) -> None:
    monkeypatch.setattr(asyncio_offload, "is_asyncio_thread_wakeup_available", lambda: False)

    async def _run() -> tuple[int, int]:
        loop_thread_id = threading.get_ident()
        worker_thread_id = await asyncio_offload.offload_blocking(threading.get_ident)
        return loop_thread_id, worker_thread_id

    loop_thread_id, worker_thread_id = asyncio.run(_run())
    assert loop_thread_id != worker_thread_id


def test_offload_blocking_polling_fallback_honors_timeout(monkeypatch) -> None:
    monkeypatch.setattr(asyncio_offload, "is_asyncio_thread_wakeup_available", lambda: False)

    async def _run() -> None:
        with pytest.raises(asyncio.TimeoutError):
            await asyncio_offload.offload_blocking(
                time.sleep,
                0.2,
                timeout=0.05,
                poll_interval=0.01,
            )

    asyncio.run(_run())


def test_probe_threadsafe_wakeup_reports_permission_error(monkeypatch) -> None:
    class _FakeSocket:
        def __init__(self, *, fail_send: bool = False) -> None:
            self._fail_send = fail_send

        def send(self, _data: bytes) -> int:
            if self._fail_send:
                raise PermissionError(1, "Operation not permitted")
            return 1

        def close(self) -> None:
            return None

    monkeypatch.setattr(
        asyncio_offload.socket,
        "socketpair",
        lambda: (_FakeSocket(), _FakeSocket(fail_send=True)),
    )

    ok, error = asyncio_offload._probe_threadsafe_wakeup()
    assert ok is False
    assert "PermissionError" in error
