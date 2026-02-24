"""Export local SLO/alert snapshot JSON for on-call dashboard baseline."""

from __future__ import annotations

import argparse
import json
import math
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import yaml

from system.artifact_store import ArtifactStore, ArtifactStoreConfig


STATUS_ORDER: Dict[str, int] = {
    "unknown": 0,
    "ok": 1,
    "warning": 2,
    "critical": 3,
}


@dataclass(frozen=True)
class SnapshotPaths:
    """Filesystem inputs used by SLO snapshot collector."""

    repo_root: Path
    events_file: Path
    workflow_db: Path
    global_mutex_state: Path
    autonomous_config: Path

    @classmethod
    def from_repo_root(cls, repo_root: Path) -> "SnapshotPaths":
        root = repo_root.resolve()
        return cls(
            repo_root=root,
            events_file=root / "logs" / "autonomous" / "events.jsonl",
            workflow_db=root / "logs" / "autonomous" / "workflow.db",
            global_mutex_state=root / "logs" / "runtime" / "global_mutex_lease.json",
            autonomous_config=root / "autonomous" / "config" / "autonomous_config.yaml",
        )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _to_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "y", "ok", "success"}


def _parse_iso_datetime(raw: Any) -> Optional[datetime]:
    text = str(raw or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _read_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if isinstance(payload, dict):
        return payload
    return {}


def _read_events(events_file: Path, *, limit: int) -> List[Dict[str, Any]]:
    if not events_file.exists() or limit <= 0:
        return []
    lines = events_file.read_text(encoding="utf-8", errors="ignore").splitlines()
    records: List[Dict[str, Any]] = []
    for line in lines[-limit:]:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            records.append(row)
    return records


def _percentile(values: Iterable[float], percentile: float) -> Optional[float]:
    points = sorted(float(v) for v in values)
    if not points:
        return None
    rank = max(0, min(len(points) - 1, math.ceil((percentile / 100.0) * len(points)) - 1))
    return points[rank]


def _classify_numeric(
    value: Optional[float],
    *,
    warning: float,
    critical: float,
    higher_is_bad: bool = True,
) -> str:
    if value is None:
        return "unknown"

    warn = float(warning)
    crit = float(critical)
    if higher_is_bad and warn > crit:
        warn, crit = crit, warn
    if not higher_is_bad and warn < crit:
        warn, crit = crit, warn

    if higher_is_bad:
        if value >= crit:
            return "critical"
        if value >= warn:
            return "warning"
        return "ok"

    if value <= crit:
        return "critical"
    if value <= warn:
        return "warning"
    return "ok"


def _stronger_status(left: str, right: str) -> str:
    lhs = STATUS_ORDER.get(left, 0)
    rhs = STATUS_ORDER.get(right, 0)
    return left if lhs >= rhs else right


def _collect_error_latency(
    events: List[Dict[str, Any]],
    *,
    max_error_rate: float,
    max_latency_p95_ms: float,
) -> Dict[str, Dict[str, Any]]:
    error_warning = max(0.0, max_error_rate * 0.5)
    latency_warning = max(1.0, max_latency_p95_ms * 0.8)

    cli_successes: List[bool] = []
    cli_latencies_ms: List[float] = []

    for row in events:
        if row.get("event_type") != "CliExecutionCompleted":
            continue
        payload = row.get("payload")
        if not isinstance(payload, dict):
            continue
        cli_successes.append(_to_bool(payload.get("success")))
        duration_s = _to_float(payload.get("duration_seconds"))
        if duration_s is not None and duration_s >= 0:
            cli_latencies_ms.append(duration_s * 1000.0)

    source = "cli_execution_events"
    sample_count = len(cli_successes)
    error_rate: Optional[float]
    latency_p95_ms: Optional[float]

    if sample_count > 0:
        failures = sum(1 for ok in cli_successes if not ok)
        error_rate = failures / sample_count
        latency_p95_ms = _percentile(cli_latencies_ms, 95)
    else:
        source = "canary_evaluated_windows"
        windows: List[Dict[str, Any]] = []
        for row in events:
            if row.get("event_type") not in {"ChangePromoted", "ReleaseRolledBack", "CanaryObserving"}:
                continue
            payload = row.get("payload")
            if not isinstance(payload, dict):
                continue
            decision = payload.get("decision")
            if not isinstance(decision, dict):
                continue
            evaluated = decision.get("evaluated_windows")
            if not isinstance(evaluated, list):
                continue
            for item in evaluated:
                if isinstance(item, dict):
                    windows.append(item)

        weighted_error = 0.0
        weighted_samples = 0
        canary_p95_values: List[float] = []
        for window in windows:
            sample = max(0, _to_int(window.get("sample_count"), 0))
            if sample <= 0:
                continue
            if window.get("eligible") is False:
                continue
            err = _to_float(window.get("error_rate"))
            p95 = _to_float(window.get("latency_p95_ms"))
            if err is not None:
                weighted_error += err * sample
                weighted_samples += sample
            if p95 is not None and p95 >= 0:
                canary_p95_values.append(p95)

        sample_count = weighted_samples
        error_rate = weighted_error / weighted_samples if weighted_samples > 0 else None
        latency_p95_ms = max(canary_p95_values) if canary_p95_values else None

    error_status = _classify_numeric(error_rate, warning=error_warning, critical=max_error_rate, higher_is_bad=True)
    latency_status = _classify_numeric(
        latency_p95_ms,
        warning=latency_warning,
        critical=max_latency_p95_ms,
        higher_is_bad=True,
    )

    return {
        "error_rate": {
            "value": error_rate,
            "unit": "ratio",
            "sample_count": sample_count,
            "source": source,
            "thresholds": {
                "warning": error_warning,
                "critical": max_error_rate,
            },
            "status": error_status,
        },
        "latency_p95_ms": {
            "value": latency_p95_ms,
            "unit": "ms",
            "sample_count": sample_count,
            "source": source,
            "thresholds": {
                "warning": latency_warning,
                "critical": max_latency_p95_ms,
            },
            "status": latency_status,
        },
    }


def _collect_queue_depth(
    workflow_db: Path,
    *,
    now_dt: datetime,
    batch_size: int,
) -> Dict[str, Any]:
    warn_count = max(1, int(batch_size))
    critical_count = max(warn_count + 1, warn_count * 3)
    warn_age_seconds = 120
    critical_age_seconds = 300

    if not workflow_db.exists():
        return {
            "value": None,
            "unit": "events",
            "oldest_pending_age_seconds": None,
            "source": "workflow_db_missing",
            "thresholds": {
                "warning": warn_count,
                "critical": critical_count,
                "warning_oldest_age_seconds": warn_age_seconds,
                "critical_oldest_age_seconds": critical_age_seconds,
            },
            "status": "unknown",
        }

    pending_count = 0
    oldest_pending_age_seconds: Optional[float] = None
    try:
        conn = sqlite3.connect(str(workflow_db))
        with conn:
            row = conn.execute(
                "SELECT COUNT(*) AS c, MIN(created_at) AS oldest FROM outbox_event WHERE status = 'pending'"
            ).fetchone()
    except sqlite3.DatabaseError:
        return {
            "value": None,
            "unit": "events",
            "oldest_pending_age_seconds": None,
            "source": "workflow_db_query_failed",
            "thresholds": {
                "warning": warn_count,
                "critical": critical_count,
                "warning_oldest_age_seconds": warn_age_seconds,
                "critical_oldest_age_seconds": critical_age_seconds,
            },
            "status": "unknown",
        }
    finally:
        try:
            conn.close()  # type: ignore[misc]
        except Exception:
            pass

    if row:
        pending_count = _to_int(row[0], 0)
        oldest = _parse_iso_datetime(row[1])
        if oldest is not None:
            oldest_pending_age_seconds = max(0.0, (now_dt - oldest).total_seconds())

    status = _classify_numeric(float(pending_count), warning=warn_count, critical=critical_count, higher_is_bad=True)
    if oldest_pending_age_seconds is not None:
        age_status = _classify_numeric(
            oldest_pending_age_seconds,
            warning=warn_age_seconds,
            critical=critical_age_seconds,
            higher_is_bad=True,
        )
        status = _stronger_status(status, age_status)

    return {
        "value": pending_count,
        "unit": "events",
        "oldest_pending_age_seconds": oldest_pending_age_seconds,
        "source": "workflow_outbox_event",
        "thresholds": {
            "warning": warn_count,
            "critical": critical_count,
            "warning_oldest_age_seconds": warn_age_seconds,
            "critical_oldest_age_seconds": critical_age_seconds,
        },
        "status": status,
    }


def _collect_disk_watermark(repo_root: Path) -> Dict[str, Any]:
    artifact_root = repo_root / "logs" / "artifacts"
    store = ArtifactStore(ArtifactStoreConfig(artifact_root=artifact_root))
    metrics = store.get_metrics_snapshot()

    max_total_size_mb = float(store.config.max_total_size_mb)
    usage_ratio = None
    if max_total_size_mb > 0:
        usage_ratio = float(metrics.get("total_size_mb", 0.0)) / max_total_size_mb

    warning_ratio = float(store.config.high_watermark_ratio)
    reserve = max(0.0, min(1.0, _to_float(store.config.critical_reserve_ratio, 0.0) or 0.0))
    critical_ratio = max(warning_ratio, 1.0 - reserve)

    status = _classify_numeric(usage_ratio, warning=warning_ratio, critical=critical_ratio, higher_is_bad=True)

    filesystem_free_gb: Optional[float] = None
    filesystem_used_ratio: Optional[float] = None
    try:
        usage = shutil.disk_usage(str(artifact_root))
        filesystem_free_gb = usage.free / (1024**3)
        filesystem_used_ratio = (usage.total - usage.free) / usage.total if usage.total > 0 else None
    except OSError:
        pass

    return {
        "value": usage_ratio,
        "unit": "ratio",
        "artifact_count": _to_int(metrics.get("artifact_count"), 0),
        "total_size_mb": _to_float(metrics.get("total_size_mb"), 0.0),
        "max_total_size_mb": max_total_size_mb,
        "filesystem_free_gb": filesystem_free_gb,
        "filesystem_used_ratio": filesystem_used_ratio,
        "source": "artifact_store",
        "thresholds": {
            "warning": warning_ratio,
            "critical": critical_ratio,
            "high_watermark_ratio": warning_ratio,
            "critical_reserve_ratio": reserve,
        },
        "status": status,
    }


def _collect_lock_status(
    lock_state_file: Path,
    *,
    now_ts: float,
    lease_ttl_hint_seconds: float,
) -> Dict[str, Any]:
    warn_seconds = max(2.0, lease_ttl_hint_seconds * 0.2)
    thresholds = {
        "warning_seconds_to_expiry": warn_seconds,
        "critical_seconds_to_expiry": 0.0,
    }

    if not lock_state_file.exists():
        return {
            "value": None,
            "unit": "seconds_to_expiry",
            "state": "missing",
            "owner_id": "",
            "fencing_epoch": 0,
            "source": "global_mutex_state_missing",
            "thresholds": thresholds,
            "status": "unknown",
        }

    try:
        payload = json.loads(lock_state_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {
            "value": None,
            "unit": "seconds_to_expiry",
            "state": "parse_failed",
            "owner_id": "",
            "fencing_epoch": 0,
            "source": "global_mutex_state_parse_failed",
            "thresholds": thresholds,
            "status": "unknown",
        }

    if not isinstance(payload, dict):
        return {
            "value": None,
            "unit": "seconds_to_expiry",
            "state": "invalid_payload",
            "owner_id": "",
            "fencing_epoch": 0,
            "source": "global_mutex_state_invalid",
            "thresholds": thresholds,
            "status": "unknown",
        }

    ttl_seconds = _to_float(payload.get("ttl_seconds"), lease_ttl_hint_seconds) or lease_ttl_hint_seconds
    expires_at = _to_float(payload.get("expires_at"), now_ts)
    seconds_to_expiry = expires_at - now_ts if expires_at is not None else None

    status = _classify_numeric(
        seconds_to_expiry,
        warning=max(2.0, ttl_seconds * 0.2),
        critical=0.0,
        higher_is_bad=False,
    )

    if seconds_to_expiry is None:
        state = "unknown"
    elif seconds_to_expiry <= 0:
        state = "expired"
    elif seconds_to_expiry <= max(2.0, ttl_seconds * 0.2):
        state = "near_expiry"
    else:
        state = "healthy"

    return {
        "value": seconds_to_expiry,
        "unit": "seconds_to_expiry",
        "state": state,
        "lease_id": str(payload.get("lease_id") or ""),
        "owner_id": str(payload.get("owner_id") or ""),
        "job_id": str(payload.get("job_id") or ""),
        "fencing_epoch": _to_int(payload.get("fencing_epoch"), 0),
        "ttl_seconds": ttl_seconds,
        "source": "global_mutex_state",
        "thresholds": {
            "warning_seconds_to_expiry": max(2.0, ttl_seconds * 0.2),
            "critical_seconds_to_expiry": 0.0,
        },
        "status": status,
    }


def _load_threshold_config(config_file: Path) -> Dict[str, Any]:
    defaults = {
        "max_error_rate": 0.02,
        "max_latency_p95_ms": 1500.0,
        "queue_batch_size": 50,
        "lease_ttl_seconds": 10.0,
    }

    payload = _read_yaml(config_file)
    autonomous = payload.get("autonomous") if isinstance(payload.get("autonomous"), dict) else {}
    release = autonomous.get("release") if isinstance(autonomous.get("release"), dict) else {}
    outbox = autonomous.get("outbox_dispatch") if isinstance(autonomous.get("outbox_dispatch"), dict) else {}
    lease = autonomous.get("lease") if isinstance(autonomous.get("lease"), dict) else {}

    defaults["max_error_rate"] = max(0.0, _to_float(release.get("max_error_rate"), defaults["max_error_rate"]) or 0.0)
    defaults["max_latency_p95_ms"] = max(
        1.0,
        _to_float(release.get("max_latency_p95_ms"), defaults["max_latency_p95_ms"]) or defaults["max_latency_p95_ms"],
    )
    defaults["queue_batch_size"] = max(1, _to_int(outbox.get("batch_size"), defaults["queue_batch_size"]))
    defaults["lease_ttl_seconds"] = max(
        1.0,
        _to_float(lease.get("ttl_seconds"), defaults["lease_ttl_seconds"]) or defaults["lease_ttl_seconds"],
    )
    return defaults


def _summarize_overall(metrics: Dict[str, Dict[str, Any]]) -> str:
    overall = "unknown"
    for payload in metrics.values():
        status = str(payload.get("status") or "unknown")
        overall = _stronger_status(overall, status)
    return overall


def build_snapshot(
    *,
    repo_root: Path,
    now: Optional[datetime] = None,
    events_limit: int = 5000,
) -> Dict[str, Any]:
    paths = SnapshotPaths.from_repo_root(repo_root)
    now_dt = now.astimezone(timezone.utc) if now is not None else _utc_now()

    thresholds = _load_threshold_config(paths.autonomous_config)
    events = _read_events(paths.events_file, limit=max(1, int(events_limit)))

    metrics = _collect_error_latency(
        events,
        max_error_rate=float(thresholds["max_error_rate"]),
        max_latency_p95_ms=float(thresholds["max_latency_p95_ms"]),
    )
    metrics["queue_depth"] = _collect_queue_depth(
        paths.workflow_db,
        now_dt=now_dt,
        batch_size=int(thresholds["queue_batch_size"]),
    )
    metrics["disk_watermark_ratio"] = _collect_disk_watermark(paths.repo_root)
    metrics["lock_status"] = _collect_lock_status(
        paths.global_mutex_state,
        now_ts=now_dt.timestamp(),
        lease_ttl_hint_seconds=float(thresholds["lease_ttl_seconds"]),
    )

    snapshot = {
        "schema_version": "1.0.0",
        "generated_at": now_dt.isoformat(),
        "project_root": str(paths.repo_root),
        "summary": {
            "overall_status": _summarize_overall(metrics),
            "metric_status": {name: payload.get("status", "unknown") for name, payload in metrics.items()},
        },
        "metrics": metrics,
        "threshold_profile": thresholds,
        "sources": {
            "events_file": str(paths.events_file),
            "workflow_db": str(paths.workflow_db),
            "global_mutex_state": str(paths.global_mutex_state),
            "autonomous_config": str(paths.autonomous_config),
            "events_scanned": len(events),
        },
    }
    return snapshot


def export_snapshot(snapshot: Dict[str, Any], *, output_file: Path, indent: int = 2) -> Path:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(snapshot, ensure_ascii=False, indent=indent) + "\n", encoding="utf-8")
    return output_file


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export local SLO snapshot JSON baseline")
    parser.add_argument("--repo-root", type=Path, default=Path("."), help="Repository root path")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("logs/runtime/slo_snapshot_baseline.json"),
        help="Output JSON file path (relative to repo-root by default)",
    )
    parser.add_argument("--events-limit", type=int, default=5000, help="Maximum event rows scanned from events.jsonl")
    parser.add_argument("--indent", type=int, default=2, help="JSON indent size")
    parser.add_argument("--stdout-only", action="store_true", help="Print JSON only, do not write output file")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()

    snapshot = build_snapshot(repo_root=repo_root, events_limit=args.events_limit)
    rendered = json.dumps(snapshot, ensure_ascii=False, indent=max(0, int(args.indent)))
    print(rendered)

    if args.stdout_only:
        return 0

    output_file = args.output
    if not output_file.is_absolute():
        output_file = repo_root / output_file
    export_snapshot(snapshot, output_file=output_file, indent=max(0, int(args.indent)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
