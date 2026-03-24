"""WS33-001 DLQ auto-retry daemon for the TopicEventBus dead-letter queue.

Polls the ``dead_letter_event`` table at a configurable interval and retries
eligible entries with exponential back-off.  Successful retries are removed
from the DLQ; failures increment ``retry_count`` and push ``next_retry_at``
into the future.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from core.event_bus.topic_bus import TopicEventBus

logger = logging.getLogger(__name__)


class DLQAutoRetryDaemon:
    """Background asyncio task that periodically retries dead-letter events."""

    def __init__(
        self,
        topic_bus: TopicEventBus,
        *,
        interval_seconds: float = 60.0,
        max_retries: int = 5,
        backoff_base: float = 2.0,
    ) -> None:
        self._bus = topic_bus
        self._interval = max(1.0, float(interval_seconds))
        self._max_retries = max(1, int(max_retries))
        self._backoff_base = max(1.0, float(backoff_base))
        self._task: Optional[asyncio.Task[None]] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the retry polling loop as an asyncio task."""
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.get_running_loop().create_task(self._retry_loop())

    async def stop(self) -> None:
        """Cancel the polling task."""
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

    # ------------------------------------------------------------------
    # Core loop
    # ------------------------------------------------------------------

    async def _retry_loop(self) -> None:
        """Poll dead_letter_event table, retry eligible items with exponential backoff."""
        while True:
            try:
                await self._process_eligible_entries()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("DLQAutoRetryDaemon: unexpected error in retry loop")
            await asyncio.sleep(self._interval)

    async def _process_eligible_entries(self) -> None:
        entries = self._fetch_eligible()
        for entry in entries:
            dlq_id = int(entry.get("dlq_id") or 0)
            event_id = str(entry.get("event_id") or "")
            retry_count = int(entry.get("retry_count") or 0)
            if not event_id:
                continue
            try:
                success = self._bus.retry_dead_letter(event_id)
            except Exception:
                logger.exception("DLQAutoRetryDaemon: error retrying event_id=%s", event_id)
                success = False

            if success:
                self._delete_entry(dlq_id)
            else:
                self._bump_retry(dlq_id, retry_count)

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------

    def _fetch_eligible(self) -> List[Dict[str, Any]]:
        """Return DLQ entries that have not exceeded max_retries and whose
        ``next_retry_at`` is in the past (or empty / unset)."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._bus._lock:
            with self._bus._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT dlq_id, event_id, retry_count, next_retry_at
                    FROM dead_letter_event
                    WHERE retry_count < ?
                      AND (next_retry_at = '' OR next_retry_at IS NULL OR next_retry_at <= ?)
                    ORDER BY dlq_id ASC
                    """,
                    (self._max_retries, now_iso),
                ).fetchall()
        return [
            {
                "dlq_id": int(row["dlq_id"]),
                "event_id": str(row["event_id"] or ""),
                "retry_count": int(row["retry_count"] or 0),
                "next_retry_at": str(row["next_retry_at"] or ""),
            }
            for row in rows
        ]

    def _delete_entry(self, dlq_id: int) -> None:
        with self._bus._lock:
            with self._bus._connect() as conn:
                conn.execute("DELETE FROM dead_letter_event WHERE dlq_id = ?", (dlq_id,))
                conn.commit()

    def _bump_retry(self, dlq_id: int, current_retry_count: int) -> None:
        new_count = current_retry_count + 1
        delay_seconds = self._backoff_base ** new_count
        next_retry = (datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)).isoformat()
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._bus._lock:
            with self._bus._connect() as conn:
                conn.execute(
                    """
                    UPDATE dead_letter_event
                    SET retry_count = ?, next_retry_at = ?, updated_at = ?
                    WHERE dlq_id = ?
                    """,
                    (new_count, next_retry, now_iso, dlq_id),
                )
                conn.commit()


__all__ = ["DLQAutoRetryDaemon"]
