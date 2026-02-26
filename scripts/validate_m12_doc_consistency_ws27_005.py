#!/usr/bin/env python3
"""Validate WS27-005 M12 doc consistency closure."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Sequence

from scripts.audit_task_status_drift import run_audit
from system.doc_consistency import validate_execution_board_consistency


DEFAULT_OUTPUT = Path("scratch/reports/ws27_m12_doc_consistency_ws27_005.json")
DEFAULT_BOARD = Path("doc/task/09-execution-board.csv")
DEFAULT_BACKLOG = Path("doc/task/99-task-backlog.csv")
DEFAULT_PHASE3_BOARD = Path("doc/task/23-phase3-full-execution-board.csv")
DEFAULT_RISK_LEDGER = Path("doc/task/08-risk-closure-ledger.md")
DEFAULT_PHASE3_TASK_LIST = Path("doc/task/23-phase3-full-target-task-list.md")

CORE_DOC_PATHS: Sequence[Path] = (
    Path("doc/00-omni-operator-architecture.md"),
    Path("doc/10-brainstem-layer-modules.md"),
    Path("doc/11-brain-layer-modules.md"),
    Path("doc/12-limbs-layer-modules.md"),
    Path("doc/13-security-blindspots-and-hardening.md"),
    DEFAULT_PHASE3_TASK_LIST,
)

WS27_IMPLEMENTATION_DOC_PATHS: Sequence[Path] = (
    Path("doc/task/implementation/NGA-WS27-001-implementation.md"),
    Path("doc/task/implementation/NGA-WS27-002-implementation.md"),
    Path("doc/task/implementation/NGA-WS27-003-implementation.md"),
    Path("doc/task/implementation/NGA-WS27-004-implementation.md"),
)

WS27_RUNBOOK_PATHS: Sequence[Path] = (
    Path("doc/task/runbooks/release_m12_cutover_rollback_onepager_ws27_002.md"),
    Path("doc/task/runbooks/release_m12_oob_repair_drill_onepager_ws27_003.md"),
    Path("doc/task/runbooks/release_m12_full_chain_m0_m12_onepager_ws27_004.md"),
)

PHASE3_REQUIRED_MARKERS: Sequence[str] = (
    "NGA-WS27-001` 已落地",
    "NGA-WS27-002` 已落地",
    "NGA-WS27-003` 已落地",
    "NGA-WS27-004` 已落地",
)


def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_unix_path(path: Path) -> str:
    return str(path).replace("\\", "/")


def _resolve_path(repo_root: Path, candidate: Path) -> Path:
    return candidate if candidate.is_absolute() else repo_root / candidate


def _missing_paths(*, repo_root: Path, candidates: Sequence[Path]) -> list[str]:
    missing = []
    for path in candidates:
        resolved = _resolve_path(repo_root, path)
        if not resolved.exists():
            missing.append(_to_unix_path(path))
    return missing


def _missing_markers(*, repo_root: Path, phase3_task_list: Path, markers: Sequence[str]) -> list[str]:
    target = _resolve_path(repo_root, phase3_task_list)
    if not target.exists():
        return list(markers)
    content = target.read_text(encoding="utf-8")
    return [marker for marker in markers if marker not in content]


def run_validate_m12_doc_consistency_ws27_005(
    *,
    repo_root: Path,
    board_file: Path = DEFAULT_BOARD,
    backlog_file: Path = DEFAULT_BACKLOG,
    phase3_board_file: Path = DEFAULT_PHASE3_BOARD,
    risk_ledger_file: Path = DEFAULT_RISK_LEDGER,
    phase3_task_list: Path = DEFAULT_PHASE3_TASK_LIST,
    output_file: Path = DEFAULT_OUTPUT,
) -> Dict[str, Any]:
    root = repo_root.resolve()

    legacy_board_report = validate_execution_board_consistency(
        board_file=_resolve_path(root, board_file),
        repo_root=root,
        risk_ledger_file=_resolve_path(root, risk_ledger_file),
    )
    phase3_board_report = validate_execution_board_consistency(
        board_file=_resolve_path(root, phase3_board_file),
        repo_root=root,
        risk_ledger_file=_resolve_path(root, risk_ledger_file),
    )

    missing_core_docs = _missing_paths(repo_root=root, candidates=CORE_DOC_PATHS)
    missing_impl_docs = _missing_paths(repo_root=root, candidates=WS27_IMPLEMENTATION_DOC_PATHS)
    missing_runbooks = _missing_paths(repo_root=root, candidates=WS27_RUNBOOK_PATHS)
    missing_phase3_markers = _missing_markers(
        repo_root=root,
        phase3_task_list=phase3_task_list,
        markers=PHASE3_REQUIRED_MARKERS,
    )
    status_audit_error = ""
    status_audit_summary: Dict[str, int] = {}
    status_audit_samples: Dict[str, Any] = {}
    legacy_board_backlog_status_aligned = False
    legacy_done_has_dated_verification = False
    legacy_ws_docs_status_synced_with_board = False
    resolved_backlog = _resolve_path(root, backlog_file)
    if resolved_backlog.exists():
        status_audit_report = run_audit(
            board_file=_resolve_path(root, board_file),
            backlog_file=resolved_backlog,
            ws_doc_glob="doc/task/[1-2][0-9]-ws-*.md",
            demote_undated_done=False,
            apply=False,
        )
        summary_payload = status_audit_report.get("summary")
        if isinstance(summary_payload, dict):
            status_audit_summary = {str(k): int(v) for k, v in summary_payload.items()}
        legacy_board_backlog_status_aligned = (
            int(status_audit_summary.get("board_vs_backlog_mismatch_count", 0)) == 0
            and int(status_audit_summary.get("missing_in_backlog_count", 0)) == 0
        )
        legacy_done_has_dated_verification = int(status_audit_summary.get("done_without_dated_note_count", 0)) == 0
        legacy_ws_docs_status_synced_with_board = int(status_audit_summary.get("ws_doc_drift_count", 0)) == 0
        status_audit_samples = {
            "board_vs_backlog_mismatch_sample": list(status_audit_report.get("board_vs_backlog_mismatch", [])[:20]),
            "done_without_dated_note_sample": list(status_audit_report.get("done_without_dated_note", [])[:20]),
            "ws_doc_drift_sample": list(status_audit_report.get("ws_doc_drift", [])[:20]),
        }
    else:
        status_audit_error = f"missing file: {_to_unix_path(resolved_backlog)}"

    checks = {
        "execution_board_has_no_errors": (
            int(legacy_board_report.error_count) == 0 and int(phase3_board_report.error_count) == 0
        ),
        "legacy_execution_board_has_no_errors": int(legacy_board_report.error_count) == 0,
        "phase3_execution_board_has_no_errors": int(phase3_board_report.error_count) == 0,
        "core_docs_present": len(missing_core_docs) == 0,
        "ws27_implementation_docs_present": len(missing_impl_docs) == 0,
        "ws27_runbooks_present": len(missing_runbooks) == 0,
        "phase3_snapshot_markers_present": len(missing_phase3_markers) == 0,
        "legacy_board_backlog_status_aligned": legacy_board_backlog_status_aligned,
        "legacy_done_has_dated_verification": legacy_done_has_dated_verification,
        "legacy_ws_docs_status_synced_with_board": legacy_ws_docs_status_synced_with_board,
    }
    passed = all(checks.values())

    report: Dict[str, Any] = {
        "task_id": "NGA-WS27-005",
        "scenario": "m12_doc_consistency_closure_ws27_005",
        "generated_at": _utc_iso_now(),
        "repo_root": _to_unix_path(root),
        "passed": passed,
        "checks": checks,
        "missing_items": {
            "core_docs": missing_core_docs,
            "ws27_implementation_docs": missing_impl_docs,
            "ws27_runbooks": missing_runbooks,
            "phase3_snapshot_markers": missing_phase3_markers,
            "legacy_backlog_file": ([] if resolved_backlog.exists() else [_to_unix_path(backlog_file)]),
        },
        "board_consistency_summary": {
            "legacy_board": {
                "board_file": _to_unix_path(_resolve_path(root, board_file)),
                "checked_rows": int(legacy_board_report.checked_rows),
                "issue_count": int(legacy_board_report.issue_count),
                "error_count": int(legacy_board_report.error_count),
                "warn_count": int(legacy_board_report.warn_count),
                "issues_sample": list(legacy_board_report.issues[:20]),
            },
            "phase3_board": {
                "board_file": _to_unix_path(_resolve_path(root, phase3_board_file)),
                "checked_rows": int(phase3_board_report.checked_rows),
                "issue_count": int(phase3_board_report.issue_count),
                "error_count": int(phase3_board_report.error_count),
                "warn_count": int(phase3_board_report.warn_count),
                "issues_sample": list(phase3_board_report.issues[:20]),
            },
            "combined": {
                "checked_rows": int(legacy_board_report.checked_rows + phase3_board_report.checked_rows),
                "issue_count": int(legacy_board_report.issue_count + phase3_board_report.issue_count),
                "error_count": int(legacy_board_report.error_count + phase3_board_report.error_count),
                "warn_count": int(legacy_board_report.warn_count + phase3_board_report.warn_count),
            },
        },
        "status_audit": {
            "error": status_audit_error,
            "summary": status_audit_summary,
            "samples": status_audit_samples,
        },
    }

    output = _resolve_path(root, output_file)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["output_file"] = _to_unix_path(output)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate WS27-005 M12 doc consistency closure")
    parser.add_argument("--repo-root", type=Path, default=Path("."), help="Repository root")
    parser.add_argument("--board", type=Path, default=DEFAULT_BOARD, help="Execution board CSV path")
    parser.add_argument("--backlog", type=Path, default=DEFAULT_BACKLOG, help="Task backlog CSV path")
    parser.add_argument(
        "--phase3-board",
        type=Path,
        default=DEFAULT_PHASE3_BOARD,
        help="Phase3 WS23-WS27 execution board CSV path",
    )
    parser.add_argument("--risk-ledger", type=Path, default=DEFAULT_RISK_LEDGER, help="Risk closure ledger path")
    parser.add_argument(
        "--phase3-task-list",
        type=Path,
        default=DEFAULT_PHASE3_TASK_LIST,
        help="Phase3 task list markdown path",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output JSON report path")
    parser.add_argument("--strict", action="store_true", help="Return non-zero when checks fail")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_validate_m12_doc_consistency_ws27_005(
        repo_root=args.repo_root,
        board_file=args.board,
        backlog_file=args.backlog,
        phase3_board_file=args.phase3_board,
        risk_ledger_file=args.risk_ledger,
        phase3_task_list=args.phase3_task_list,
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
