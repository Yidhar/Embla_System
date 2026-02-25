"""WS27-001 72h endurance and disk quota pressure baseline harness."""

from __future__ import annotations

import json
import math
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from autonomous.event_log import EventStore
from system.artifact_store import ArtifactStore, ArtifactStoreConfig, ContentType


def _clamp_ratio(value: float, *, default: float) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    if numeric <= 0:
        return default
    if numeric >= 1:
        return 0.99
    return numeric


def _build_artifact_payload(round_idx: int, payload_bytes: int) -> str:
    seed = f"WS27-001-R{int(round_idx):06d}|"
    if payload_bytes <= len(seed):
        return seed[:payload_bytes]
    return seed + ("x" * (payload_bytes - len(seed)))


def _to_unix_path(path: Path) -> str:
    return str(path).replace("\\", "/")


@dataclass(frozen=True)
class WS27LongRunConfig:
    target_hours: float = 72.0
    virtual_round_seconds: float = 300.0
    artifact_payload_kb: int = 128
    max_total_size_mb: int = 24
    max_single_artifact_mb: int = 2
    max_artifact_count: int = 4_096
    high_watermark_ratio: float = 0.85
    low_watermark_ratio: float = 0.65
    critical_reserve_ratio: float = 0.10
    normal_priority_every: int = 12
    high_priority_every: int = 48


def _pick_priority(round_idx: int, *, normal_every: int, high_every: int) -> str:
    if high_every > 0 and round_idx % high_every == 0:
        return "high"
    if normal_every > 0 and round_idx % normal_every == 0:
        return "normal"
    return "low"


