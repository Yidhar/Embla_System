#!/usr/bin/env python3
"""Render markdown summary from release closure chain reports."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


def _load_report(path: Path) -> tuple[Dict[str, Any] | None, str | None]:
    if not path.exists():
        return None, "report file not found"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - defensive branch
        return None, f"invalid json: {exc}"
    if not isinstance(payload, dict):
        return None, f"invalid payload type: {type(payload).__name__}"
    return payload, None


def _status_label(passed: bool | None) -> str:
    if passed is True:
        return "PASS"
    if passed is False:
        return "FAIL"
    return "UNKNOWN"


def _format_paths(*paths: Path) -> str:
    rows = []
    for p in paths:
        rows.append(f"- `{str(p).replace(chr(92), '/')}`")
    return "\n".join(rows)


def _extract_failed_step_rows(step_results: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for item in step_results:
        if not isinstance(item, dict):
            continue
        if bool(item.get("passed")):
            continue
        rows.append(item)
    return rows


def _truncate(text: Any, max_chars: int = 400) -> str:
    normalized = str(text or "")
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max_chars - 3] + "..."


def build_release_summary_markdown(
    *,
    full_report: Dict[str, Any] | None,
    m0_m5_report: Dict[str, Any] | None,
    m6_m7_report: Dict[str, Any] | None,
    full_report_path: Path,
    m0_m5_report_path: Path,
    m6_m7_report_path: Path,
    load_errors: Dict[str, str],
) -> str:
    full_passed = None if full_report is None else bool(full_report.get("passed"))
    m0_passed = None if m0_m5_report is None else bool(m0_m5_report.get("passed"))
    m6_passed = None if m6_m7_report is None else bool(m6_m7_report.get("passed"))

    if full_passed is None:
        overall_status = "UNKNOWN"
    else:
        overall_status = _status_label(full_passed)

    lines: List[str] = []
    lines.append("## Release Closure Summary (M0-M7)")
    lines.append("")
    lines.append(f"Overall: **{overall_status}**")
    lines.append("")
    lines.append("| Report | Status | Key Notes |")
    lines.append("|---|---|---|")
    lines.append(
        f"| `full_m0_m7` | `{_status_label(full_passed)}` | failed_groups={list((full_report or {}).get('failed_groups') or [])} |"
    )
    lines.append(
        f"| `m0_m5` | `{_status_label(m0_passed)}` | failed_steps={list((m0_m5_report or {}).get('failed_steps') or [])} |"
    )
    lines.append(
        f"| `m6_m7` | `{_status_label(m6_passed)}` | failed_steps={list((m6_m7_report or {}).get('failed_steps') or [])} |"
    )
    lines.append("")
    lines.append("Report paths:")
    lines.append(_format_paths(full_report_path, m0_m5_report_path, m6_m7_report_path))
    lines.append("")

    if load_errors:
        lines.append("Load issues:")
        for key in sorted(load_errors.keys()):
            lines.append(f"- `{key}`: {load_errors[key]}")
        lines.append("")

    failed_rows: List[Tuple[str, Dict[str, Any]]] = []
    for group_name, report in (("m0_m5", m0_m5_report), ("m6_m7", m6_m7_report)):
        if not isinstance(report, dict):
            continue
        step_results = report.get("step_results")
        if not isinstance(step_results, list):
            continue
        for row in _extract_failed_step_rows(step_results):
            failed_rows.append((group_name, row))

    if failed_rows:
        lines.append("Failed steps:")
        for group_name, row in failed_rows:
            step_id = row.get("step_id", "")
            desc = row.get("description", "")
            rc = row.get("return_code", "")
            stderr_tail = _truncate(row.get("stderr_tail", ""))
            lines.append(f"- `{group_name}` `{step_id}` rc={rc} {desc}")
            if stderr_tail:
                lines.append("```text")
                lines.append(stderr_tail)
                lines.append("```")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render release closure markdown summary")
    parser.add_argument(
        "--full-report",
        type=Path,
        default=Path("scratch/reports/release_closure_chain_full_m0_m7_ci.json"),
        help="Unified M0-M7 closure report path",
    )
    parser.add_argument(
        "--m0-m5-report",
        type=Path,
        default=Path("scratch/reports/release_closure_chain_m0_m5_result.json"),
        help="M0-M5 closure report path",
    )
    parser.add_argument(
        "--m6-m7-report",
        type=Path,
        default=Path("scratch/reports/ws22_phase3_release_chain_result.json"),
        help="M6-M7 closure report path",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("scratch/reports/release_closure_summary.md"),
        help="Output markdown path",
    )
    parser.add_argument(
        "--append-github-step-summary",
        action="store_true",
        help="Append markdown to GITHUB_STEP_SUMMARY file when environment variable exists",
    )
    parser.add_argument(
        "--allow-missing-full-report",
        action="store_true",
        help="Return success when full report is missing (useful for skip mode)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_errors: Dict[str, str] = {}

    full_report, full_error = _load_report(args.full_report)
    if full_error:
        load_errors["full_m0_m7"] = full_error
    m0_report, m0_error = _load_report(args.m0_m5_report)
    if m0_error:
        load_errors["m0_m5"] = m0_error
    m6_report, m6_error = _load_report(args.m6_m7_report)
    if m6_error:
        load_errors["m6_m7"] = m6_error

    markdown = build_release_summary_markdown(
        full_report=full_report,
        m0_m5_report=m0_report,
        m6_m7_report=m6_report,
        full_report_path=args.full_report,
        m0_m5_report_path=args.m0_m5_report,
        m6_m7_report_path=args.m6_m7_report,
        load_errors=load_errors,
    )

    output_path = args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")
    print(str(output_path.resolve()))

    if args.append_github_step_summary:
        step_summary = os.environ.get("GITHUB_STEP_SUMMARY", "").strip()
        if step_summary:
            summary_path = Path(step_summary)
            summary_path.parent.mkdir(parents=True, exist_ok=True)
            with summary_path.open("a", encoding="utf-8") as handle:
                handle.write(markdown)

    if full_report is None:
        if args.allow_missing_full_report:
            return 0
        return 2
    return 0 if bool(full_report.get("passed")) else 2


if __name__ == "__main__":
    raise SystemExit(main())
