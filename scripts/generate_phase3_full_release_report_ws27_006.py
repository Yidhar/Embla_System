#!/usr/bin/env python3
"""Generate WS27-006 Phase3 Full release report and signoff template."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


DEFAULT_FULL_CHAIN_REPORT = Path("scratch/reports/release_closure_chain_full_m0_m12_result.json")
DEFAULT_DOC_CONSISTENCY_REPORT = Path("scratch/reports/ws27_m12_doc_consistency_ws27_005.json")
DEFAULT_WS27_ENDURANCE_REPORT = Path("scratch/reports/ws27_72h_endurance_ws27_001.json")
DEFAULT_WS27_WALLCLOCK_REPORT = Path("scratch/reports/ws27_72h_wallclock_acceptance_ws27_001.json")
DEFAULT_WS27_CUTOVER_STATUS_REPORT = Path("scratch/reports/ws27_subagent_cutover_status_ws27_002.json")
DEFAULT_WS27_OOB_REPORT = Path("scratch/reports/ws27_oob_repair_drill_ws27_003.json")
DEFAULT_OUTPUT_JSON = Path("scratch/reports/phase3_full_release_report_ws27_006.json")
DEFAULT_OUTPUT_MARKDOWN = Path("scratch/reports/phase3_full_release_signoff_ws27_006.md")

DEFAULT_HARD_GOVERNANCE_REASON_CODES = (
    "SEMANTIC_TOOLCHAIN_VIOLATION",
    "ROLE_PATH_VIOLATION",
    "MISSING_PATCH_INTENT",
    "FORCED_SUBTASK_ERROR",
    "EXECUTION_BRIDGE_REJECTED",
    "EXECUTION_BRIDGE_GOVERNANCE_CRITICAL",
)
DEFAULT_SOFT_GOVERNANCE_REASON_CODES = (
    "ROLE_EXECUTOR_GUARD_WARNING",
    "ROLE_EXECUTOR_GUARD_OK",
    "EXECUTION_BRIDGE_GOVERNANCE_WARNING",
    "EXECUTION_BRIDGE_GOVERNANCE_OK",
    "EXECUTION_BRIDGE_GOVERNANCE_UNKNOWN",
)


def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_unix_path(path: Path) -> str:
    return str(path).replace("\\", "/")


def _resolve_path(repo_root: Path, candidate: Path) -> Path:
    return candidate if candidate.is_absolute() else repo_root / candidate


def _read_json_if_exists(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _build_signoff_markdown(
    *,
    generated_at: str,
    release_candidate: str,
    checks: Dict[str, bool],
    report_paths: Dict[str, str],
    governance_reason_code_policy: Dict[str, Any],
    governance_reason_code_evaluation: Dict[str, Any],
    verdict_passed: bool,
    require_wallclock_acceptance: bool,
) -> str:
    verdict = "PASS" if verdict_passed else "FAIL"
    lines = [
        "# Phase3 Full 放行签署模板（WS27-006）",
        "",
        f"- 生成时间（UTC）: `{generated_at}`",
        f"- 发布候选标识: `{release_candidate}`",
        f"- 放行结论: `{verdict}`",
        "",
        "## 门禁检查",
        "",
        "| 检查项 | 结果 |",
        "|---|---|",
    ]
    for check_id, passed in checks.items():
        lines.append(f"| `{check_id}` | `{'PASS' if bool(passed) else 'FAIL'}` |")

    lines.extend(
        [
            "",
            "## 报告路径",
            "",
            f"- `full_chain_report`: `{report_paths['full_chain_report']}`",
            f"- `doc_consistency_report`: `{report_paths['doc_consistency_report']}`",
            f"- `ws27_endurance_report`: `{report_paths['ws27_endurance_report']}`",
            f"- `ws27_wallclock_report`: `{report_paths['ws27_wallclock_report']}`",
            f"- `ws27_cutover_status_report`: `{report_paths['ws27_cutover_status_report']}`",
            f"- `ws27_oob_report`: `{report_paths['ws27_oob_report']}`",
            "",
            "## 签署策略",
            "",
            f"- `require_wallclock_acceptance`: `{'true' if require_wallclock_acceptance else 'false'}`",
            "- `governance_reason_codes`: `hard/soft` 分层阻断策略启用",
            "",
            "## Governance Reason-Code 策略",
            "",
            f"- `hard_policy_codes`: `{', '.join(list(governance_reason_code_policy.get('hard', []) or []))}`",
            f"- `soft_policy_codes`: `{', '.join(list(governance_reason_code_policy.get('soft', []) or []))}`",
            f"- `observed_codes`: `{', '.join(list(governance_reason_code_evaluation.get('observed', []) or []))}`",
            f"- `hard_hits`: `{', '.join(list(governance_reason_code_evaluation.get('hard_hits', []) or []))}`",
            f"- `soft_hits`: `{', '.join(list(governance_reason_code_evaluation.get('soft_hits', []) or []))}`",
            f"- `unknown_hits`: `{', '.join(list(governance_reason_code_evaluation.get('unknown_hits', []) or []))}`",
            f"- `max_soft_reason_code_count`: `{int(governance_reason_code_evaluation.get('max_soft_reason_code_count') or 0)}`",
            "",
            "## 签署信息",
            "",
            "- 发布负责人（Owner）: ____________________",
            "- 审批人（Approver）: ____________________",
            "- 签署时间（UTC）: ____________________",
            "- 备注: ____________________",
            "",
        ]
    )
    return "\n".join(lines)


def _extract_governance_reason_codes_from_full_chain(full_chain_payload: Dict[str, Any]) -> list[str]:
    group_results = full_chain_payload.get("group_results") if isinstance(full_chain_payload.get("group_results"), dict) else {}
    governance_group = group_results.get("m12_execution_governance") if isinstance(group_results.get("m12_execution_governance"), dict) else {}
    governance = governance_group.get("governance") if isinstance(governance_group.get("governance"), dict) else {}
    codes_raw = governance.get("reason_codes")
    if not isinstance(codes_raw, list):
        return []
    normalized: list[str] = []
    for item in codes_raw:
        code = str(item or "").strip().upper()
        if code:
            normalized.append(code)
    return sorted(set(normalized))


def run_generate_phase3_full_release_report_ws27_006(
    *,
    repo_root: Path,
    release_candidate: str = "phase3-full-m12",
    full_chain_report: Path = DEFAULT_FULL_CHAIN_REPORT,
    doc_consistency_report: Path = DEFAULT_DOC_CONSISTENCY_REPORT,
    ws27_endurance_report: Path = DEFAULT_WS27_ENDURANCE_REPORT,
    ws27_wallclock_report: Path = DEFAULT_WS27_WALLCLOCK_REPORT,
    ws27_cutover_status_report: Path = DEFAULT_WS27_CUTOVER_STATUS_REPORT,
    ws27_oob_report: Path = DEFAULT_WS27_OOB_REPORT,
    output_json: Path = DEFAULT_OUTPUT_JSON,
    output_markdown: Path = DEFAULT_OUTPUT_MARKDOWN,
    require_wallclock_acceptance: bool = False,
    max_soft_reason_code_count: int = 5,
) -> Dict[str, Any]:
    root = repo_root.resolve()
    resolved_paths = {
        "full_chain_report": _resolve_path(root, full_chain_report),
        "doc_consistency_report": _resolve_path(root, doc_consistency_report),
        "ws27_endurance_report": _resolve_path(root, ws27_endurance_report),
        "ws27_wallclock_report": _resolve_path(root, ws27_wallclock_report),
        "ws27_cutover_status_report": _resolve_path(root, ws27_cutover_status_report),
        "ws27_oob_report": _resolve_path(root, ws27_oob_report),
    }

    full_chain_payload = _read_json_if_exists(resolved_paths["full_chain_report"])
    doc_consistency_payload = _read_json_if_exists(resolved_paths["doc_consistency_report"])
    ws27_endurance_payload = _read_json_if_exists(resolved_paths["ws27_endurance_report"])
    ws27_wallclock_payload = _read_json_if_exists(resolved_paths["ws27_wallclock_report"])
    ws27_cutover_status_payload = _read_json_if_exists(resolved_paths["ws27_cutover_status_report"])
    ws27_oob_payload = _read_json_if_exists(resolved_paths["ws27_oob_report"])

    governance_reason_codes = _extract_governance_reason_codes_from_full_chain(full_chain_payload)
    hard_policy = sorted(set(str(code).strip().upper() for code in DEFAULT_HARD_GOVERNANCE_REASON_CODES if str(code).strip()))
    soft_policy = sorted(set(str(code).strip().upper() for code in DEFAULT_SOFT_GOVERNANCE_REASON_CODES if str(code).strip()))
    hard_policy_set = set(hard_policy)
    soft_policy_set = set(soft_policy)
    hard_hits = sorted([code for code in governance_reason_codes if code in hard_policy_set])
    soft_hits = sorted([code for code in governance_reason_codes if code in soft_policy_set])
    unknown_hits = sorted([code for code in governance_reason_codes if code not in hard_policy_set and code not in soft_policy_set])

    checks = {
        "full_chain_passed": bool(full_chain_payload.get("passed")),
        "doc_consistency_passed": bool(doc_consistency_payload.get("passed")),
        "ws27_endurance_passed": bool(ws27_endurance_payload.get("passed")),
        "ws27_wallclock_report_present": resolved_paths["ws27_wallclock_report"].exists(),
        "ws27_wallclock_acceptance_passed": bool(ws27_wallclock_payload.get("passed")),
        "ws27_cutover_status_passed": bool(ws27_cutover_status_payload.get("passed")),
        "ws27_oob_drill_passed": bool(ws27_oob_payload.get("passed")),
        "ws28_governance_hard_reason_codes_absent": len(hard_hits) == 0,
        "ws28_governance_soft_reason_codes_within_budget": len(soft_hits) <= max(0, int(max_soft_reason_code_count)),
        "ws28_governance_unknown_reason_codes_absent": len(unknown_hits) == 0,
    }
    required_path_keys = [
        "full_chain_report",
        "doc_consistency_report",
        "ws27_endurance_report",
        "ws27_cutover_status_report",
        "ws27_oob_report",
    ]
    if require_wallclock_acceptance:
        required_path_keys.append("ws27_wallclock_report")
    required_paths = [resolved_paths[key] for key in required_path_keys]
    missing_required_reports = [_to_unix_path(path) for path in required_paths if not path.exists()]
    checks["all_required_reports_present"] = len(missing_required_reports) == 0

    gating_check_ids = [
        "full_chain_passed",
        "doc_consistency_passed",
        "ws27_endurance_passed",
        "ws27_cutover_status_passed",
        "ws27_oob_drill_passed",
        "ws28_governance_hard_reason_codes_absent",
        "ws28_governance_soft_reason_codes_within_budget",
        "ws28_governance_unknown_reason_codes_absent",
        "all_required_reports_present",
    ]
    if require_wallclock_acceptance:
        gating_check_ids.append("ws27_wallclock_acceptance_passed")
    passed = all(bool(checks.get(check_id)) for check_id in gating_check_ids)
    generated_at = _utc_iso_now()
    path_report = {key: _to_unix_path(path) for key, path in resolved_paths.items()}

    report: Dict[str, Any] = {
        "task_id": "NGA-WS27-006",
        "scenario": "phase3_full_release_report_and_signoff_template",
        "generated_at": generated_at,
        "repo_root": _to_unix_path(root),
        "release_candidate": str(release_candidate or "phase3-full-m12"),
        "passed": passed,
        "checks": checks,
        "gating_check_ids": gating_check_ids,
        "require_wallclock_acceptance": bool(require_wallclock_acceptance),
        "missing_required_reports": missing_required_reports,
        "report_paths": path_report,
        "sources": {
            "full_chain_report": full_chain_payload,
            "doc_consistency_report": doc_consistency_payload,
            "ws27_endurance_report": ws27_endurance_payload,
            "ws27_wallclock_report": ws27_wallclock_payload,
            "ws27_cutover_status_report": ws27_cutover_status_payload,
            "ws27_oob_report": ws27_oob_payload,
        },
        "governance_reason_code_policy": {
            "hard": hard_policy,
            "soft": soft_policy,
            "unknown_policy": "hard_fail",
        },
        "governance_reason_code_evaluation": {
            "observed": governance_reason_codes,
            "hard_hits": hard_hits,
            "soft_hits": soft_hits,
            "unknown_hits": unknown_hits,
            "max_soft_reason_code_count": max(0, int(max_soft_reason_code_count)),
        },
    }

    output_report = _resolve_path(root, output_json)
    output_signoff = _resolve_path(root, output_markdown)
    output_report.parent.mkdir(parents=True, exist_ok=True)
    output_signoff.parent.mkdir(parents=True, exist_ok=True)
    output_report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    markdown_text = _build_signoff_markdown(
        generated_at=generated_at,
        release_candidate=str(release_candidate or "phase3-full-m12"),
        checks=checks,
        report_paths=path_report,
        governance_reason_code_policy=report["governance_reason_code_policy"],
        governance_reason_code_evaluation=report["governance_reason_code_evaluation"],
        verdict_passed=passed,
        require_wallclock_acceptance=bool(require_wallclock_acceptance),
    )
    output_signoff.write_text(markdown_text + "\n", encoding="utf-8")

    report["output_json"] = _to_unix_path(output_report)
    report["output_markdown"] = _to_unix_path(output_signoff)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate WS27-006 Phase3 Full release report and signoff template")
    parser.add_argument("--repo-root", type=Path, default=Path("."), help="Repository root")
    parser.add_argument("--release-candidate", default="phase3-full-m12", help="Release candidate identifier")
    parser.add_argument("--full-chain-report", type=Path, default=DEFAULT_FULL_CHAIN_REPORT, help="M0-M12 full chain report path")
    parser.add_argument(
        "--doc-consistency-report",
        type=Path,
        default=DEFAULT_DOC_CONSISTENCY_REPORT,
        help="WS27-005 doc consistency report path",
    )
    parser.add_argument(
        "--ws27-endurance-report",
        type=Path,
        default=DEFAULT_WS27_ENDURANCE_REPORT,
        help="WS27-001 endurance report path",
    )
    parser.add_argument(
        "--ws27-wallclock-report",
        type=Path,
        default=DEFAULT_WS27_WALLCLOCK_REPORT,
        help="WS27-001 wall-clock acceptance report path",
    )
    parser.add_argument(
        "--ws27-cutover-status-report",
        type=Path,
        default=DEFAULT_WS27_CUTOVER_STATUS_REPORT,
        help="WS27-002 cutover status report path",
    )
    parser.add_argument("--ws27-oob-report", type=Path, default=DEFAULT_WS27_OOB_REPORT, help="WS27-003 OOB drill report path")
    parser.add_argument(
        "--require-wallclock-acceptance",
        action="store_true",
        help="Treat WS27-001 wall-clock acceptance report as required release gate",
    )
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON, help="Output JSON report path")
    parser.add_argument("--output-markdown", type=Path, default=DEFAULT_OUTPUT_MARKDOWN, help="Output markdown signoff template path")
    parser.add_argument(
        "--max-soft-reason-code-count",
        type=int,
        default=5,
        help="Maximum accepted count of soft governance reason_codes",
    )
    parser.add_argument("--strict", action="store_true", help="Return non-zero when checks fail")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_generate_phase3_full_release_report_ws27_006(
        repo_root=args.repo_root,
        release_candidate=str(args.release_candidate),
        full_chain_report=args.full_chain_report,
        doc_consistency_report=args.doc_consistency_report,
        ws27_endurance_report=args.ws27_endurance_report,
        ws27_wallclock_report=args.ws27_wallclock_report,
        ws27_cutover_status_report=args.ws27_cutover_status_report,
        ws27_oob_report=args.ws27_oob_report,
        output_json=args.output_json,
        output_markdown=args.output_markdown,
        require_wallclock_acceptance=bool(args.require_wallclock_acceptance),
        max_soft_reason_code_count=max(0, int(args.max_soft_reason_code_count)),
    )
    print(
        json.dumps(
            {
                "passed": bool(report.get("passed")),
                "checks": report.get("checks", {}),
                "output_json": report.get("output_json"),
                "output_markdown": report.get("output_markdown"),
            },
            ensure_ascii=False,
        )
    )
    if args.strict and not bool(report.get("passed")):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
