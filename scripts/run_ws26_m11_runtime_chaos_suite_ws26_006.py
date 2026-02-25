#!/usr/bin/env python3
"""Run WS26-006 M11 runtime chaos suite."""

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


@dataclass(frozen=True)
class ChaosCase:
    case_id: str
    name: str
    pytest_targets: Sequence[str]


@dataclass
class ChaosCaseResult:
    case_id: str
    name: str
    command: List[str]
    passed: bool
    return_code: int
    duration_seconds: float
    stdout_tail: str = ""
    stderr_tail: str = ""


Runner = Callable[[List[str], Path, int], tuple[int, str, str]]


CHAOS_CASES: Sequence[ChaosCase] = (
    ChaosCase(
        case_id="C1",
        name="lock_leak_and_fencing_failover",
        pytest_targets=(
            "tests/test_chaos_lock_failover.py",
            "tests/test_agentic_loop_contract_and_mutex.py::test_global_mutex_pre_acquire_scavenger_runs_and_attaches_report",
            "tests/test_agentic_loop_contract_and_mutex.py::test_global_mutex_pre_acquire_scavenger_scan_error_is_non_blocking",
        ),
    ),
    ChaosCase(
        case_id="C2",
        name="sleep_watch_logrotate_and_redos",
        pytest_targets=("tests/test_chaos_sleep_watch.py",),
    ),
    ChaosCase(
        case_id="C3",
        name="double_fork_detached_cleanup",
        pytest_targets=(
            "tests/test_process_lineage.py::test_process_lineage_kill_job_signature_runs_even_when_root_kill_succeeds",
            "tests/test_process_lineage.py::test_extract_signature_tokens_supports_docker_detach_variant",
        ),
    ),
)


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


def run_ws26_m11_runtime_chaos_suite_ws26_006(
    *,
    repo_root: Path,
    output_file: Path,
    continue_on_failure: bool = False,
    timeout_seconds: int = 2400,
    runner: Runner | None = None,
) -> Dict[str, object]:
    root = repo_root.resolve()
    py = sys.executable
    step_runner = runner or _default_runner
    started_at = time.time()

    case_results: List[ChaosCaseResult] = []
    failed_cases: List[str] = []
    for case in CHAOS_CASES:
        command = [py, "-m", "pytest", "-q", *case.pytest_targets, "-p", "no:tmpdir"]
        round_start = time.time()
        rc, stdout, stderr = step_runner(list(command), root, timeout_seconds)
        passed = int(rc) == 0
        case_result = ChaosCaseResult(
            case_id=case.case_id,
            name=case.name,
            command=list(command),
            passed=passed,
            return_code=int(rc),
            duration_seconds=round(time.time() - round_start, 4),
            stdout_tail=_tail(stdout),
            stderr_tail=_tail(stderr),
        )
        case_results.append(case_result)
        if not passed:
            failed_cases.append(case.case_id)
            if not continue_on_failure:
                break

    passed = len(failed_cases) == 0
    report: Dict[str, object] = {
        "task_id": "NGA-WS26-006",
        "scenario": "m11_lock_logrotate_double_fork_chaos_suite",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo_root": str(root).replace("\\", "/"),
        "elapsed_seconds": round(time.time() - started_at, 4),
        "passed": passed,
        "failed_cases": failed_cases,
        "case_count_executed": len(case_results),
        "case_count_planned": len(CHAOS_CASES),
        "case_results": [asdict(item) for item in case_results],
    }

    output = output_file if output_file.is_absolute() else root / output_file
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run WS26-006 M11 runtime chaos suite")
    parser.add_argument("--repo-root", type=Path, default=Path("."), help="Repository root")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("scratch/reports/ws26_m11_runtime_chaos_ws26_006.json"),
        help="Output JSON report path",
    )
    parser.add_argument("--continue-on-failure", action="store_true", help="Continue remaining cases after failure")
    parser.add_argument("--timeout-seconds", type=int, default=2400, help="Per-case timeout")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_ws26_m11_runtime_chaos_suite_ws26_006(
        repo_root=args.repo_root,
        output_file=args.output,
        continue_on_failure=bool(args.continue_on_failure),
        timeout_seconds=max(30, int(args.timeout_seconds)),
    )
    print(
        json.dumps(
            {
                "passed": report.get("passed"),
                "failed_cases": report.get("failed_cases"),
                "output": str((args.output if args.output.is_absolute() else (args.repo_root / args.output).resolve())),
            },
            ensure_ascii=False,
        )
    )
    return 0 if bool(report.get("passed")) else 2


if __name__ == "__main__":
    raise SystemExit(main())
