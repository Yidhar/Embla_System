from __future__ import annotations

import json
from pathlib import Path

import apiserver.api_server as api_server


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n"
    path.write_text(content, encoding="utf-8")


def test_ops_build_vision_multimodal_summary_counts_events(tmp_path: Path) -> None:
    events_file = tmp_path / "logs" / "autonomous" / "events.jsonl"
    _write_jsonl(
        events_file,
        [
            {
                "timestamp": "2026-03-01T10:00:00+00:00",
                "event_type": "VisionMultimodalQASucceeded",
                "payload": {"model": "gpt-4o-mini"},
            },
            {
                "timestamp": "2026-03-01T10:01:00+00:00",
                "event_type": "VisionMultimodalQAFallback",
                "payload": {"fallback_reason": "llm_unavailable"},
            },
            {
                "timestamp": "2026-03-01T10:02:00+00:00",
                "event_type": "VisionMultimodalQAError",
                "payload": {"fallback_reason": "llm_error", "llm_error": "timeout"},
            },
        ],
    )

    summary = api_server._ops_build_vision_multimodal_summary(events_file=events_file, limit=200)
    assert summary["status"] == "warning"
    assert summary["success_count"] == 1
    assert summary["fallback_count"] == 1
    assert summary["error_count"] == 1
    assert summary["total_count"] == 3
    assert summary["reason_code"] == "VISION_MULTIMODAL_ERROR_PRESENT"


def test_ops_runtime_and_incidents_include_vision_multimodal(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path
    events_file = repo_root / "logs" / "autonomous" / "events.jsonl"
    _write_jsonl(
        events_file,
        [
            {
                "timestamp": "2026-03-01T11:00:00+00:00",
                "event_type": "VisionMultimodalQASucceeded",
                "payload": {"model": "gpt-4o-mini", "base_url": "https://example.com/v1"},
            },
            {
                "timestamp": "2026-03-01T11:01:00+00:00",
                "event_type": "VisionMultimodalQAError",
                "payload": {"fallback_reason": "llm_error", "llm_error": "timeout"},
            },
        ],
    )

    monkeypatch.setattr(api_server, "_ops_repo_root", lambda: repo_root)

    from scripts import export_slo_snapshot

    monkeypatch.setattr(
        export_slo_snapshot,
        "build_snapshot",
        lambda **_kwargs: {
            "summary": {"overall_status": "ok", "metric_status": {}},
            "metrics": {
                "runtime_rollout": {"status": "ok", "value": 1.0},
                "runtime_fail_open": {"status": "ok", "value": 0.0},
                "runtime_lease": {"status": "ok", "value": 1.0},
                "queue_depth": {"status": "ok", "value": 0},
                "lock_status": {"status": "ok", "value": "healthy"},
                "disk_watermark_ratio": {"status": "ok", "value": 0.1},
                "error_rate": {"status": "ok", "value": 0.0},
                "latency_p95_ms": {"status": "ok", "value": 100},
            },
            "threshold_profile": {},
            "sources": {
                "events_file": str(events_file),
                "events_db": str(events_file.with_name("events_topics.db")),
                "workflow_db": str(repo_root / "logs" / "autonomous" / "workflow.db"),
                "global_mutex_state": str(repo_root / "scratch" / "runtime" / "global_mutex_state.json"),
                "autonomous_config": str(repo_root / "config.json"),
                "events_scanned": 2,
            },
        },
    )

    runtime_payload = api_server._ops_build_runtime_posture_payload(events_limit=200)
    vision_summary = runtime_payload["data"]["vision_multimodal"]
    assert vision_summary["total_count"] == 2
    assert runtime_payload["data"]["summary"]["vision_multimodal_status"] == "warning"
    assert runtime_payload["data"]["metrics"]["vision_multimodal_fallback_ratio"]["status"] == "warning"

    incidents_payload = api_server._ops_build_incidents_latest_payload(limit=50)
    prompt_safety = incidents_payload["data"]["summary"]["runtime_prompt_safety"]
    assert "vision_multimodal" in prompt_safety
    assert prompt_safety["vision_multimodal"]["error_count"] == 1
    assert incidents_payload["data"]["event_counters"]["VisionMultimodalQAError"] == 1
