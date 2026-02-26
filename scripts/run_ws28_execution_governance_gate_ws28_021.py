#!/usr/bin/env python3
"""Run WS28-021 execution-governance gate based on runtime posture/incidents summaries."""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


DEFAULT_OUTPUT = Path("scratch/reports/ws28_execution_governance_gate_ws28_021.json")
DEFAULT_RUNTIME_POSTURE_OUTPUT = Path("scratch/reports/ws28_execution_governance_runtime_posture_ws28_021.json")
DEFAULT_INCIDENTS_OUTPUT = Path("scratch/reports/ws28_execution_governance_incidents_ws28_021.json")


def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_unix_path(path: Path) -> str:
    return str(path).replace("\\", "/")


def _resolve_path(repo_root: Path, path: Path) -> Path:
    return path if path.is_absolute() else repo_root / path


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _safe_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def run_ws28_execution_governance_gate_ws28_021(
    *,
    repo_root: Path,
    output_file: Path = DEFAULT_OUTPUT,
    runtime_posture_output: Path = DEFAULT_RUNTIME_POSTURE_OUTPUT,
    incidents_output: Path = DEFAULT_INCIDENTS_OUTPUT,
    events_limit: int = 5000,
    incidents_limit: int = 50,
    max_warning_ratio: float = 0.30,
    max_rejection_ratio: float = 0.20,
) -> Dict[str, Any]:
    started = time.time()
    root = repo_root.resolve()
    runtime_output_path = _resolve_path(root, runtime_posture_output)
    incidents_output_path = _resolve_path(root, incidents_output)
    output_path = _resolve_path(root, output_file)

    import apiserver.api_server as api_server

    original_repo_root = api_server._ops_repo_root  # noqa: SLF001
    try:
        api_server._ops_repo_root = lambda: root  # type: ignore[assignment]  # noqa: SLF001
        runtime_posture_payload = api_server._ops_build_runtime_posture_payload(events_limit=max(1, int(events_limit)))  # noqa: SLF001
        incidents_payload = api_server._ops_build_incidents_latest_payload(limit=max(1, int(incidents_limit)))  # noqa: SLF001
    finally:
        api_server._ops_repo_root = original_repo_root  # type: ignore[assignment]  # noqa: SLF001

    _write_json(runtime_output_path, runtime_posture_payload)
    _write_json(incidents_output_path, incidents_payload)

    runtime_data = runtime_posture_payload.get("data") if isinstance(runtime_posture_payload.get("data"), dict) else {}
    runtime_summary = runtime_data.get("summary") if isinstance(runtime_data.get("summary"), dict) else {}
    runtime_governance = (
        runtime_data.get("execution_bridge_governance")
        if isinstance(runtime_data.get("execution_bridge_governance"), dict)
        else {}
    )
    runtime_governance_status = str(
        runtime_summary.get("execution_bridge_governance_status") or runtime_governance.get("status") or "unknown"
    ).strip().lower()

    incidents_data = incidents_payload.get("data") if isinstance(incidents_payload.get("data"), dict) else {}
    incidents_summary = incidents_data.get("summary") if isinstance(incidents_data.get("summary"), dict) else {}
    incidents_governance = (
        incidents_summary.get("execution_bridge_governance")
        if isinstance(incidents_summary.get("execution_bridge_governance"), dict)
        else {}
    )
    incidents_governance_status = str(incidents_governance.get("status") or "unknown").strip().lower()
    critical_issue_count = _safe_int(incidents_governance.get("governed_critical_count"), default=0)

    warning_ratio = _safe_float(runtime_governance.get("governed_warning_ratio"))
    rejection_ratio = _safe_float(runtime_governance.get("rejection_ratio"))

    checks = {
        "runtime_posture_payload_success": str(runtime_posture_payload.get("status") or "") == "success",
        "incidents_payload_success": str(incidents_payload.get("status") or "") == "success",
        "runtime_governance_status_not_critical": runtime_governance_status != "critical",
        "incidents_governance_status_not_critical": incidents_governance_status != "critical",
        "critical_governance_issue_count_zero": critical_issue_count == 0,
        "governance_warning_ratio_within_budget": warning_ratio is None or warning_ratio <= float(max_warning_ratio),
        "governance_rejection_ratio_within_budget": rejection_ratio is None or rejection_ratio <= float(max_rejection_ratio),
    }
    passed = all(bool(value) for value in checks.values())
    failed_checks = [key for key, value in checks.items() if not bool(value)]

    report: Dict[str, Any] = {
        "task_id": "NGA-WS28-021",
        "scenario": "execution_bridge_governance_gate_ws28_021",
        "generated_at": _utc_iso_now(),
        "repo_root": _to_unix_path(root),
        "passed": passed,
        "checks": checks,
        "failed_checks": failed_checks,
        "thresholds": {
            "max_warning_ratio": float(max_warning_ratio),
            "max_rejection_ratio": float(max_rejection_ratio),
        },
        "governance": {
            "runtime_status": runtime_governance_status,
            "incidents_status": incidents_governance_status,
            "critical_issue_count": critical_issue_count,
            "warning_ratio": warning_ratio,
            "rejection_ratio": rejection_ratio,
            "reason_codes": list(runtime_governance.get("reason_codes") or []),
        },
        "outputs": {
            "runtime_posture_output": _to_unix_path(runtime_output_path),
            "incidents_output": _to_unix_path(incidents_output_path),
        },
        "elapsed_seconds": round(time.time() - started, 4),
    }
    _write_json(output_path, report)
    report["output_file"] = _to_unix_path(output_path)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run WS28-021 execution governance gate")
    parser.add_argument("--repo-root", type=Path, default=Path("."), help="Repository root")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Gate output JSON path")
    parser.add_argument(
        "--runtime-posture-output",
        type=Path,
        default=DEFAULT_RUNTIME_POSTURE_OUTPUT,
        help="Runtime posture snapshot output path",
    )
    parser.add_argument(
        "--incidents-output",
        type=Path,
        default=DEFAULT_INCIDENTS_OUTPUT,
        help="Incidents snapshot output path",
    )
    parser.add_argument("--events-limit", type=int, default=5000, help="Events limit for runtime posture collector")
    parser.add_argument("--incidents-limit", type=int, default=50, help="Incidents limit for incidents collector")
    parser.add_argument(
        "--max-warning-ratio",
        type=float,
        default=0.30,
        help="Maximum accepted governance warning ratio",
    )
    parser.add_argument(
        "--max-rejection-ratio",
        type=float,
        default=0.20,
        help="Maximum accepted governance rejection ratio",
    )
    parser.add_argument("--strict", action="store_true", help="Return non-zero when checks fail")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_ws28_execution_governance_gate_ws28_021(
        repo_root=args.repo_root,
        output_file=args.output,
        runtime_posture_output=args.runtime_posture_output,
        incidents_output=args.incidents_output,
        events_limit=max(1, int(args.events_limit)),
        incidents_limit=max(1, int(args.incidents_limit)),
        max_warning_ratio=max(0.0, float(args.max_warning_ratio)),
        max_rejection_ratio=max(0.0, float(args.max_rejection_ratio)),
    )
    print(
        json.dumps(
            {
                "passed": bool(report.get("passed")),
                "failed_checks": report.get("failed_checks", []),
                "output": report.get("output_file", ""),
            },
            ensure_ascii=False,
        )
    )
    if args.strict and not bool(report.get("passed")):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
