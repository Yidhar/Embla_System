"""Backward-compat import shim for topic event bus."""

from __future__ import annotations

from core.event_bus.topic_bus import (
    ReplayDispatchResult,
    TopicEventBus,
    TopicSubscription,
    infer_event_topic,
)

__all__ = [
    "TopicEventBus",
    "TopicSubscription",
    "ReplayDispatchResult",
    "infer_event_topic",
]

