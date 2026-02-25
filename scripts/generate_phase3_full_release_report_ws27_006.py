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
DEFAULT_WS27_CUTOVER_STATUS_REPORT = Path("scratch/reports/ws27_subagent_cutover_status_ws27_002.json")
DEFAULT_WS27_OOB_REPORT = Path("scratch/reports/ws27_oob_repair_drill_ws27_003.json")
DEFAULT_OUTPUT_JSON = Path("scratch/reports/phase3_full_release_report_ws27_006.json")
DEFAULT_OUTPUT_MARKDOWN = Path("scratch/reports/phase3_full_release_signoff_ws27_006.md")


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
    verdict_passed: bool,
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
            f"- `ws27_cutover_status_report`: `{report_paths['ws27_cutover_status_report']}`",
            f"- `ws27_oob_report`: `{report_paths['ws27_oob_report']}`",
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


def run_generate_phase3_full_release_report_ws27_006(
    *,
    repo_root: Path,
    release_candidate: str = "phase3-full-m12",
    full_chain_report: Path = DEFAULT_FULL_CHAIN_REPORT,
    doc_consistency_report: Path = DEFAULT_DOC_CONSISTENCY_REPORT,
    ws27_endurance_report: Path = DEFAULT_WS27_ENDURANCE_REPORT,
    ws27_cutover_status_report: Path = DEFAULT_WS27_CUTOVER_STATUS_REPORT,
    ws27_oob_report: Path = DEFAULT_WS27_OOB_REPORT,
    output_json: Path = DEFAULT_OUTPUT_JSON,
    output_markdown: Path = DEFAULT_OUTPUT_MARKDOWN,
) -> Dict[str, Any]:
    root = repo_root.resolve()
    resolved_paths = {
        "full_chain_report": _resolve_path(root, full_chain_report),
        "doc_consistency_report": _resolve_path(root, doc_consistency_report),
        "ws27_endurance_report": _resolve_path(root, ws27_endurance_report),
        "ws27_cutover_status_report": _resolve_path(root, ws27_cutover_status_report),
        "ws27_oob_report": _resolve_path(root, ws27_oob_report),
    }

    full_chain_payload = _read_json_if_exists(resolved_paths["full_chain_report"])
    doc_consistency_payload = _read_json_if_exists(resolved_paths["doc_consistency_report"])
    ws27_endurance_payload = _read_json_if_exists(resolved_paths["ws27_endurance_report"])
    ws27_cutover_status_payload = _read_json_if_exists(resolved_paths["ws27_cutover_status_report"])
    ws27_oob_payload = _read_json_if_exists(resolved_paths["ws27_oob_report"])

    checks = {
        "full_chain_passed": bool(full_chain_payload.get("passed")),
        "doc_consistency_passed": bool(doc_consistency_payload.get("passed")),
        "ws27_endurance_passed": bool(ws27_endurance_payload.get("passed")),
        "ws27_cutover_status_passed": bool(ws27_cutover_status_payload.get("passed")),
        "ws27_oob_drill_passed": bool(ws27_oob_payload.get("passed")),
    }
    required_paths = list(resolved_paths.values())
    missing_required_reports = [_to_unix_path(path) for path in required_paths if not path.exists()]
    checks["all_required_reports_present"] = len(missing_required_reports) == 0

    passed = all(checks.values())
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
        "missing_required_reports": missing_required_reports,
        "report_paths": path_report,
        "sources": {
            "full_chain_report": full_chain_payload,
            "doc_consistency_report": doc_consistency_payload,
            "ws27_endurance_report": ws27_endurance_payload,
            "ws27_cutover_status_report": ws27_cutover_status_payload,
            "ws27_oob_report": ws27_oob_payload,
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
        verdict_passed=passed,
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
        "--ws27-cutover-status-report",
        type=Path,
        default=DEFAULT_WS27_CUTOVER_STATUS_REPORT,
        help="WS27-002 cutover status report path",
    )
    parser.add_argument("--ws27-oob-report", type=Path, default=DEFAULT_WS27_OOB_REPORT, help="WS27-003 OOB drill report path")
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON, help="Output JSON report path")
    parser.add_argument("--output-markdown", type=Path, default=DEFAULT_OUTPUT_MARKDOWN, help="Output markdown signoff template path")
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
        ws27_cutover_status_report=args.ws27_cutover_status_report,
        ws27_oob_report=args.ws27_oob_report,
        output_json=args.output_json,
        output_markdown=args.output_markdown,
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
