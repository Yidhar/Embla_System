#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from core.event_bus.event_schema import normalize_event_envelope
from core.event_bus.topic_bus import TopicEventBus, infer_event_topic, resolve_topic_db_path_from_mirror


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _partition_ym(timestamp: str) -> str:
    text = str(timestamp or "").strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        parsed = datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%Y%m")


def _safe_json_load(line: str) -> Dict[str, Any] | None:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def migrate_events_jsonl_to_db(*, source_jsonl: Path, target_db: Path) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "source_jsonl": str(source_jsonl),
        "target_db": str(target_db),
        "started_at": _utc_now_iso(),
        "line_count": 0,
        "parsed_count": 0,
        "inserted_count": 0,
        "duplicate_count": 0,
        "invalid_count": 0,
        "passed": False,
    }
    if not source_jsonl.exists():
        report["error"] = "source_jsonl_not_found"
        report["finished_at"] = _utc_now_iso()
        return report

    target_db.parent.mkdir(parents=True, exist_ok=True)
    # Ensure schema exists.
    TopicEventBus(db_path=target_db, mirror_file_path=None)

    conn = sqlite3.connect(str(target_db))
    conn.row_factory = sqlite3.Row
    raw_lines = source_jsonl.read_text(encoding="utf-8", errors="ignore").splitlines()
    report["line_count"] = len(raw_lines)

    for line in raw_lines:
        if not line.strip():
            continue
        row = _safe_json_load(line)
        if row is None:
            report["invalid_count"] = int(report["invalid_count"]) + 1
            continue
        report["parsed_count"] = int(report["parsed_count"]) + 1

        envelope = normalize_event_envelope(
            row,
            fallback_event_type=str(row.get("event_type") or "UnknownEvent"),
            fallback_timestamp=str(row.get("timestamp") or ""),
        )
        topic = str(row.get("topic") or "").strip() or infer_event_topic(
            str(envelope.get("event_type") or ""),
            dict(envelope.get("data") or {}),
        )
        envelope["topic"] = topic

        rowcount_before = conn.total_changes
        conn.execute(
            """
            INSERT OR IGNORE INTO topic_event
            (event_id, topic, event_type, source, severity, idempotency_key, timestamp, partition_ym, envelope_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(envelope.get("event_id") or ""),
                str(topic),
                str(envelope.get("event_type") or ""),
                str(envelope.get("source") or ""),
                str(envelope.get("severity") or ""),
                str(envelope.get("idempotency_key") or ""),
                str(envelope.get("timestamp") or ""),
                _partition_ym(str(envelope.get("timestamp") or "")),
                json.dumps(envelope, ensure_ascii=False),
            ),
        )
        if conn.total_changes > rowcount_before:
            report["inserted_count"] = int(report["inserted_count"]) + 1
        else:
            report["duplicate_count"] = int(report["duplicate_count"]) + 1

    conn.commit()
    conn.close()
    report["finished_at"] = _utc_now_iso()
    report["passed"] = True
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migrate logs/autonomous/events.jsonl into events_topics.db")
    parser.add_argument(
        "--source-jsonl",
        default="logs/autonomous/events.jsonl",
        help="Path to source jsonl file",
    )
    parser.add_argument(
        "--target-db",
        default="",
        help="Optional sqlite target path (default: derived from source jsonl)",
    )
    parser.add_argument(
        "--remove-source",
        action="store_true",
        help="Backup and remove source jsonl after successful migration",
    )
    parser.add_argument(
        "--backup-dir",
        default="scratch/runtime/event_migration_backups",
        help="Backup directory used when --remove-source is enabled",
    )
    parser.add_argument(
        "--output",
        default="scratch/reports/ws29_006_events_jsonl_to_db_migration.json",
        help="Migration report output path",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_jsonl = Path(args.source_jsonl).resolve()
    target_db = Path(args.target_db).resolve() if str(args.target_db).strip() else resolve_topic_db_path_from_mirror(source_jsonl)
    report = migrate_events_jsonl_to_db(source_jsonl=source_jsonl, target_db=target_db)

    if bool(args.remove_source) and bool(report.get("passed")):
        if int(report.get("invalid_count") or 0) == 0:
            backup_dir = Path(args.backup_dir).resolve()
            backup_dir.mkdir(parents=True, exist_ok=True)
            backup_path = backup_dir / f"{source_jsonl.name}.{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.bak"
            shutil.copy2(source_jsonl, backup_path)
            source_jsonl.unlink(missing_ok=True)
            report["source_removed"] = True
            report["backup_path"] = str(backup_path)
        else:
            report["source_removed"] = False
            report["source_remove_skipped_reason"] = "invalid_rows_present"

    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if bool(report.get("passed")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
