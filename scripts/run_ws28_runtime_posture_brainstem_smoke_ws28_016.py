#!/usr/bin/env python3
"""Run WS28-016 runtime posture brainstem heartbeat integration smoke."""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

import apiserver.api_server as api_server


DEFAULT_OUTPUT = Path("scratch/reports/ws28_016_runtime_posture_brainstem_smoke.json")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_unix(path: Path) -> str:
    return str(path).replace("\\", "/")


def _resolve_path(repo_root: Path, candidate: Path) -> Path:
    return candidate if candidate.is_absolute() else repo_root / candidate


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run_ws28_runtime_posture_brainstem_smoke_ws28_016(
    *,
    repo_root: Path,
    output_file: Path = DEFAULT_OUTPUT,
) -> Dict[str, Any]:
    root = repo_root.resolve()
    case_root = root / "scratch" / "runtime" / "ws28_016_runtime_posture_brainstem_smoke" / uuid.uuid4().hex[:12]
    fake_repo = case_root / "repo"
    heartbeat_file = fake_repo / "scratch" / "runtime" / "brainstem_control_plane_heartbeat_ws23_001.json"
    events_file = fake_repo / "logs" / "autonomous" / "events.jsonl"
    events_file.parent.mkdir(parents=True, exist_ok=True)
    events_file.write_text("", encoding="utf-8")

    now = datetime.now(timezone.utc)
    _write_json(
        heartbeat_file,
        {
            "generated_at": now.isoformat(),
            "pid": 52001,
            "tick": 4,
            "mode": "daemon",
            "healthy": True,
            "service_count": 1,
            "unhealthy_services": [],
            "state_file": str((fake_repo / "logs" / "autonomous" / "brainstem_supervisor_state.json").resolve()),
            "spec_file": str((fake_repo / "system" / "brainstem_services.spec").resolve()),
        },
    )

    def _fake_snapshot(*, repo_root: Path, events_limit: int) -> Dict[str, Any]:  # noqa: ARG001
        return {
            "summary": {
                "overall_status": "ok",
                "metric_status": {},
            },
            "metrics": {
                "runtime_rollout": {"value": 0.7, "status": "ok"},
                "runtime_fail_open": {"value": 0.0, "status": "ok"},
                "runtime_lease": {"value": 8.0, "status": "ok", "state": "healthy"},
                "queue_depth": {"value": 0, "status": "ok"},
                "lock_status": {"state": "healthy", "status": "ok"},
                "disk_watermark_ratio": {"value": 0.1, "status": "ok"},
                "error_rate": {"value": 0.0, "status": "ok"},
                "latency_p95_ms": {"value": 120.0, "status": "ok"},
            },
            "threshold_profile": {"max_error_rate": 0.2},
            "sources": {
                "events_file": _to_unix(events_file),
                "workflow_db": _to_unix(fake_repo / "logs" / "autonomous" / "workflow.db"),
                "global_mutex_state": _to_unix(fake_repo / "logs" / "runtime" / "global_mutex_lease.json"),
                "autonomous_config": _to_unix(fake_repo / "autonomous" / "config" / "autonomous_config.yaml"),
            },
        }

    from scripts import export_slo_snapshot

    with (
        patch.object(api_server, "_ops_repo_root", lambda: fake_repo),
        patch.object(export_slo_snapshot, "build_snapshot", _fake_snapshot),
    ):
        response_payload = asyncio.run(api_server.get_ops_runtime_posture(events_limit=128))

    response_data = response_payload.get("data") if isinstance(response_payload.get("data"), dict) else {}
    summary = response_data.get("summary") if isinstance(response_data.get("summary"), dict) else {}
    brainstem = (
        response_data.get("brainstem_control_plane")
        if isinstance(response_data.get("brainstem_control_plane"), dict)
        else {}
    )

    checks = {
        "handler_returned_payload": isinstance(response_payload, dict),
        "payload_status_success": str(response_payload.get("status") or "") == "success",
        "brainstem_block_present": bool(brainstem),
        "brainstem_status_ok": str(brainstem.get("status") or "") == "ok",
        "summary_brainstem_status_ok": str(summary.get("brainstem_control_plane_status") or "") == "ok",
        "source_reports_contains_heartbeat": any(
            str(path).endswith("brainstem_control_plane_heartbeat_ws23_001.json")
            for path in (response_payload.get("source_reports") or [])
        ),
    }
    passed = all(checks.values())

    report: Dict[str, Any] = {
        "task_id": "NGA-WS28-016",
        "scenario": "runtime_posture_brainstem_heartbeat_smoke",
        "generated_at": _utc_now(),
        "repo_root": _to_unix(root),
        "passed": passed,
        "checks": checks,
        "sample": {
            "severity": response_payload.get("severity"),
            "summary": summary,
            "brainstem_control_plane": brainstem,
        },
    }

    output = _resolve_path(root, output_file)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["output_file"] = _to_unix(output)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run WS28-016 runtime posture brainstem heartbeat smoke")
    parser.add_argument("--repo-root", type=Path, default=Path("."), help="Repository root")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output JSON report path")
    parser.add_argument("--strict", action="store_true", help="Return non-zero when checks fail")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_ws28_runtime_posture_brainstem_smoke_ws28_016(
        repo_root=args.repo_root,
        output_file=args.output,
    )
    print(
        json.dumps(
            {
                "passed": bool(report.get("passed")),
                "checks": report.get("checks", {}),
                "output": report.get("output_file"),
            },
            ensure_ascii=False,
        )
    )
    if args.strict and not bool(report.get("passed")):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
