from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from autonomous.event_log import AlertEventProducer, CronEventProducer, EventStore


def _make_case_root(prefix: str) -> Path:
    root = Path("scratch") / prefix / uuid.uuid4().hex[:12]
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_case_root(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


def test_cron_event_producer_publishes_due_events_into_topic_bus_ws25_002() -> None:
    case_root = _make_case_root("test_cron_alert_producer_ws25_002")
    try:
        store = EventStore(file_path=case_root / "events.jsonl")
        producer = CronEventProducer(event_store=store, source="unit-cron")
        producer.add_schedule(
            schedule_id="cron-15s",
            interval_seconds=15,
            topic="cron.healthcheck",
            event_type="CronScheduleTriggered",
            payload={"job": "healthcheck"},
            run_immediately=True,
            now_ts=1000.0,
        )

        first = producer.run_due(now_ts=1000.0)
        second = producer.run_due(now_ts=1005.0)
        third = producer.run_due(now_ts=1016.0)

        assert len(first) == 1
        assert second == []
        assert len(third) == 1

        cron_rows = store.replay_by_topic(topic_pattern="cron.*", limit=20)
        assert len(cron_rows) == 2
        assert all(str(item.get("topic") or "").startswith("cron.") for item in cron_rows)
        assert all(str(item.get("event_type") or "") == "CronScheduleTriggered" for item in cron_rows)
    finally:
        _cleanup_case_root(case_root)


def test_alert_event_producer_dedupes_and_persists_alert_topic_ws25_002() -> None:
    case_root = _make_case_root("test_cron_alert_producer_ws25_002")
    try:
        store = EventStore(file_path=case_root / "events.jsonl")
        producer = AlertEventProducer(
            event_store=store,
            source="unit-alert",
            dedupe_window_seconds=30,
        )

        first = producer.emit_alert(
            alert_key="watchdog-overload",
            severity="critical",
            payload={"cpu_percent": 97.0},
            topic="alert.watchdog",
            event_type="AlertRaised",
            now_ts=1000.0,
        )
        second = producer.emit_alert(
            alert_key="watchdog-overload",
            severity="critical",
            payload={"cpu_percent": 99.0},
            topic="alert.watchdog",
            event_type="AlertRaised",
            now_ts=1010.0,
        )
        third = producer.emit_alert(
            alert_key="watchdog-overload",
            severity="critical",
            payload={"cpu_percent": 99.0},
            topic="alert.watchdog",
            event_type="AlertRaised",
            now_ts=1035.0,
        )

        assert first
        assert second == ""
        assert third

        alert_rows = store.replay_by_topic(topic_pattern="alert.*", limit=20)
        assert len(alert_rows) == 2
        assert all(str(item.get("topic") or "").startswith("alert.") for item in alert_rows)
        assert all(str(item.get("event_type") or "") == "AlertRaised" for item in alert_rows)
    finally:
        _cleanup_case_root(case_root)
