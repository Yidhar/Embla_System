#!/usr/bin/env python3
"""WS24-006 M9 release closure chain runner."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Sequence


M9_TEST_TARGETS: Sequence[str] = (
    "tests/test_mcp_plugin_isolation_ws24_001.py",
    "tests/test_run_plugin_isolation_chaos_suite_ws24_005.py",
    "autonomous/tests/test_ws24_release_gate.py",
)

DEFAULT_PLUGIN_CHAOS_REPORT = Path("scratch/reports/plugin_isolation_chaos_ws24_005.json")
DEFAULT_M9_GATE_REPORT = Path("scratch/reports/ws24_m9_closure_gate_result.json")


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
    skip_tests: bool,
    skip_runtime_checks: bool,
    skip_gate: bool,
    skip_doc_consistency: bool,
) -> List[ChainStep]:
    steps: List[ChainStep] = []
    if not skip_tests:
        steps.append(
            ChainStep(
                step_id="T0",
                description="WS24 M9 targeted regression tests",
                command=[python_exe, "-m", "pytest", "-q", *M9_TEST_TARGETS, "-p", "no:tmpdir"],
            )
        )
    if not skip_runtime_checks:
        steps.append(
            ChainStep(
                step_id="T1",
                description="WS24-005 plugin isolation chaos suite",
                command=[
                    python_exe,
                    "scripts/run_plugin_isolation_chaos_suite_ws24_005.py",
                    "--output",
                    str(DEFAULT_PLUGIN_CHAOS_REPORT).replace("\\", "/"),
                ],
            )
        )
    if not skip_gate:
        steps.append(
            ChainStep(
                step_id="T2",
                description="WS24-006 M9 closure gate validation",
                command=[
                    python_exe,
                    "scripts/validate_m9_closure_gate_ws24_006.py",
                    "--plugin-chaos-report",
                    str(DEFAULT_PLUGIN_CHAOS_REPORT).replace("\\", "/"),
                    "--output-json",
                    str(DEFAULT_M9_GATE_REPORT).replace("\\", "/"),
                ],
            )
        )
    if not skip_doc_consistency:
        steps.append(
            ChainStep(
                step_id="T3",
                description="Doc consistency strict validation",
                command=[python_exe, "scripts/validate_doc_consistency_ws16_006.py", "--strict"],
            )
        )
    return steps


def run_release_closure_chain_m9_ws24_006(
    *,
    repo_root: Path,
    output_file: Path,
    skip_tests: bool = False,
    skip_runtime_checks: bool = False,
    skip_gate: bool = False,
    skip_doc_consistency: bool = False,
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
        skip_tests=skip_tests,
        skip_runtime_checks=skip_runtime_checks,
        skip_gate=skip_gate,
        skip_doc_consistency=skip_doc_consistency,
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

    passed = len(failed_steps) == 0
    report: Dict[str, object] = {
        "task_id": "NGA-WS24-006",
        "scenario": "release_closure_chain_m9_ws24_006",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo_root": str(root).replace("\\", "/"),
        "elapsed_seconds": round(time.time() - started_at, 4),
        "passed": passed,
        "failed_steps": failed_steps,
        "step_count_executed": len(step_results),
        "step_count_planned": len(steps),
        "step_results": [asdict(item) for item in step_results],
    }

    output = output_file if output_file.is_absolute() else root / output_file
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run WS24-006 M9 release closure chain")
    parser.add_argument("--repo-root", type=Path, default=Path("."), help="Repository root")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("scratch/reports/release_closure_chain_m9_ws24_006_result.json"),
        help="Output JSON report path",
    )
    parser.add_argument("--skip-tests", action="store_true", help="Skip T0 targeted tests")
    parser.add_argument("--skip-runtime-checks", action="store_true", help="Skip T1 runtime/report step")
    parser.add_argument("--skip-gate", action="store_true", help="Skip T2 closure gate validation")
    parser.add_argument("--skip-doc-consistency", action="store_true", help="Skip T3 doc consistency")
    parser.add_argument("--continue-on-failure", action="store_true", help="Continue remaining steps after failure")
    parser.add_argument("--timeout-seconds", type=int, default=2400, help="Per-step timeout")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_release_closure_chain_m9_ws24_006(
        repo_root=args.repo_root,
        output_file=args.output,
        skip_tests=bool(args.skip_tests),
        skip_runtime_checks=bool(args.skip_runtime_checks),
        skip_gate=bool(args.skip_gate),
        skip_doc_consistency=bool(args.skip_doc_consistency),
        continue_on_failure=bool(args.continue_on_failure),
        timeout_seconds=max(30, int(args.timeout_seconds)),
    )
    print(
        json.dumps(
            {
                "passed": report.get("passed"),
                "failed_steps": report.get("failed_steps"),
                "output": str((args.output if args.output.is_absolute() else (args.repo_root / args.output).resolve())),
            },
            ensure_ascii=False,
        )
    )
    return 0 if bool(report.get("passed")) else 2


if __name__ == "__main__":
    raise SystemExit(main())
