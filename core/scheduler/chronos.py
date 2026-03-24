"""Chronos — cron and interval scheduling engine backed by APScheduler."""

import logging
from typing import Any, Callable, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)


class ChronosScheduler:
    """Thin wrapper around APScheduler with event-bus integration."""

    def __init__(self, *, event_emitter: Any = None) -> None:
        self._scheduler = BackgroundScheduler(daemon=True)
        self._event_emitter = event_emitter
        self._started = False

    # ---- lifecycle ----

    def start(self) -> None:
        if not self._started:
            self._scheduler.start()
            self._started = True
            logger.info("ChronosScheduler started")

    def shutdown(self) -> None:
        if self._started:
            self._scheduler.shutdown(wait=False)
            self._started = False
            logger.info("ChronosScheduler shut down")

    @property
    def is_running(self) -> bool:
        return self._started

    # ---- job management ----

    def add_cron_job(self, job_id: str, func: Callable, *, cron_expr: str, **kwargs: Any) -> str:
        """Add a cron-triggered job.

        *cron_expr* follows the standard 5-field format:
        ``minute hour day month day_of_week``
        """
        parts = cron_expr.strip().split()
        if len(parts) != 5:
            raise ValueError(f"cron_expr must have exactly 5 fields, got {len(parts)}: {cron_expr!r}")
        trigger = CronTrigger(
            minute=parts[0],
            hour=parts[1],
            day=parts[2],
            month=parts[3],
            day_of_week=parts[4],
        )
        self._scheduler.add_job(self._wrap(job_id, func), trigger, id=job_id, replace_existing=True, **kwargs)
        logger.debug("Cron job added: %s (%s)", job_id, cron_expr)
        return job_id

    def add_interval_job(self, job_id: str, func: Callable, *, seconds: float, **kwargs: Any) -> str:
        """Add an interval-triggered job that fires every *seconds* seconds."""
        trigger = IntervalTrigger(seconds=seconds)
        self._scheduler.add_job(self._wrap(job_id, func), trigger, id=job_id, replace_existing=True, **kwargs)
        logger.debug("Interval job added: %s (every %.1fs)", job_id, seconds)
        return job_id

    def remove_job(self, job_id: str) -> None:
        try:
            self._scheduler.remove_job(job_id)
            logger.debug("Job removed: %s", job_id)
        except Exception:
            pass

    def list_jobs(self) -> list:
        return [{"id": j.id, "next_run": str(j.next_run_time)} for j in self._scheduler.get_jobs()]

    # ---- internal helpers ----

    def _wrap(self, job_id: str, func: Callable) -> Callable:
        """Return a wrapper that emits events on completion or failure."""

        def wrapper() -> Any:
            try:
                result = func()
                if self._event_emitter is not None:
                    self._event_emitter.emit("CronJobCompleted", {"job_id": job_id, "status": "success"})
                return result
            except Exception as exc:
                if self._event_emitter is not None:
                    self._event_emitter.emit("CronJobFailed", {"job_id": job_id, "error": str(exc)})
                raise

        return wrapper


# ---- module-level singleton ----

_DEFAULT_SCHEDULER: Optional[ChronosScheduler] = None


def get_default_scheduler() -> ChronosScheduler:
    """Return (and lazily create) the process-wide default scheduler."""
    global _DEFAULT_SCHEDULER
    if _DEFAULT_SCHEDULER is None:
        _DEFAULT_SCHEDULER = ChronosScheduler()
    return _DEFAULT_SCHEDULER
