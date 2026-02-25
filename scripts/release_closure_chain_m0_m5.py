#!/usr/bin/env python3
"""Release closure chain runner for M0-M5 gates."""

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


T1_TEST_TARGETS: tuple[str, ...] = (
    "tests/test_native_executor_guards.py",
    "tests/test_policy_firewall.py",
    "tests/test_global_mutex.py",
    "tests/test_process_lineage.py",
    "tests/test_native_tools_runtime_hardening.py",
    "tests/test_agentic_loop_contract_and_mutex.py",
)

T2_TEST_TARGETS: tuple[str, ...] = (
    "tests/test_tool_contract.py",
    "tests/test_tool_schema_validation.py",
    "tests/test_native_tools_artifact_and_guard.py",
    "tests/test_native_tools_ws11_003.py",
    "tests/test_gc_budget_guard.py",
    "tests/test_gc_reader_bridge.py",
    "tests/test_gc_memory_card_injection.py",
)

T3_TEST_TARGETS: tuple[str, ...] = (
    "tests/test_api_contract_ws20_001.py",
    "tests/test_sse_event_protocol_ws20_002.py",
    "tests/test_frontend_bff_regression_ws20_005.py",
    "tests/test_mcp_status_snapshot.py",
    "tests/test_contract_rollout_ws16_005.py",
    "tests/test_doc_consistency_ws16_006.py",
    "tests/test_sync_risk_verify_mapping_ws16_006.py",
    "tests/test_sync_risk_closure_ledger_ws16_006.py",
)

T4_TEST_TARGETS: tuple[str, ...] = (
    "autonomous/tests/test_event_store_ws18_001.py",
    "autonomous/tests/test_workflow_store.py",
    "autonomous/tests/test_meta_agent_runtime_ws19_001.py",
    "autonomous/tests/test_router_engine_ws19_002.py",
    "autonomous/tests/test_llm_gateway_ws19_003.py",
    "autonomous/tests/test_working_memory_manager_ws19_004.py",
    "autonomous/tests/test_daily_checkpoint_ws19_007.py",
    "autonomous/tests/test_router_arbiter_guard_ws19_008.py",
    "autonomous/tests/test_event_replay_tool_ws18_003.py",
    "autonomous/tests/test_system_agent_release_flow.py",
)


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
    skip_t0: bool,
    skip_t1: bool,
    skip_t2: bool,
    skip_t3: bool,
    skip_t4: bool,
    skip_t5: bool,
) -> List[ChainStep]:
    steps: List[ChainStep] = []
    if not skip_t0:
        steps.append(
            ChainStep(
                step_id="T0A",
                description="Immutable DNA integrity gate validation",
                command=[python_exe, "scripts/validate_immutable_dna_gate_ws23_003.py"],
            )
        )
        steps.append(
            ChainStep(
                step_id="T0B",
                description="Doc consistency strict validation",
                command=[python_exe, "scripts/validate_doc_consistency_ws16_006.py", "--strict"],
            )
        )
    if not skip_t1:
        steps.append(
            ChainStep(
                step_id="T1",
                description="Security and runtime regression suite",
                command=[python_exe, "-m", "pytest", "-q", *T1_TEST_TARGETS, "-p", "no:tmpdir"],
            )
        )
    if not skip_t2:
        steps.append(
            ChainStep(
                step_id="T2",
                description="Contract and evidence pipeline regression suite",
                command=[python_exe, "-m", "pytest", "-q", *T2_TEST_TARGETS, "-p", "no:tmpdir"],
            )
        )
    if not skip_t3:
        steps.append(
            ChainStep(
                step_id="T3",
                description="API/BFF and migration regression suite",
                command=[python_exe, "-m", "pytest", "-q", *T3_TEST_TARGETS, "-p", "no:tmpdir"],
            )
        )
    if not skip_t4:
        steps.append(
            ChainStep(
                step_id="T4",
                description="Autonomous core regression suite",
                command=[python_exe, "-m", "pytest", "-q", *T4_TEST_TARGETS, "-p", "no:tmpdir"],
            )
        )
    if not skip_t5:
        steps.append(
            ChainStep(
                step_id="T5A",
                description="Export SLO snapshot release artifact",
                command=[python_exe, "scripts/export_slo_snapshot.py"],
            )
        )
        steps.append(
            ChainStep(
                step_id="T5B",
                description="Desktop release compatibility strict check",
                command=[python_exe, "scripts/desktop_release_compat_ws20_006.py", "--strict"],
            )
        )
        steps.append(
            ChainStep(
                step_id="T5C",
                description="Canary rollback drill dry-run",
                command=[python_exe, "scripts/canary_rollback_drill.py", "--dry-run"],
            )
        )
    return steps


def run_release_closure_chain_m0_m5(
    *,
    repo_root: Path,
    output_file: Path,
    skip_t0: bool = False,
    skip_t1: bool = False,
    skip_t2: bool = False,
    skip_t3: bool = False,
    skip_t4: bool = False,
    skip_t5: bool = False,
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
        skip_t0=skip_t0,
        skip_t1=skip_t1,
        skip_t2=skip_t2,
        skip_t3=skip_t3,
        skip_t4=skip_t4,
        skip_t5=skip_t5,
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
        "task_id": "M0-M5-RELEASE-CLOSURE",
        "scenario": "release_closure_chain_m0_m5",
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
    parser = argparse.ArgumentParser(description="Run release closure chain for M0-M5")
    parser.add_argument("--repo-root", type=Path, default=Path("."), help="Repository root")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("scratch/reports/release_closure_chain_m0_m5_result.json"),
        help="Output JSON report path",
    )
    parser.add_argument("--skip-t0", action="store_true", help="Skip T0 preflight gates (DNA + doc consistency)")
    parser.add_argument("--skip-t1", action="store_true", help="Skip T1 runtime regression suite")
    parser.add_argument("--skip-t2", action="store_true", help="Skip T2 contract/evidence regression suite")
    parser.add_argument("--skip-t3", action="store_true", help="Skip T3 API/BFF regression suite")
    parser.add_argument("--skip-t4", action="store_true", help="Skip T4 autonomous core regression suite")
    parser.add_argument("--skip-t5", action="store_true", help="Skip T5 release work-order artifact steps")
    parser.add_argument("--continue-on-failure", action="store_true", help="Continue remaining steps after failure")
    parser.add_argument("--timeout-seconds", type=int, default=2400, help="Per-step timeout")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_release_closure_chain_m0_m5(
        repo_root=args.repo_root,
        output_file=args.output,
        skip_t0=bool(args.skip_t0),
        skip_t1=bool(args.skip_t1),
        skip_t2=bool(args.skip_t2),
        skip_t3=bool(args.skip_t3),
        skip_t4=bool(args.skip_t4),
        skip_t5=bool(args.skip_t5),
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
