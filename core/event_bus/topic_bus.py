"""Core topic bus facade (brainstem namespace)."""

from __future__ import annotations

from autonomous.event_log.topic_event_bus import (
    ReplayDispatchResult,
    TopicEventBus as _TopicEventBus,
    TopicSubscription,
    infer_event_topic,
)


class TopicEventBus(_TopicEventBus):
    """Brainstem namespace facade for topic-oriented event bus."""


__all__ = ["TopicEventBus", "TopicSubscription", "ReplayDispatchResult", "infer_event_topic"]

