"""Backward-compat import shim for event store."""

from __future__ import annotations

from core.event_bus.event_store import (
    EventStore,
    ReplayDispatchResult,
    TopicEventBus,
    TopicSubscription,
    infer_event_topic,
)

__all__ = [
    "EventStore",
    "ReplayDispatchResult",
    "TopicEventBus",
    "TopicSubscription",
    "infer_event_topic",
]

