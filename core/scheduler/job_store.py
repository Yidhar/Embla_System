"""SQLite-backed job registry for Chronos — survives restarts."""

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


class ScheduledJobStore:
    """Persists scheduled-job metadata so the scheduler can be rebuilt on restart."""

    def __init__(self, db_path: str = "scratch/runtime/scheduled_jobs.db") -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_schema()

    # ---- schema ----

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        ddl = """
        CREATE TABLE IF NOT EXISTS scheduled_job (
            job_id      TEXT PRIMARY KEY,
            cron_expr   TEXT NOT NULL,
            func_ref    TEXT NOT NULL,
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        );
        """
        with self._lock:
            with self._connect() as conn:
                conn.executescript(ddl)
                conn.commit()

    # ---- public API ----

    def register(self, job_id: str, cron_expr: str, func_ref: str) -> None:
        """Insert or update a job registration."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO scheduled_job (job_id, cron_expr, func_ref, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(job_id) DO UPDATE SET
                        cron_expr  = excluded.cron_expr,
                        func_ref   = excluded.func_ref,
                        updated_at = excluded.updated_at
                    """,
                    (str(job_id), str(cron_expr), str(func_ref), now, now),
                )
                conn.commit()

    def list_registered(self) -> List[Dict[str, Any]]:
        """Return all registered jobs as dicts."""
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT job_id, cron_expr, func_ref, created_at, updated_at FROM scheduled_job ORDER BY job_id"
                ).fetchall()
        return [
            {
                "job_id": str(row["job_id"]),
                "cron_expr": str(row["cron_expr"]),
                "func_ref": str(row["func_ref"]),
                "created_at": str(row["created_at"]),
                "updated_at": str(row["updated_at"]),
            }
            for row in rows
        ]

    def remove(self, job_id: str) -> None:
        """Delete a job registration by id."""
        with self._lock:
            with self._connect() as conn:
                conn.execute("DELETE FROM scheduled_job WHERE job_id = ?", (str(job_id),))
                conn.commit()
