#!/usr/bin/env python3
"""Run WS27-006 one-click Phase3 full signoff closure chain."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List


DEFAULT_OUTPUT = Path("scratch/reports/release_phase3_full_signoff_chain_ws27_006_result.json")
DEFAULT_FULL_CHAIN_OUTPUT = Path("scratch/reports/release_closure_chain_full_m0_m12_result.json")
DEFAULT_DOC_CONSISTENCY_OUTPUT = Path("scratch/reports/ws27_m12_doc_consistency_ws27_005.json")
DEFAULT_RELEASE_REPORT_OUTPUT = Path("scratch/reports/phase3_full_release_report_ws27_006.json")
DEFAULT_RELEASE_SIGNOFF_OUTPUT = Path("scratch/reports/phase3_full_release_signoff_ws27_006.md")


@dataclass(frozen=True)
class ChainStep:
    step_id: str
    description: str
    command: List[str]


@dataclass
class ChainStepResult:
    step_id: str
    description: str
    command: List[str]
    passed: bool
    return_code: int
    duration_seconds: float
    stdout_tail: str = ""
    stderr_tail: str = ""


Runner = Callable[[List[str], Path, int], tuple[int, str, str]]


def _tail(text: str, *, max_chars: int = 1600) -> str:
    normalized = str(text or "")
    if len(normalized) <= max_chars:
        return normalized
    return normalized[-max_chars:]


def _to_unix_path(path: Path) -> str:
    return str(path).replace("\\", "/")


def _default_runner(command: List[str], cwd: Path, timeout_seconds: int) -> tuple[int, str, str]:
    proc = subprocess.run(
        command,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=max(30, int(timeout_seconds)),
        check=False,
    )
    return int(proc.returncode), str(proc.stdout or ""), str(proc.stderr or "")


def _build_steps(
    *,
    python_exe: str,
    full_chain_output: Path,
    doc_consistency_output: Path,
    release_report_output: Path,
    release_signoff_output: Path,
    release_candidate: str,
    require_wallclock_acceptance: bool,
    quick_mode: bool,
    skip_m0_m11: bool,
    skip_full_chain: bool,
    skip_doc_consistency: bool,
    skip_release_report: bool,
) -> List[ChainStep]:
    steps: List[ChainStep] = []
    if not skip_full_chain:
        command = [
            python_exe,
            "scripts/release_closure_chain_full_m0_m12.py",
            "--output",
            _to_unix_path(full_chain_output),
        ]
        if quick_mode:
            command.append("--quick-mode")
        if skip_m0_m11:
            command.append("--skip-m0-m11")
        steps.append(
            ChainStep(
                step_id="T0",
                description="WS27-004 M0-M12 full closure chain",
                command=command,
            )
        )

    if not skip_doc_consistency:
        steps.append(
            ChainStep(
                step_id="T1",
                description="WS27-005 M12 doc consistency strict validation",
                command=[
                    python_exe,
                    "scripts/validate_m12_doc_consistency_ws27_005.py",
                    "--strict",
                    "--output",
                    _to_unix_path(doc_consistency_output),
                ],
            )
        )

    if not skip_release_report:
        command = [
            python_exe,
            "scripts/generate_phase3_full_release_report_ws27_006.py",
            "--strict",
            "--release-candidate",
            str(release_candidate or "phase3-full-m12"),
            "--full-chain-report",
            _to_unix_path(full_chain_output),
            "--doc-consistency-report",
            _to_unix_path(doc_consistency_output),
            "--output-json",
            _to_unix_path(release_report_output),
            "--output-markdown",
            _to_unix_path(release_signoff_output),
        ]
        if require_wallclock_acceptance:
            command.append("--require-wallclock-acceptance")
        steps.append(
            ChainStep(
                step_id="T2",
                description="WS27-006 phase3 full release report and signoff template",
                command=command,
            )
        )

    return steps


def run_release_phase3_full_signoff_chain_ws27_006(
    *,
    repo_root: Path,
    output_file: Path = DEFAULT_OUTPUT,
    full_chain_output: Path = DEFAULT_FULL_CHAIN_OUTPUT,
    doc_consistency_output: Path = DEFAULT_DOC_CONSISTENCY_OUTPUT,
    release_report_output: Path = DEFAULT_RELEASE_REPORT_OUTPUT,
    release_signoff_output: Path = DEFAULT_RELEASE_SIGNOFF_OUTPUT,
    release_candidate: str = "phase3-full-m12",
    require_wallclock_acceptance: bool = False,
    quick_mode: bool = False,
    skip_m0_m11: bool = False,
    skip_full_chain: bool = False,
    skip_doc_consistency: bool = False,
    skip_release_report: bool = False,
    continue_on_failure: bool = False,
    timeout_seconds: int = 2400,
    runner: Runner | None = None,
) -> Dict[str, object]:
    root = repo_root.resolve()
    py = sys.executable
    step_runner = runner or _default_runner
    started_at = time.time()
    steps = _build_steps(
        python_exe=py,
        full_chain_output=full_chain_output,
        doc_consistency_output=doc_consistency_output,
        release_report_output=release_report_output,
        release_signoff_output=release_signoff_output,
        release_candidate=release_candidate,
        require_wallclock_acceptance=bool(require_wallclock_acceptance),
        quick_mode=bool(quick_mode),
        skip_m0_m11=bool(skip_m0_m11),
        skip_full_chain=bool(skip_full_chain),
        skip_doc_consistency=bool(skip_doc_consistency),
        skip_release_report=bool(skip_release_report),
    )

    step_results: List[ChainStepResult] = []
    failed_steps: List[str] = []
    for step in steps:
        round_start = time.time()
        rc, stdout, stderr = step_runner(list(step.command), root, timeout_seconds)
        passed = int(rc) == 0
        result = ChainStepResult(
            step_id=step.step_id,
            description=step.description,
            command=list(step.command),
            passed=passed,
            return_code=int(rc),
            duration_seconds=round(time.time() - round_start, 4),
            stdout_tail=_tail(stdout),
            stderr_tail=_tail(stderr),
        )
        step_results.append(result)
        if not passed:
            failed_steps.append(step.step_id)
            if not continue_on_failure:
                break

    report: Dict[str, object] = {
        "task_id": "NGA-WS27-006",
        "scenario": "release_phase3_full_signoff_chain_ws27_006",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo_root": _to_unix_path(root),
        "elapsed_seconds": round(time.time() - started_at, 4),
        "passed": len(failed_steps) == 0,
        "failed_steps": failed_steps,
        "step_count_executed": len(step_results),
        "step_count_planned": len(steps),
        "steps_config": {
            "quick_mode": bool(quick_mode),
            "skip_m0_m11": bool(skip_m0_m11),
            "skip_full_chain": bool(skip_full_chain),
            "skip_doc_consistency": bool(skip_doc_consistency),
            "skip_release_report": bool(skip_release_report),
            "require_wallclock_acceptance": bool(require_wallclock_acceptance),
        },
        "artifacts": {
            "full_chain_output": _to_unix_path(full_chain_output),
            "doc_consistency_output": _to_unix_path(doc_consistency_output),
            "release_report_output": _to_unix_path(release_report_output),
            "release_signoff_output": _to_unix_path(release_signoff_output),
        },
        "step_results": [asdict(item) for item in step_results],
    }

    output = output_file if output_file.is_absolute() else root / output_file
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["output"] = _to_unix_path(output)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run WS27-006 one-click Phase3 full signoff closure chain")
    parser.add_argument("--repo-root", type=Path, default=Path("."), help="Repository root")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output JSON report path")
    parser.add_argument("--full-chain-output", type=Path, default=DEFAULT_FULL_CHAIN_OUTPUT, help="WS27-004 output path")
    parser.add_argument(
        "--doc-consistency-output",
        type=Path,
        default=DEFAULT_DOC_CONSISTENCY_OUTPUT,
        help="WS27-005 output path",
    )
    parser.add_argument(
        "--release-report-output",
        type=Path,
        default=DEFAULT_RELEASE_REPORT_OUTPUT,
        help="WS27-006 JSON output path",
    )
    parser.add_argument(
        "--release-signoff-output",
        type=Path,
        default=DEFAULT_RELEASE_SIGNOFF_OUTPUT,
        help="WS27-006 markdown output path",
    )
    parser.add_argument("--release-candidate", default="phase3-full-m12", help="Release candidate identifier")
    parser.add_argument(
        "--require-wallclock-acceptance",
        action="store_true",
        help="Enable WS27-001 real wall-clock acceptance hard gate on WS27-006 step",
    )
    parser.add_argument("--quick-mode", action="store_true", help="Forward quick mode to WS27-004 full chain")
    parser.add_argument("--skip-m0-m11", action="store_true", help="Forward skip-m0-m11 to WS27-004 full chain")
    parser.add_argument("--skip-full-chain", action="store_true", help="Skip WS27-004 full chain step")
    parser.add_argument("--skip-doc-consistency", action="store_true", help="Skip WS27-005 doc consistency step")
    parser.add_argument("--skip-release-report", action="store_true", help="Skip WS27-006 release report step")
    parser.add_argument("--continue-on-failure", action="store_true", help="Continue remaining steps after failure")
    parser.add_argument("--timeout-seconds", type=int, default=2400, help="Per-step timeout")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_release_phase3_full_signoff_chain_ws27_006(
        repo_root=args.repo_root,
        output_file=args.output,
        full_chain_output=args.full_chain_output,
        doc_consistency_output=args.doc_consistency_output,
        release_report_output=args.release_report_output,
        release_signoff_output=args.release_signoff_output,
        release_candidate=str(args.release_candidate),
        require_wallclock_acceptance=bool(args.require_wallclock_acceptance),
        quick_mode=bool(args.quick_mode),
        skip_m0_m11=bool(args.skip_m0_m11),
        skip_full_chain=bool(args.skip_full_chain),
        skip_doc_consistency=bool(args.skip_doc_consistency),
        skip_release_report=bool(args.skip_release_report),
        continue_on_failure=bool(args.continue_on_failure),
        timeout_seconds=max(30, int(args.timeout_seconds)),
    )
    print(
        json.dumps(
            {
                "passed": bool(report.get("passed")),
                "failed_steps": report.get("failed_steps", []),
                "output": str((args.output if args.output.is_absolute() else (args.repo_root / args.output).resolve())),
            },
            ensure_ascii=False,
        )
    )
    return 0 if bool(report.get("passed")) else 2


if __name__ == "__main__":
    raise SystemExit(main())
