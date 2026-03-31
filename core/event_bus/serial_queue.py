"""WS33-001 Serial action queue for mutually-exclusive write operations.

Provides a strict FIFO queue with a single background worker that processes
actions one at a time, ensuring serial execution of side-effecting operations
such as file writes, dependency installs, and service restarts.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class SerialAction:
    action_id: str
    actor: str
    scope: str  # "local" | "global"
    action_type: str  # "write_file" | "install_dep" | "git_branch" | "restart_service" | "other"
    requires_global_mutex: bool
    payload: Dict[str, Any]


@dataclass
class QueueTicket:
    ticket_id: str
    position: int
    status: str  # "queued" | "running" | "done" | "failed"
    result: Optional[Dict[str, Any]] = field(default=None)
    error: Optional[str] = field(default=None)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# Type alias for the optional executor callback
ActionExecutor = Callable[[SerialAction], Coroutine[Any, Any, Dict[str, Any]]]


async def _default_executor(action: SerialAction) -> Dict[str, Any]:
    """Default no-op executor that simply acknowledges the action."""
    return {"ok": True, "action_id": action.action_id, "action_type": action.action_type}


class SerialActionQueue:
    """Strict FIFO queue with a single async worker for serial execution."""

    def __init__(self, *, executor: Optional[ActionExecutor] = None) -> None:
        self._queue: asyncio.Queue[tuple[SerialAction, str]] = asyncio.Queue()
        self._tickets: Dict[str, QueueTicket] = {}
        self._worker_task: Optional[asyncio.Task[None]] = None
        self._executor: ActionExecutor = executor or _default_executor
        self._position_counter: int = 0

    async def enqueue(self, action: SerialAction) -> QueueTicket:
        """Add an action to the queue and return a tracking ticket."""
        ticket_id = f"tkt_{uuid.uuid4().hex[:16]}"
        self._position_counter += 1
        ticket = QueueTicket(
            ticket_id=ticket_id,
            position=self._position_counter,
            status="queued",
        )
        self._tickets[ticket_id] = ticket
        await self._queue.put((action, ticket_id))
        return ticket

    def get_ticket(self, ticket_id: str) -> Optional[QueueTicket]:
        """Look up a ticket by ID."""
        return self._tickets.get(str(ticket_id or ""))

    async def start_worker(self) -> None:
        """Launch the single background worker."""
        if self._worker_task is not None and not self._worker_task.done():
            return
        self._worker_task = asyncio.get_running_loop().create_task(self._worker_loop())

    async def stop_worker(self) -> None:
        """Gracefully shut down the worker (drains current item first)."""
        if self._worker_task is not None and not self._worker_task.done():
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        self._worker_task = None

    @property
    def pending_count(self) -> int:
        return self._queue.qsize()

    # ------------------------------------------------------------------
    # Internal worker
    # ------------------------------------------------------------------

    async def _worker_loop(self) -> None:
        while True:
            try:
                action, ticket_id = await self._queue.get()
            except asyncio.CancelledError:
                raise

            ticket = self._tickets.get(ticket_id)
            if ticket is None:
                self._queue.task_done()
                continue

            ticket.status = "running"
            ticket.updated_at = datetime.now(timezone.utc).isoformat()

            try:
                result = await self._executor(action)
                ticket.status = "done"
                ticket.result = result
            except asyncio.CancelledError:
                ticket.status = "failed"
                ticket.error = "cancelled"
                raise
            except Exception as exc:
                logger.exception("SerialActionQueue: executor failed for action_id=%s", action.action_id)
                ticket.status = "failed"
                ticket.error = str(exc)
            finally:
                ticket.updated_at = datetime.now(timezone.utc).isoformat()
                self._queue.task_done()


# ---- module-level singleton ----

_DEFAULT_QUEUE: Optional[SerialActionQueue] = None


def get_serial_action_queue() -> SerialActionQueue:
    """Return (and lazily create) the process-wide serial action queue."""
    global _DEFAULT_QUEUE
    if _DEFAULT_QUEUE is None:
        _DEFAULT_QUEUE = SerialActionQueue()
    return _DEFAULT_QUEUE


__all__ = [
    "ActionExecutor",
    "QueueTicket",
    "SerialAction",
    "SerialActionQueue",
    "get_serial_action_queue",
]
