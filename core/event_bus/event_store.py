"""Core event store facade (brainstem namespace)."""

from __future__ import annotations

from autonomous.event_log.event_store import EventStore as _EventStore
from autonomous.event_log.topic_event_bus import ReplayDispatchResult, TopicSubscription, TopicEventBus, infer_event_topic


class EventStore(_EventStore):
    """Brainstem namespace facade for the durable event store."""


__all__ = [
    "EventStore",
    "ReplayDispatchResult",
    "TopicSubscription",
    "TopicEventBus",
    "infer_event_topic",
]

