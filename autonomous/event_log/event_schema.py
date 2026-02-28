"""Backward-compat import shim for event schema helpers."""

from __future__ import annotations

from core.event_bus.event_schema import (
    DEFAULT_EVENT_SOURCE,
    EVENT_SCHEMA_VERSION,
    build_event_envelope,
    is_event_envelope,
    normalize_event_envelope,
)

__all__ = [
    "EVENT_SCHEMA_VERSION",
    "DEFAULT_EVENT_SOURCE",
    "is_event_envelope",
    "build_event_envelope",
    "normalize_event_envelope",
]

