"""Tests for register_incident_consumer – production-only IncidentConsumer registration.

WS33-014: Verify that register_incident_consumer correctly wires up the
append-only JSONL incident consumer and that it filters events as expected.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.event_bus.event_store import EventStore
from core.event_bus.consumers import register_incident_consumer
from core.event_bus.topic_bus import TopicSubscription


@pytest.fixture()
def tmp_repo(tmp_path: Path) -> Path:
    """Create a minimal repo root with scratch/runtime directory."""
    (tmp_path / "scratch" / "runtime").mkdir(parents=True, exist_ok=True)
    return tmp_path


@pytest.fixture()
def event_store(tmp_path: Path) -> EventStore:
    events_file = tmp_path / "events.jsonl"
    return EventStore(file_path=events_file)


def _incident_file(repo_root: Path) -> Path:
    return repo_root / "scratch" / "runtime" / "event_bus_incidents_ws28_029.jsonl"


class TestRegisterIncidentConsumer:
    """register_incident_consumer returns a TopicSubscription and wires the handler."""

    def test_returns_topic_subscription(self, event_store: EventStore, tmp_repo: Path) -> None:
        sub = register_incident_consumer(event_store=event_store, repo_root=tmp_repo)
        assert isinstance(sub, TopicSubscription)
        assert sub.pattern == "*"
        assert sub.timeout_ms == 3_000
        assert sub.max_retries == 1

    def test_critical_event_written_to_jsonl(self, event_store: EventStore, tmp_repo: Path) -> None:
        register_incident_consumer(event_store=event_store, repo_root=tmp_repo)

        event_store.publish(
            "system.alert",
            {"reason_code": "OOM", "reason_text": "Out of memory"},
            event_type="IncidentOpened",
            source="test",
            severity="critical",
        )

        out = _incident_file(tmp_repo)
        assert out.exists(), "Incident JSONL file should have been created"
        lines = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert len(lines) == 1
        row = lines[0]
        assert row["event_type"] == "IncidentOpened"
        assert row["severity"] == "critical"
        assert "timestamp" in row
        assert "generated_at" in row

    def test_info_event_not_written(self, event_store: EventStore, tmp_repo: Path) -> None:
        register_incident_consumer(event_store=event_store, repo_root=tmp_repo)

        event_store.publish(
            "agent.shell",
            {"msg": "routine log"},
            event_type="AgentStep",
            source="test",
            severity="info",
        )

        out = _incident_file(tmp_repo)
        if out.exists():
            content = out.read_text(encoding="utf-8").strip()
            assert content == "", "Info-level non-incident events should not be recorded"

    def test_jsonl_contains_expected_fields(self, event_store: EventStore, tmp_repo: Path) -> None:
        register_incident_consumer(event_store=event_store, repo_root=tmp_repo)

        event_store.publish(
            "system.watchdog",
            {"reason_code": "CPU_HIGH", "reason_text": "CPU > 90%", "task_id": "t-42"},
            event_type="WatchdogThresholdExceeded",
            source="watchdog",
            severity="critical",
        )

        out = _incident_file(tmp_repo)
        lines = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert len(lines) == 1
        row = lines[0]
        expected_keys = {"event_type", "severity", "timestamp", "generated_at", "event_id", "topic", "reason_code"}
        assert expected_keys.issubset(row.keys()), f"Missing keys: {expected_keys - row.keys()}"
        assert row["reason_code"] == "CPU_HIGH"
        assert row["topic"] == "system.watchdog"
