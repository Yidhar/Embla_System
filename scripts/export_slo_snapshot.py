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

from autonomous.event_log.event_schema import normalize_event_envelope
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
            envelope = normalize_event_envelope(
                row,
                fallback_event_type=str(row.get("event_type") or ""),
                fallback_timestamp=str(row.get("timestamp") or ""),
            )
            records.append({**envelope, "payload": dict(envelope.get("data") or {})})
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

    execution_successes: List[bool] = []
    execution_latencies_ms: List[float] = []

    for row in events:
        if row.get("event_type") != "TaskExecutionCompleted":
            continue
        payload = row.get("payload")
        if not isinstance(payload, dict):
            continue
        execution_successes.append(_to_bool(payload.get("success")))
        duration_s = _to_float(payload.get("duration_seconds"))
        if duration_s is not None and duration_s >= 0:
            execution_latencies_ms.append(duration_s * 1000.0)

    source = "task_execution_events"
    sample_count = len(execution_successes)
    error_rate: Optional[float]
    latency_p95_ms: Optional[float]

    if sample_count > 0:
        failures = sum(1 for ok in execution_successes if not ok)
        error_rate = failures / sample_count
        latency_p95_ms = _percentile(execution_latencies_ms, 95)
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

    lease_state = str(payload.get("lease_state") or payload.get("state") or "").strip().lower()
    if lease_state == "idle":
        ttl_seconds = _to_float(payload.get("ttl_seconds"), lease_ttl_hint_seconds) or lease_ttl_hint_seconds
        return {
            "value": None,
            "unit": "seconds_to_expiry",
            "state": "idle",
            "lease_id": str(payload.get("lease_id") or ""),
            "owner_id": str(payload.get("owner_id") or ""),
            "job_id": str(payload.get("job_id") or ""),
            "fencing_epoch": _to_int(payload.get("fencing_epoch"), 0),
            "ttl_seconds": ttl_seconds,
            "source": "global_mutex_state_idle",
            "thresholds": {
                "warning_seconds_to_expiry": max(2.0, ttl_seconds * 0.2),
                "critical_seconds_to_expiry": 0.0,
            },
            "status": "ok",
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


def _collect_runtime_rollout(
    events: List[Dict[str, Any]],
    *,
    configured_rollout_percent: int,
) -> Dict[str, Any]:
    decisions = []
    for row in events:
        if row.get("event_type") != "SubAgentRuntimeRolloutDecision":
            continue
        payload = row.get("payload")
        if isinstance(payload, dict):
            decisions.append(payload)

    total = len(decisions)
    subagent_count = 0
    legacy_count = 0
    reason_counts: Dict[str, int] = {}
    for payload in decisions:
        runtime_mode = str(payload.get("runtime_mode") or "").strip().lower()
        if runtime_mode == "subagent":
            subagent_count += 1
        elif runtime_mode == "legacy":
            legacy_count += 1
        reason = str(payload.get("decision_reason") or "unknown")
        reason_counts[reason] = reason_counts.get(reason, 0) + 1

    hit_ratio = (subagent_count / total) if total > 0 else None
    expected_ratio = max(0.0, min(1.0, float(configured_rollout_percent) / 100.0))
    if total <= 0:
        status = "unknown"
        thresholds = {"warning": None, "critical": None}
    elif expected_ratio <= 0.0:
        status = _classify_numeric(hit_ratio, warning=0.2, critical=0.4, higher_is_bad=True)
        thresholds = {"warning": 0.2, "critical": 0.4}
    else:
        status = _classify_numeric(
            hit_ratio,
            warning=max(0.0, expected_ratio * 0.7),
            critical=max(0.0, expected_ratio * 0.4),
            higher_is_bad=False,
        )
        thresholds = {
            "warning": max(0.0, expected_ratio * 0.7),
            "critical": max(0.0, expected_ratio * 0.4),
        }

    return {
        "value": hit_ratio,
        "unit": "ratio",
        "total_decisions": total,
        "subagent_decisions": subagent_count,
        "legacy_decisions": legacy_count,
        "decision_reasons": reason_counts,
        "configured_rollout_percent": int(max(0, min(100, int(configured_rollout_percent)))),
        "source": "runtime_rollout_events",
        "thresholds": thresholds,
        "status": status,
    }


def _collect_runtime_fail_open(
    events: List[Dict[str, Any]],
    *,
    fail_open_budget_ratio: float,
) -> Dict[str, Any]:
    budget = max(0.0, min(1.0, float(fail_open_budget_ratio)))
    fail_open_count = 0
    blocked_count = 0
    subagent_attempt_count = 0
    gate_failure_counts: Dict[str, int] = {}

    for row in events:
        event_type = str(row.get("event_type") or "")
        payload = row.get("payload")
        payload_dict = payload if isinstance(payload, dict) else {}
        if event_type == "SubAgentRuntimeCompleted":
            subagent_attempt_count += 1
        if event_type == "SubAgentRuntimeFailOpen":
            fail_open_count += 1
            gate_failure = str(payload_dict.get("gate_failure") or "unknown")
            gate_failure_counts[gate_failure] = gate_failure_counts.get(gate_failure, 0) + 1
        if event_type == "SubAgentRuntimeFailOpenBlocked":
            blocked_count += 1
            gate_failure = str(payload_dict.get("gate_failure") or "unknown")
            gate_failure_counts[gate_failure] = gate_failure_counts.get(gate_failure, 0) + 1

    fail_open_ratio = (fail_open_count / subagent_attempt_count) if subagent_attempt_count > 0 else None
    blocked_ratio = (blocked_count / subagent_attempt_count) if subagent_attempt_count > 0 else None
    status = _classify_numeric(
        fail_open_ratio,
        warning=max(0.0, budget * 0.8),
        critical=budget,
        higher_is_bad=True,
    )
    if subagent_attempt_count <= 0:
        status = "unknown"

    budget_exhausted = bool(fail_open_ratio is not None and fail_open_ratio > budget)
    budget_remaining_ratio = None
    if fail_open_ratio is not None:
        budget_remaining_ratio = max(0.0, budget - fail_open_ratio)

    return {
        "value": fail_open_ratio,
        "unit": "ratio",
        "subagent_attempt_count": subagent_attempt_count,
        "fail_open_count": fail_open_count,
        "fail_open_blocked_count": blocked_count,
        "fail_open_blocked_ratio": blocked_ratio,
        "gate_failure_counts": gate_failure_counts,
        "configured_budget_ratio": budget,
        "budget_exhausted": budget_exhausted,
        "budget_remaining_ratio": budget_remaining_ratio,
        "source": "runtime_fail_open_events",
        "thresholds": {
            "warning": max(0.0, budget * 0.8),
            "critical": budget,
        },
        "status": status,
    }


def _collect_runtime_lease(
    events: List[Dict[str, Any]],
    *,
    workflow_db: Path,
    now_dt: datetime,
    lease_name: str,
    lease_ttl_hint_seconds: float,
) -> Dict[str, Any]:
    lease_acquired_count = sum(1 for row in events if row.get("event_type") == "LeaseAcquired")
    lease_lost_count = sum(1 for row in events if row.get("event_type") == "LeaseLost")
    churn_ratio = (lease_lost_count / lease_acquired_count) if lease_acquired_count > 0 else None

    warning_churn_ratio = 0.1
    critical_churn_ratio = 0.3
    churn_status = _classify_numeric(
        churn_ratio,
        warning=warning_churn_ratio,
        critical=critical_churn_ratio,
        higher_is_bad=True,
    )
    if lease_acquired_count <= 0 and lease_lost_count <= 0:
        churn_status = "unknown"

    owner_id = ""
    fencing_epoch = 0
    seconds_to_expiry: Optional[float] = None
    lease_state = "missing"
    source = "workflow_db_lease_missing"

    if workflow_db.exists():
        try:
            conn = sqlite3.connect(str(workflow_db))
            with conn:
                row = conn.execute(
                    """
                    SELECT owner_id, fencing_epoch, lease_expire_at
                    FROM orchestrator_lease
                    WHERE lease_name = ?
                    """,
                    (lease_name,),
                ).fetchone()
            if row is not None:
                owner_id = str(row[0] or "")
                fencing_epoch = _to_int(row[1], 0)
                expires_at = _parse_iso_datetime(row[2])
                if expires_at is not None:
                    seconds_to_expiry = max(0.0, (expires_at - now_dt).total_seconds())
                source = "workflow_db_lease"
        except sqlite3.DatabaseError:
            source = "workflow_db_lease_query_failed"
        finally:
            try:
                conn.close()  # type: ignore[misc]
            except Exception:
                pass

    warn_seconds = max(2.0, lease_ttl_hint_seconds * 0.2)
    expiry_status = _classify_numeric(
        seconds_to_expiry,
        warning=warn_seconds,
        critical=0.0,
        higher_is_bad=False,
    )
    if seconds_to_expiry is None:
        lease_state = "missing"
        expiry_status = "unknown"
    elif seconds_to_expiry <= 0:
        lease_state = "expired"
    elif seconds_to_expiry <= warn_seconds:
        lease_state = "near_expiry"
    else:
        lease_state = "healthy"

    status = _stronger_status(churn_status, expiry_status)
    if lease_state == "missing" and lease_acquired_count <= 0 and lease_lost_count <= 0:
        status = "unknown"

    return {
        "value": seconds_to_expiry,
        "unit": "seconds_to_expiry",
        "state": lease_state,
        "lease_name": str(lease_name or ""),
        "owner_id": owner_id,
        "fencing_epoch": fencing_epoch,
        "lease_acquired_count": lease_acquired_count,
        "lease_lost_count": lease_lost_count,
        "lease_lost_churn_ratio": churn_ratio,
        "source": source,
        "thresholds": {
            "warning_seconds_to_expiry": warn_seconds,
            "critical_seconds_to_expiry": 0.0,
            "warning_churn_ratio": warning_churn_ratio,
            "critical_churn_ratio": critical_churn_ratio,
        },
        "status": status,
    }


def _collect_prompt_injection_quality(events: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    decisions: List[Dict[str, Any]] = []
    for row in events:
        if str(row.get("event_type") or "") != "PromptInjectionComposed":
            continue
        payload = row.get("payload")
        if isinstance(payload, dict):
            decisions.append(payload)

    total = len(decisions)
    layer_counts: Dict[str, int] = {}
    trigger_counts: Dict[str, int] = {}
    selected_slice_total = 0
    recovery_hit_count = 0
    conflict_drop_count = 0
    delegation_hit_count = 0
    outer_readonly_hit_count = 0
    readonly_exposure_sample_count = 0
    readonly_write_tool_exposure_count = 0
    readonly_write_tool_exposed_slice_count = 0
    core_escalation_count = 0
    route_path_counts: Dict[str, int] = {"path-a": 0, "path-b": 0, "path-c": 0}
    path_b_budget_escalated_count = 0
    core_session_created_count = 0
    prefix_cache_hit_count = 0
    tail_hashes: List[str] = []
    contract_upgrade_latencies_ms: List[float] = []
    recovery_survival_total = 0
    recovery_survival_count = 0

    for payload in decisions:
        selected_layer_counts = payload.get("selected_layer_counts")
        if isinstance(selected_layer_counts, dict) and selected_layer_counts:
            for layer, raw_count in selected_layer_counts.items():
                layer_key = str(layer or "L_UNKNOWN")
                layer_counts[layer_key] = layer_counts.get(layer_key, 0) + max(0, _to_int(raw_count, 0))
        else:
            selected_layers = payload.get("selected_layers")
            if isinstance(selected_layers, list):
                for layer in selected_layers:
                    layer_key = str(layer or "L_UNKNOWN")
                    layer_counts[layer_key] = layer_counts.get(layer_key, 0) + 1

        selected_slice_count = _to_int(payload.get("selected_slice_count"), -1)
        if selected_slice_count < 0:
            selected_slices = payload.get("selected_slices")
            if isinstance(selected_slices, list):
                selected_slice_count = len(selected_slices)
            else:
                selected_slice_count = 0
        selected_slice_total += max(0, selected_slice_count)

        trigger = str(payload.get("trigger") or payload.get("path") or "unknown")
        trigger_counts[trigger] = trigger_counts.get(trigger, 0) + 1

        route_path = str(payload.get("path") or "").strip().lower()
        if route_path in route_path_counts:
            route_path_counts[route_path] = int(route_path_counts.get(route_path, 0)) + 1

        if bool(payload.get("recovery_hit")):
            recovery_hit_count += 1

        dropped_conflict_count = _to_int(payload.get("dropped_conflict_count"), -1)
        if dropped_conflict_count < 0:
            dropped_conflict_count = _to_int(payload.get("dropped_slice_count"), -1)
        if dropped_conflict_count < 0:
            dropped_slices = payload.get("dropped_slices")
            if isinstance(dropped_slices, list):
                dropped_conflict_count = len(dropped_slices)
            else:
                dropped_conflict_count = 0
        conflict_drop_count += max(0, dropped_conflict_count)

        delegation_hit = payload.get("delegation_hit")
        if isinstance(delegation_hit, bool):
            if delegation_hit:
                delegation_hit_count += 1
        else:
            delegation_intent = str(payload.get("delegation_intent") or "").strip().lower()
            if delegation_intent.startswith("delegate"):
                delegation_hit_count += 1

        if bool(payload.get("outer_readonly_hit")):
            outer_readonly_hit_count += 1
            readonly_exposure_sample_count += 1
            readonly_selected_count = _to_int(payload.get("readonly_write_tool_selected_count"), -1)
            if readonly_selected_count < 0:
                selected_exposed = payload.get("readonly_write_tool_selected_slices")
                if isinstance(selected_exposed, list):
                    readonly_selected_count = len(selected_exposed)
                else:
                    readonly_selected_count = 0
            readonly_exposed = bool(payload.get("readonly_write_tool_exposed")) or readonly_selected_count > 0
            if readonly_exposed:
                readonly_write_tool_exposure_count += 1
                readonly_write_tool_exposed_slice_count += max(0, readonly_selected_count)
        if bool(payload.get("core_escalation")):
            core_escalation_count += 1
        if bool(payload.get("path_b_budget_escalated")):
            path_b_budget_escalated_count += 1
        if bool(payload.get("core_session_created")):
            core_session_created_count += 1

        prefix_cache_hit = payload.get("prefix_cache_hit")
        if isinstance(prefix_cache_hit, bool):
            if prefix_cache_hit:
                prefix_cache_hit_count += 1
        else:
            block1_hit = bool(payload.get("block1_cache_hit"))
            block2_hit = bool(payload.get("block2_cache_hit"))
            if block1_hit and block2_hit:
                prefix_cache_hit_count += 1

        tail_hash = str(payload.get("tail_hash") or "").strip()
        if tail_hash:
            tail_hashes.append(tail_hash)

        latency_ms = _to_float(payload.get("contract_upgrade_latency_ms"))
        if latency_ms is not None and latency_ms >= 0:
            contract_upgrade_latencies_ms.append(latency_ms)

        if "recovery_context_survived" in payload:
            recovery_survival_total += 1
            if bool(payload.get("recovery_context_survived")):
                recovery_survival_count += 1

    average_selected_slice_count = (selected_slice_total / total) if total > 0 else None
    trigger_distribution = {
        trigger: (count / total) for trigger, count in trigger_counts.items()
    } if total > 0 else {}
    recovery_slice_hit_rate = (recovery_hit_count / total) if total > 0 else None
    delegation_hit_rate = (delegation_hit_count / total) if total > 0 else None
    outer_readonly_hit_rate = (outer_readonly_hit_count / total) if total > 0 else None
    readonly_write_tool_exposure_rate = (
        readonly_write_tool_exposure_count / readonly_exposure_sample_count
    ) if readonly_exposure_sample_count > 0 else None
    core_escalation_rate = (core_escalation_count / total) if total > 0 else None
    path_a_route_ratio = (route_path_counts.get("path-a", 0) / total) if total > 0 else None
    path_b_route_ratio = (route_path_counts.get("path-b", 0) / total) if total > 0 else None
    path_c_route_ratio = (route_path_counts.get("path-c", 0) / total) if total > 0 else None
    path_b_budget_escalation_rate = (
        (path_b_budget_escalated_count / route_path_counts.get("path-b", 0))
        if route_path_counts.get("path-b", 0) > 0
        else None
    )
    core_session_creation_rate = (
        (core_session_created_count / core_escalation_count) if core_escalation_count > 0 else None
    )
    prefix_cache_hit_rate = (prefix_cache_hit_count / total) if total > 0 else None

    tail_churn_rate: Optional[float] = None
    if len(tail_hashes) > 1:
        changed_count = 0
        previous = tail_hashes[0]
        for current in tail_hashes[1:]:
            if current != previous:
                changed_count += 1
            previous = current
        tail_churn_rate = changed_count / float(len(tail_hashes) - 1)

    contract_upgrade_latency_p95_ms = _percentile(contract_upgrade_latencies_ms, 95)
    recovery_context_survival_rate = (
        (recovery_survival_count / recovery_survival_total) if recovery_survival_total > 0 else None
    )

    prompt_slice_status = "ok" if total > 0 else "unknown"
    trigger_status = "ok" if total > 0 else "unknown"
    recovery_slice_status = _classify_numeric(
        recovery_slice_hit_rate,
        warning=0.2,
        critical=0.05,
        higher_is_bad=False,
    )
    if total <= 0:
        recovery_slice_status = "unknown"
    conflict_drop_status = _classify_numeric(
        float(conflict_drop_count) if total > 0 else None,
        warning=max(1.0, float(total) * 0.3),
        critical=max(3.0, float(total) * 0.6),
        higher_is_bad=True,
    )
    if total <= 0:
        conflict_drop_status = "unknown"
    delegation_status = "ok" if total > 0 else "unknown"
    outer_readonly_status = "ok" if total > 0 else "unknown"
    readonly_write_tool_exposure_status = _classify_numeric(
        readonly_write_tool_exposure_rate,
        warning=0.01,
        critical=0.05,
        higher_is_bad=True,
    )
    if readonly_exposure_sample_count <= 0:
        readonly_write_tool_exposure_status = "unknown"
    core_escalation_status = _classify_numeric(
        core_escalation_rate,
        warning=0.8,
        critical=0.95,
        higher_is_bad=True,
    )
    if total <= 0:
        core_escalation_status = "unknown"
    route_distribution_status = "ok" if total > 0 else "unknown"
    path_b_budget_escalation_status = _classify_numeric(
        path_b_budget_escalation_rate,
        warning=0.5,
        critical=0.8,
        higher_is_bad=True,
    )
    if route_path_counts.get("path-b", 0) <= 0:
        path_b_budget_escalation_status = "unknown"
    core_session_creation_status = _classify_numeric(
        core_session_creation_rate,
        warning=0.6,
        critical=0.8,
        higher_is_bad=True,
    )
    if core_escalation_count <= 0:
        core_session_creation_status = "unknown"
    prefix_cache_status = _classify_numeric(
        prefix_cache_hit_rate,
        warning=0.8,
        critical=0.6,
        higher_is_bad=False,
    )
    if total <= 0:
        prefix_cache_status = "unknown"
    tail_churn_status = _classify_numeric(
        tail_churn_rate,
        warning=0.4,
        critical=0.6,
        higher_is_bad=True,
    )
    if total <= 1:
        tail_churn_status = "unknown"
    contract_upgrade_latency_status = _classify_numeric(
        contract_upgrade_latency_p95_ms,
        warning=2_000.0,
        critical=5_000.0,
        higher_is_bad=True,
    )
    recovery_survival_status = _classify_numeric(
        recovery_context_survival_rate,
        warning=0.8,
        critical=0.6,
        higher_is_bad=False,
    )
    if recovery_survival_total <= 0:
        recovery_survival_status = "unknown"

    return {
        "prompt_slice_count_by_layer": {
            "value": average_selected_slice_count,
            "unit": "avg_selected_slice_count",
            "sample_count": total,
            "selected_layer_counts": layer_counts,
            "source": "prompt_injection_events",
            "status": prompt_slice_status,
        },
        "injection_trigger_distribution": {
            "value": float(total),
            "unit": "count",
            "sample_count": total,
            "trigger_counts": trigger_counts,
            "trigger_distribution": trigger_distribution,
            "source": "prompt_injection_events",
            "status": trigger_status,
        },
        "recovery_slice_hit_rate": {
            "value": recovery_slice_hit_rate,
            "unit": "ratio",
            "sample_count": total,
            "hit_count": recovery_hit_count,
            "source": "prompt_injection_events",
            "thresholds": {
                "warning": 0.2,
                "critical": 0.05,
            },
            "status": recovery_slice_status,
        },
        "prompt_conflict_drop_count": {
            "value": float(conflict_drop_count) if total > 0 else None,
            "unit": "count",
            "sample_count": total,
            "source": "prompt_injection_events",
            "thresholds": {
                "warning": max(1.0, float(total) * 0.3),
                "critical": max(3.0, float(total) * 0.6),
            },
            "status": conflict_drop_status,
        },
        "delegation_hit_rate": {
            "value": delegation_hit_rate,
            "unit": "ratio",
            "sample_count": total,
            "hit_count": delegation_hit_count,
            "source": "prompt_injection_events",
            "status": delegation_status,
        },
        "outer_readonly_hit_rate": {
            "value": outer_readonly_hit_rate,
            "unit": "ratio",
            "sample_count": total,
            "hit_count": outer_readonly_hit_count,
            "source": "prompt_injection_events",
            "status": outer_readonly_status,
        },
        "readonly_write_tool_exposure_rate": {
            "value": readonly_write_tool_exposure_rate,
            "unit": "ratio",
            "sample_count": readonly_exposure_sample_count,
            "exposure_count": readonly_write_tool_exposure_count,
            "exposed_slice_count": readonly_write_tool_exposed_slice_count,
            "source": "prompt_injection_events",
            "thresholds": {
                "warning": 0.01,
                "critical": 0.05,
            },
            "status": readonly_write_tool_exposure_status,
        },
        "core_escalation_rate": {
            "value": core_escalation_rate,
            "unit": "ratio",
            "sample_count": total,
            "hit_count": core_escalation_count,
            "source": "prompt_injection_events",
            "thresholds": {
                "warning": 0.8,
                "critical": 0.95,
            },
            "status": core_escalation_status,
        },
        "chat_route_path_distribution": {
            "value": float(total) if total > 0 else None,
            "unit": "count",
            "sample_count": total,
            "path_counts": route_path_counts,
            "path_ratios": {
                "path-a": path_a_route_ratio,
                "path-b": path_b_route_ratio,
                "path-c": path_c_route_ratio,
            },
            "source": "prompt_injection_events",
            "status": route_distribution_status,
        },
        "path_b_budget_escalation_rate": {
            "value": path_b_budget_escalation_rate,
            "unit": "ratio",
            "sample_count": route_path_counts.get("path-b", 0),
            "escalated_count": path_b_budget_escalated_count,
            "source": "prompt_injection_events",
            "thresholds": {
                "warning": 0.5,
                "critical": 0.8,
            },
            "status": path_b_budget_escalation_status,
        },
        "core_session_creation_rate": {
            "value": core_session_creation_rate,
            "unit": "ratio",
            "sample_count": core_escalation_count,
            "created_count": core_session_created_count,
            "source": "prompt_injection_events",
            "thresholds": {
                "warning": 0.6,
                "critical": 0.8,
            },
            "status": core_session_creation_status,
        },
        "prompt_prefix_cache_hit_rate": {
            "value": prefix_cache_hit_rate,
            "unit": "ratio",
            "sample_count": total,
            "hit_count": prefix_cache_hit_count,
            "source": "prompt_injection_events",
            "thresholds": {
                "warning": 0.8,
                "critical": 0.6,
            },
            "status": prefix_cache_status,
        },
        "prompt_tail_churn_rate": {
            "value": tail_churn_rate,
            "unit": "ratio",
            "sample_count": len(tail_hashes),
            "source": "prompt_injection_events",
            "thresholds": {
                "warning": 0.4,
                "critical": 0.6,
            },
            "status": tail_churn_status,
        },
        "contract_upgrade_latency_ms": {
            "value": contract_upgrade_latency_p95_ms,
            "unit": "p95_ms",
            "sample_count": len(contract_upgrade_latencies_ms),
            "source": "prompt_injection_events",
            "thresholds": {
                "warning": 2_000.0,
                "critical": 5_000.0,
            },
            "status": contract_upgrade_latency_status,
        },
        "recovery_context_survival_rate": {
            "value": recovery_context_survival_rate,
            "unit": "ratio",
            "sample_count": recovery_survival_total,
            "survived_count": recovery_survival_count,
            "source": "prompt_injection_events",
            "thresholds": {
                "warning": 0.8,
                "critical": 0.6,
            },
            "status": recovery_survival_status,
        },
    }


def _load_threshold_config(config_file: Path) -> Dict[str, Any]:
    defaults = {
        "max_error_rate": 0.02,
        "max_latency_p95_ms": 1500.0,
        "queue_batch_size": 50,
        "lease_ttl_seconds": 10.0,
        "lease_name": "global_orchestrator",
        "subagent_rollout_percent": 100,
        "fail_open_budget_ratio": 0.15,
    }

    payload = _read_yaml(config_file)
    autonomous = payload.get("autonomous") if isinstance(payload.get("autonomous"), dict) else {}
    release = autonomous.get("release") if isinstance(autonomous.get("release"), dict) else {}
    outbox = autonomous.get("outbox_dispatch") if isinstance(autonomous.get("outbox_dispatch"), dict) else {}
    lease = autonomous.get("lease") if isinstance(autonomous.get("lease"), dict) else {}
    subagent_runtime = autonomous.get("subagent_runtime") if isinstance(autonomous.get("subagent_runtime"), dict) else {}

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
    defaults["lease_name"] = str(lease.get("lease_name") or defaults["lease_name"])
    defaults["subagent_rollout_percent"] = max(
        0,
        min(100, _to_int(subagent_runtime.get("rollout_percent"), defaults["subagent_rollout_percent"])),
    )
    defaults["fail_open_budget_ratio"] = max(
        0.0,
        min(
            1.0,
            _to_float(subagent_runtime.get("fail_open_budget_ratio"), defaults["fail_open_budget_ratio"])
            or defaults["fail_open_budget_ratio"],
        ),
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
    metrics["runtime_rollout"] = _collect_runtime_rollout(
        events,
        configured_rollout_percent=int(thresholds["subagent_rollout_percent"]),
    )
    metrics["runtime_fail_open"] = _collect_runtime_fail_open(
        events,
        fail_open_budget_ratio=float(thresholds["fail_open_budget_ratio"]),
    )
    metrics["runtime_lease"] = _collect_runtime_lease(
        events,
        workflow_db=paths.workflow_db,
        now_dt=now_dt,
        lease_name=str(thresholds["lease_name"]),
        lease_ttl_hint_seconds=float(thresholds["lease_ttl_seconds"]),
    )
    metrics.update(_collect_prompt_injection_quality(events))

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
