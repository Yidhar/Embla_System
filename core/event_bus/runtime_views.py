"""Canonical event-bus runtime views backed by the topic-event SQLite store.

These helpers provide read-side summaries directly from `topic_event`, which is
the authoritative event source in the current architecture. Historical
materialized consumer outputs remain optional compatibility fallbacks, but they
are not the primary source of truth.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from .topic_bus import resolve_topic_db_path_from_mirror

_ERROR_SEVERITIES = {"error", "critical", "fatal"}
_WARNING_SEVERITIES = {"warn", "warning"}


def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_topic_event_posture_summary(project_root: Path) -> Dict[str, Any]:
    root = Path(project_root).resolve()
    mirror_path = root / "logs" / "autonomous" / "events.jsonl"
    db_path = resolve_topic_db_path_from_mirror(mirror_path)
    summary: Dict[str, Any] = {
        "status": "unknown",
        "reason_code": "TOPIC_EVENT_DB_MISSING",
        "reason_text": "Topic event database file is missing.",
        "project_root": str(root).replace("\\", "/"),
        "mirror_path": str(mirror_path).replace("\\", "/"),
        "db_path": str(db_path).replace("\\", "/"),
        "exists": bool(db_path.exists()),
        "generated_at": _utc_iso_now(),
        "total_events": 0,
        "severity_counts": {},
        "warning_events": 0,
        "error_events": 0,
        "last_event_id": "",
        "last_event_type": "",
        "last_topic": "",
        "last_severity": "",
        "last_event_timestamp": "",
    }
    if not db_path.exists():
        return summary

    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        total_row = conn.execute("SELECT COUNT(1) AS total_rows FROM topic_event").fetchone()
        latest_row = conn.execute(
            """
            SELECT event_id, event_type, topic, severity, timestamp
            FROM topic_event
            ORDER BY seq DESC
            LIMIT 1
            """
        ).fetchone()
        severity_rows = conn.execute(
            """
            SELECT severity, COUNT(1) AS row_count
            FROM topic_event
            GROUP BY severity
            """
        ).fetchall()
    except Exception as exc:
        summary["reason_code"] = "TOPIC_EVENT_DB_QUERY_FAILED"
        summary["reason_text"] = str(exc)
        return summary
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    severity_counts = {
        str(row["severity"] or "").strip().lower(): int(row["row_count"] or 0)
        for row in severity_rows
    }
    summary["severity_counts"] = severity_counts
    summary["warning_events"] = sum(
        int(count or 0)
        for severity, count in severity_counts.items()
        if severity in _WARNING_SEVERITIES
    )
    summary["error_events"] = sum(
        int(count or 0)
        for severity, count in severity_counts.items()
        if severity in _ERROR_SEVERITIES
    )
    summary["total_events"] = int(total_row["total_rows"] or 0) if total_row is not None else 0
    if latest_row is not None:
        summary["last_event_id"] = str(latest_row["event_id"] or "")
        summary["last_event_type"] = str(latest_row["event_type"] or "")
        summary["last_topic"] = str(latest_row["topic"] or "")
        summary["last_severity"] = str(latest_row["severity"] or "")
        summary["last_event_timestamp"] = str(latest_row["timestamp"] or "")
    summary["status"] = "ok"
    summary["reason_code"] = ""
    summary["reason_text"] = ""
    return summary


def build_runtime_posture_summary(*, repo_root: Path, events_limit: int = 200) -> Dict[str, Any]:
    """Minimal aggregation view for shell_tools and other lightweight callers.

    Reads from the canonical SQLite topic_event store (same DB that
    ``apiserver/routes_ops.py`` uses) and returns a flat summary dict.
    """
    root = Path(repo_root).resolve()
    mirror_path = root / "logs" / "autonomous" / "events.jsonl"
    db_path = resolve_topic_db_path_from_mirror(mirror_path)

    fallback: Dict[str, Any] = {
        "total_events": 0,
        "severity_counts": {},
        "last_event_type": "",
        "last_severity": "",
        "last_event_at": "",
        "source": str(db_path),
    }

    if not db_path.exists():
        return fallback

    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

        total_row = conn.execute("SELECT COUNT(1) AS cnt FROM topic_event").fetchone()
        latest_row = conn.execute(
            """
            SELECT event_type, severity, timestamp
            FROM topic_event
            ORDER BY seq DESC
            LIMIT 1
            """,
        ).fetchone()
        severity_rows = conn.execute(
            """
            SELECT severity, COUNT(1) AS cnt
            FROM topic_event
            GROUP BY severity
            """,
        ).fetchall()
    except Exception:
        return fallback
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    severity_counts: Dict[str, int] = {
        str(row["severity"] or "").strip().lower(): int(row["cnt"] or 0)
        for row in severity_rows
    }
    result: Dict[str, Any] = {
        "total_events": int(total_row["cnt"] or 0) if total_row else 0,
        "severity_counts": severity_counts,
        "last_event_type": str(latest_row["event_type"] or "") if latest_row else "",
        "last_severity": str(latest_row["severity"] or "") if latest_row else "",
        "last_event_at": str(latest_row["timestamp"] or "") if latest_row else "",
        "source": str(db_path),
    }
    return result


__all__ = [
    "build_runtime_posture_summary",
    "build_topic_event_posture_summary",
]
