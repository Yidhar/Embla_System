"""
Regression tests for NGA-WS11-004 artifact quota and lifecycle policy.
"""

from __future__ import annotations

import shutil
import time
import uuid
from pathlib import Path

from system.artifact_store import ArtifactStore, ArtifactStoreConfig, ContentType


def _make_store(name: str, **config_overrides: object) -> tuple[ArtifactStore, Path]:
    root = Path("scratch") / "test_artifact_store" / f"{name}_{uuid.uuid4().hex[:8]}"
    root.mkdir(parents=True, exist_ok=True)

    config = ArtifactStoreConfig(
        artifact_root=root,
        max_total_size_mb=1,
        max_single_artifact_mb=1,
        max_artifact_count=100,
        default_ttl_seconds=120,
        low_priority_ttl_seconds=30,
        high_priority_ttl_seconds=600,
        high_watermark_ratio=0.85,
        low_watermark_ratio=0.70,
    )

    for key, value in config_overrides.items():
        setattr(config, key, value)

    return ArtifactStore(config), root


def _cleanup(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


def _text_kb(kb: int) -> str:
    return "x" * (kb * 1024)


def test_priority_normalization_and_ttl_selection() -> None:
    store, root = _make_store("priority_ttl")
    try:
        initial_metrics = store.get_metrics_snapshot()
        assert initial_metrics["artifact_count"] == 0
        assert initial_metrics["store_attempt"] == 0
        assert initial_metrics["store_success"] == 0
        assert initial_metrics["quota_reject"] == 0
        assert initial_metrics["cleanup_deleted"] == 0
        assert initial_metrics["retrieve_hit"] == 0
        assert initial_metrics["retrieve_miss"] == 0

        ok, _, low_meta = store.store(
            content="low",
            content_type=ContentType.TEXT_PLAIN,
            priority="LOW",
        )
        assert ok is True
        assert low_meta is not None
        assert low_meta.priority == "low"
        low_ttl = (low_meta.expires_at or 0) - low_meta.created_at
        assert 29 <= low_ttl <= 31

        ok, _, default_meta = store.store(
            content="default",
            content_type=ContentType.TEXT_PLAIN,
            priority="unknown-priority",
        )
        assert ok is True
        assert default_meta is not None
        assert default_meta.priority == "normal"
        default_ttl = (default_meta.expires_at or 0) - default_meta.created_at
        assert 119 <= default_ttl <= 121

        metrics = store.get_metrics_snapshot()
        assert metrics["artifact_count"] == 2
        assert metrics["total_size_mb"] > 0
        assert metrics["store_attempt"] == 2
        assert metrics["store_success"] == 2
        assert metrics["quota_reject"] == 0
    finally:
        _cleanup(root)


def test_low_priority_write_rejected_at_high_watermark() -> None:
    store, root = _make_store(
        "high_watermark_low_reject",
        high_watermark_ratio=0.50,
        low_watermark_ratio=0.60,
    )
    try:
        ok, _, base_meta = store.store(
            content=_text_kb(580),
            content_type=ContentType.TEXT_PLAIN,
            priority="normal",
        )
        assert ok is True
        assert base_meta is not None

        ok, message, _ = store.store(
            content=_text_kb(10),
            content_type=ContentType.TEXT_PLAIN,
            priority="low",
        )
        assert ok is False
        assert "High watermark" in message

        rejected_metrics = store.get_metrics_snapshot()
        assert rejected_metrics["store_attempt"] == 2
        assert rejected_metrics["store_success"] == 1
        assert rejected_metrics["quota_reject"] == 1

        ok, _, high_meta = store.store(
            content=_text_kb(10),
            content_type=ContentType.TEXT_PLAIN,
            priority="high",
        )
        assert ok is True
        assert high_meta is not None
        assert high_meta.priority == "high"

        final_metrics = store.get_metrics_snapshot()
        assert final_metrics["store_attempt"] == 3
        assert final_metrics["store_success"] == 2
        assert final_metrics["quota_reject"] == 1
    finally:
        _cleanup(root)


def test_store_cleans_expired_before_rejecting_by_total_size() -> None:
    store, root = _make_store(
        "cleanup_before_reject",
        high_watermark_ratio=0.95,
        low_watermark_ratio=0.80,
    )
    try:
        ok, _, old_meta = store.store(
            content=_text_kb(700),
            content_type=ContentType.APPLICATION_JSON,
            priority="normal",
            ttl_seconds=300,
        )
        assert ok is True
        assert old_meta is not None

        # Simulate expiration and expect next write to reclaim it before quota check.
        cache_meta = store.get_metadata(old_meta.artifact_id)
        assert cache_meta is not None
        cache_meta.expires_at = time.time() - 5

        ok, _, new_meta = store.store(
            content=_text_kb(500),
            content_type=ContentType.APPLICATION_JSON,
            priority="normal",
        )
        assert ok is True
        assert new_meta is not None
        assert store.get_metadata(old_meta.artifact_id) is None

        metrics = store.get_metrics_snapshot()
        assert metrics["store_attempt"] == 2
        assert metrics["store_success"] == 2
        assert metrics["cleanup_deleted"] >= 1
        assert metrics["artifact_count"] == 1
    finally:
        _cleanup(root)


def test_metrics_snapshot_tracks_retrieve_hit_miss_and_cleanup() -> None:
    store, root = _make_store(
        "metrics_retrieve_cleanup",
        high_watermark_ratio=0.95,
        low_watermark_ratio=0.80,
    )
    try:
        ok, _, meta = store.store(
            content="metrics-payload",
            content_type=ContentType.TEXT_PLAIN,
            priority="normal",
            ttl_seconds=120,
        )
        assert ok is True
        assert meta is not None

        ok, _, content = store.retrieve(meta.artifact_id)
        assert ok is True
        assert content == "metrics-payload"

        ok, message, content = store.retrieve("artifact_not_exists")
        assert ok is False
        assert "Artifact not found" in message
        assert content is None

        cached = store.get_metadata(meta.artifact_id)
        assert cached is not None
        cached.expires_at = time.time() - 1

        deleted, freed = store.cleanup_expired()
        assert deleted == 1
        assert freed > 0

        metrics = store.get_metrics_snapshot()
        assert metrics["artifact_count"] == 0
        assert metrics["retrieve_hit"] == 1
        assert metrics["retrieve_miss"] == 1
        assert metrics["cleanup_deleted"] >= 1
    finally:
        _cleanup(root)
