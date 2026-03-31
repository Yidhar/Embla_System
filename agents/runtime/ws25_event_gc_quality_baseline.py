"""WS25-005 Event/GC quality baseline harness."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import system.artifact_store as artifact_store_module
from core.event_bus import EventStore
from system.artifact_store import ArtifactStore, ArtifactStoreConfig
from system.gc_eval_suite import DEFAULT_GC_QUALITY_THRESHOLDS, evaluate_gc_quality, validate_gc_quality_report
from system.tool_contract import build_tool_result_with_artifact


@dataclass(frozen=True)
class WS25EventGCQualityConfig:
    replay_event_count: int = 3
    gc_iterations: int = 3


def _run_replay_idempotency_drill(case_root: Path, *, replay_event_count: int) -> Dict[str, Any]:
    event_store = EventStore(file_path=case_root / "events.jsonl")
    expected_count = max(1, int(replay_event_count))
    for idx in range(expected_count):
        event_store.publish(
            "tool.replay.drill",
            {
                "workflow_id": f"wf-ws25-{idx:03d}",
                "trace_id": f"trace-ws25-{idx:03d}",
                "error_code": "ERR_WS25_REPLAY",
                "path": "/srv/ws25/replay.py",
                "seq": idx,
            },
            event_type="ReplayDrillEvent",
            source="agents.runtime.ws25.quality",
            idempotency_key=f"ws25-replay-{idx:03d}",
        )

    side_effects: list[str] = []
    sub = event_store.subscribe("tool.replay.*", lambda event: side_effects.append(str(event.get("event_id") or "")))
    try:
        first = event_store.replay_dispatch(
            anchor_id="ws25-quality-replay-consumer",
            topic_pattern="tool.replay.*",
            from_seq=1,
            limit=100,
        )
        second = event_store.replay_dispatch(
            anchor_id="ws25-quality-replay-consumer",
            topic_pattern="tool.replay.*",
            from_seq=1,
            limit=100,
        )
        anchor = event_store.get_replay_anchor("ws25-quality-replay-consumer")
    finally:
        event_store.unsubscribe(sub)

    checks = {
        "first_dispatch_matches_expected": first.dispatched_count == expected_count,
        "second_dispatch_zero": second.dispatched_count == 0,
        "second_dedupe_hit": second.deduped_count >= expected_count,
        "no_failed_delivery": first.failed_count == 0 and second.failed_count == 0,
        "side_effect_once": len(side_effects) == expected_count,
        "anchor_advanced": int(anchor.get("last_seq") or 0) >= expected_count,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "first": {
            "scanned_count": first.scanned_count,
            "dispatched_count": first.dispatched_count,
            "deduped_count": first.deduped_count,
            "failed_count": first.failed_count,
            "last_seq": first.last_seq,
        },
        "second": {
            "scanned_count": second.scanned_count,
            "dispatched_count": second.dispatched_count,
            "deduped_count": second.deduped_count,
            "failed_count": second.failed_count,
            "last_seq": second.last_seq,
        },
        "side_effect_count": len(side_effects),
        "anchor": anchor,
    }


def _run_critical_evidence_contract_drill(case_root: Path) -> Dict[str, Any]:
    artifact_store = ArtifactStore(
        ArtifactStoreConfig(
            artifact_root=case_root / "artifacts",
            max_total_size_mb=64,
            max_single_artifact_mb=16,
            max_artifact_count=256,
        )
    )
    previous_store = getattr(artifact_store_module, "_artifact_store", None)
    artifact_store_module._artifact_store = artifact_store
    try:
        payload = {
            "records": [
                {
                    "trace_id": f"trace-ws25-evidence-{idx:04d}",
                    "error_code": "ERR_WS25_TIMEOUT",
                    "path": "/srv/ws25/service.py",
                    "message": "timeout while replaying event stream",
                }
                for idx in range(500)
            ]
        }
        raw_output = json.dumps(payload, ensure_ascii=False)
        envelope = build_tool_result_with_artifact(
            call_id="call_ws25_critical_evidence",
            trace_id="trace_ws25_critical_evidence",
            tool_name="run_cmd",
            raw_output=raw_output,
            content_type="application/json",
        )
    finally:
        artifact_store_module._artifact_store = previous_store

    critical = envelope.critical_evidence if isinstance(envelope.critical_evidence, dict) else {}
    trace_ids = [str(item) for item in critical.get("trace_ids", [])]
    error_codes = [str(item) for item in critical.get("error_codes", [])]
    paths = [str(item) for item in critical.get("paths", [])]
    hints = [str(item) for item in (envelope.fetch_hints or [])]
    checks = {
        "artifact_created": bool(envelope.forensic_artifact_ref),
        "is_truncated": bool(envelope.truncated),
        "trace_ids_preserved": len(trace_ids) > 0,
        "error_codes_preserved": len(error_codes) > 0,
        "paths_preserved": len(paths) > 0,
        "trace_hint_present": any(hint.startswith("grep:trace-ws25-evidence-") for hint in hints),
        "error_hint_present": any("ERR_WS25_TIMEOUT" in hint for hint in hints),
        "path_hint_present": any("/srv/ws25/service.py" in hint for hint in hints),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "critical_evidence": critical,
        "fetch_hints": hints,
        "forensic_artifact_ref": envelope.forensic_artifact_ref,
        "raw_result_ref": envelope.raw_result_ref,
    }


def run_ws25_event_gc_quality_baseline(
    *,
    scratch_root: Path = Path("scratch/ws25_event_gc_quality_baseline"),
    report_file: Path = Path("scratch/reports/ws25_event_gc_quality_baseline.json"),
    config: WS25EventGCQualityConfig = WS25EventGCQualityConfig(),
) -> Dict[str, Any]:
    case_id = uuid.uuid4().hex[:10]
    case_root = scratch_root / case_id
    case_root.mkdir(parents=True, exist_ok=True)
    report_file.parent.mkdir(parents=True, exist_ok=True)

    started_at = time.time()
    replay_result = _run_replay_idempotency_drill(
        case_root,
        replay_event_count=max(1, int(config.replay_event_count)),
    )
    evidence_result = _run_critical_evidence_contract_drill(case_root)

    gc_report = evaluate_gc_quality(iterations=max(1, int(config.gc_iterations)))
    gc_violations = validate_gc_quality_report(gc_report, DEFAULT_GC_QUALITY_THRESHOLDS)
    gc_result = {
        "passed": len(gc_violations) == 0,
        "thresholds": DEFAULT_GC_QUALITY_THRESHOLDS.to_dict(),
        "violations": list(gc_violations),
        "report": gc_report.to_dict(),
    }

    checks = {
        "replay_idempotency": bool(replay_result.get("passed")),
        "critical_evidence_preservation": bool(evidence_result.get("passed")),
        "gc_quality_thresholds": bool(gc_result.get("passed")),
    }
    passed = all(checks.values())
    report: Dict[str, Any] = {
        "task_id": "NGA-WS25-005",
        "scenario": "event_gc_quality_baseline",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "case_root": str(case_root).replace("\\", "/"),
        "report_file": str(report_file).replace("\\", "/"),
        "elapsed_seconds": round(time.time() - started_at, 4),
        "passed": passed,
        "checks": checks,
        "replay_result": replay_result,
        "critical_evidence_result": evidence_result,
        "gc_quality_result": gc_result,
    }
    report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


__all__ = ["WS25EventGCQualityConfig", "run_ws25_event_gc_quality_baseline"]