def run_ws27_72h_endurance_baseline(
    *,
    scratch_root: Path = Path("scratch/ws27_72h_endurance"),
    report_file: Path = Path("scratch/reports/ws27_72h_endurance_ws27_001.json"),
    config: WS27LongRunConfig = WS27LongRunConfig(),
) -> Dict[str, Any]:
    case_id = uuid.uuid4().hex[:10]
    case_root = scratch_root / case_id
    case_root.mkdir(parents=True, exist_ok=True)
    report_file.parent.mkdir(parents=True, exist_ok=True)

    target_seconds = max(60.0, float(config.target_hours) * 3600.0)
    round_seconds = max(1.0, float(config.virtual_round_seconds))
    rounds = max(1, int(math.ceil(target_seconds / round_seconds)))
    payload_bytes = max(1024, int(config.artifact_payload_kb) * 1024)
    normal_every = max(1, int(config.normal_priority_every))
    high_every = max(1, int(config.high_priority_every))
    max_total_size_mb = max(1, int(config.max_total_size_mb))

    artifact_store = ArtifactStore(
        ArtifactStoreConfig(
            artifact_root=case_root / "artifacts",
            max_total_size_mb=max_total_size_mb,
            max_single_artifact_mb=max(1, int(config.max_single_artifact_mb)),
            max_artifact_count=max(16, int(config.max_artifact_count)),
            high_watermark_ratio=_clamp_ratio(config.high_watermark_ratio, default=0.85),
            low_watermark_ratio=_clamp_ratio(config.low_watermark_ratio, default=0.65),
            critical_reserve_ratio=_clamp_ratio(config.critical_reserve_ratio, default=0.10),
        )
    )
    event_store = EventStore(file_path=case_root / "events.jsonl")

    published_event_ids: List[str] = []
    captured_event_ids: List[str] = []
    unhandled_errors: List[str] = []
    store_failures: List[str] = []
    enospc_errors: List[str] = []
    peak_usage_mb = 0.0
    peak_usage_ratio = 0.0
    pressure_signal_total = 0
    previous_pressure_total = 0
    started_at = time.time()

    subscription = event_store.subscribe(
        "system.ws27.longrun",
        lambda event: captured_event_ids.append(str(event.get("event_id") or "")),
    )

    try:
        for round_idx in range(1, rounds + 1):
            priority = _pick_priority(round_idx, normal_every=normal_every, high_every=high_every)
            payload = _build_artifact_payload(round_idx, payload_bytes)
            try:
                ok, message, metadata = artifact_store.store(
                    content=payload,
                    content_type=ContentType.TEXT_PLAIN,
                    source_tool="ws27_longrun_pressure",
                    source_call_id=f"ws27-round-{round_idx:06d}",
                    source_trace_id=f"trace-ws27-{round_idx:06d}",
                    priority=priority,
                )

                if not ok:
                    failure = f"round={round_idx}, reason={message}"
                    store_failures.append(failure)
                    lowered = str(message).lower()
                    if "enospc" in lowered or "no space left on device" in lowered:
                        enospc_errors.append(failure)

                store_metrics = artifact_store.get_metrics_snapshot()
                usage_mb = float(store_metrics.get("total_size_mb") or 0.0)
                usage_ratio = usage_mb / float(max_total_size_mb) if max_total_size_mb > 0 else 0.0
                peak_usage_mb = max(peak_usage_mb, usage_mb)
                peak_usage_ratio = max(peak_usage_ratio, usage_ratio)

                current_pressure_total = int(store_metrics.get("quota_reject") or 0) + int(
                    store_metrics.get("backpressure_warn") or 0
                ) + int(store_metrics.get("cleanup_deleted") or 0)
                if current_pressure_total > previous_pressure_total:
                    pressure_signal_total += current_pressure_total - previous_pressure_total
                    previous_pressure_total = current_pressure_total

                event_id = event_store.publish(
                    "system.ws27.longrun",
                    {
                        "round": round_idx,
                        "priority": priority,
                        "artifact_store_ok": bool(ok),
                        "artifact_store_message": str(message),
                        "artifact_id": "" if metadata is None else str(metadata.artifact_id),
                        "artifact_usage_mb": round(usage_mb, 6),
                        "artifact_usage_ratio": round(usage_ratio, 6),
                    },
                    event_type="WS27LongRunRoundEvent",
                    source="autonomous.ws27.longrun",
                    idempotency_key=f"ws27-longrun-{round_idx:06d}",
                )
                published_event_ids.append(str(event_id))
            except Exception as exc:  # pragma: no cover - runtime safety net
                unhandled_errors.append(f"round={round_idx}, error={type(exc).__name__}:{exc}")
    finally:
        event_store.unsubscribe(subscription)

    persisted_rows = event_store.replay_by_topic(
        topic_pattern="system.ws27.longrun",
        from_seq=1,
        limit=max(rounds + 32, 512),
    )
    persisted_event_ids = [str(row.get("event_id") or "") for row in persisted_rows]
    persisted_set = set(persisted_event_ids)
    captured_set = set(captured_event_ids)
    missing_from_store = [event_id for event_id in published_event_ids if event_id not in persisted_set]
    missing_from_dispatch = [event_id for event_id in published_event_ids if event_id not in captured_set]
    missing_event_ids = sorted(set(missing_from_store + missing_from_dispatch))

    final_store_metrics = artifact_store.get_metrics_snapshot()
    virtual_elapsed_seconds = round(rounds * round_seconds, 2)
    metrics = {
        "target_hours": round(float(config.target_hours), 4),
        "virtual_target_seconds": round(target_seconds, 2),
        "virtual_round_seconds": round(round_seconds, 2),
        "virtual_elapsed_seconds": virtual_elapsed_seconds,
        "rounds": rounds,
        "artifact_payload_bytes": payload_bytes,
        "published_event_count": len(published_event_ids),
        "captured_event_count": len(captured_event_ids),
        "persisted_event_count": len(persisted_rows),
        "event_loss_count": len(missing_event_ids),
        "store_failure_count": len(store_failures),
        "enospc_error_count": len(enospc_errors),
        "unhandled_exception_count": len(unhandled_errors),
        "artifact_store_attempt": int(final_store_metrics.get("store_attempt") or 0),
        "artifact_store_success": int(final_store_metrics.get("store_success") or 0),
        "artifact_quota_reject": int(final_store_metrics.get("quota_reject") or 0),
        "artifact_backpressure_warn": int(final_store_metrics.get("backpressure_warn") or 0),
        "artifact_cleanup_deleted": int(final_store_metrics.get("cleanup_deleted") or 0),
        "artifact_usage_peak_mb": round(peak_usage_mb, 4),
        "artifact_usage_peak_ratio": round(peak_usage_ratio, 4),
        "pressure_signal_total": int(pressure_signal_total),
        "elapsed_wall_seconds": round(time.time() - started_at, 4),
    }

    checks = {
        "virtual_72h_target_reached": metrics["virtual_elapsed_seconds"] >= metrics["virtual_target_seconds"],
        "no_enospc": metrics["enospc_error_count"] == 0,
        "no_unhandled_exceptions": metrics["unhandled_exception_count"] == 0,
        "no_event_loss": metrics["event_loss_count"] == 0,
        "disk_quota_pressure_exercised": metrics["pressure_signal_total"] > 0,
    }
    passed = all(checks.values())

    report: Dict[str, Any] = {
        "task_id": "NGA-WS27-001",
        "scenario": "ws27_72h_endurance_and_disk_quota_pressure",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "case_root": _to_unix_path(case_root),
        "report_file": _to_unix_path(report_file),
        "passed": passed,
        "checks": checks,
        "metrics": metrics,
        "missing_event_ids": missing_event_ids[:20],
        "store_failure_samples": store_failures[:20],
        "enospc_error_samples": enospc_errors[:20],
        "unhandled_errors": unhandled_errors[:20],
    }
    report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


__all__ = ["WS27LongRunConfig", "run_ws27_72h_endurance_baseline"]
