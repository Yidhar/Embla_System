#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build NagaAgent Windows package."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EMBLA_CORE_DIR = PROJECT_ROOT / "Embla_core"
DEFAULT_BACKEND_DIST_DIR = PROJECT_ROOT / "dist" / "backend-dist"
SPEC_FILE = PROJECT_ROOT / "naga-backend.spec"
PHASE3_CLOSURE_SCRIPT = PROJECT_ROOT / "scripts" / "release_phase3_closure_chain_ws22_004.py"

MIN_PYTHON = (3, 11)


def log(msg: str) -> None:
    print(f"[build-win] {msg}")


def log_step(step: int, total: int, title: str) -> None:
    print()
    print("=" * 50)
    print(f"  Step {step}/{total}: {title}")
    print("=" * 50)


def run(
    cmd: list[str],
    cwd: Optional[Path] = None,
    env: Optional[dict[str, str]] = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    resolved = shutil.which(cmd[0])
    if resolved:
        cmd = [resolved, *cmd[1:]]
    log(f"$ {' '.join(cmd)}")
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        env=env,
        text=True,
        check=check,
    )


def get_cmd_version(cmd: str, args: list[str] | None = None) -> Optional[str]:
    resolved = shutil.which(cmd)
    if not resolved:
        return None
    try:
        result = subprocess.run(
            [resolved, *(args or ["--version"])],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def check_environment() -> bool:
    ok = True

    if os.name != "nt":
        log("Current OS is not Windows (build-win.py targets Windows packaging)")
        return False

    py_ver = sys.version_info[:2]
    if py_ver >= MIN_PYTHON:
        log(f"Python {sys.version.split()[0]} OK")
    else:
        log(f"Python {sys.version.split()[0]} invalid, requires >= {MIN_PYTHON[0]}.{MIN_PYTHON[1]}")
        ok = False

    uv_ver = get_cmd_version("uv", ["-V"])
    if uv_ver:
        log(f"{uv_ver} OK")
    else:
        log("uv not found (install with: pip install uv)")
        ok = False

    return ok


def sync_dependencies() -> None:
    run(["uv", "sync", "--group", "build"], cwd=PROJECT_ROOT)
    log("Python dependencies synced")


def build_backend(*, backend_dist_dir: Path) -> None:
    if not SPEC_FILE.exists():
        raise FileNotFoundError(f"spec file missing: {SPEC_FILE}")

    work_dir = PROJECT_ROOT / "build" / "pyinstaller"
    work_dir.mkdir(parents=True, exist_ok=True)

    run(
        [
            "uv",
            "run",
            "pyinstaller",
            str(SPEC_FILE),
            "--distpath",
            str(backend_dist_dir),
            "--workpath",
            str(work_dir),
            "--clean",
            "-y",
        ],
        cwd=PROJECT_ROOT,
    )

    backend_exe = backend_dist_dir / "naga-backend" / "naga-backend.exe"
    if not backend_exe.exists():
        raise FileNotFoundError(f"backend artifact missing: {backend_exe}")
    log(f"Backend build complete: {backend_exe}")


def run_phase3_closure_chain(
    *,
    output_file: Optional[Path],
    timeout_seconds: int,
) -> None:
    if not PHASE3_CLOSURE_SCRIPT.exists():
        raise FileNotFoundError(f"phase3 closure script missing: {PHASE3_CLOSURE_SCRIPT}")

    cmd = [
        sys.executable,
        str(PHASE3_CLOSURE_SCRIPT),
        "--timeout-seconds",
        str(max(30, int(timeout_seconds))),
    ]
    if output_file:
        cmd.extend(["--output", str(output_file)])

    run(cmd, cwd=PROJECT_ROOT)
    log("Phase3 closure chain gate passed")


def print_summary(*, backend_dist_dir: Path) -> None:
    print()
    print("=" * 50)
    print("  Build complete")
    print("=" * 50)

    backend_dir = backend_dist_dir / "naga-backend"
    if backend_dir.exists():
        size = sum(f.stat().st_size for f in backend_dir.rglob("*") if f.is_file())
        log(f"Backend artifact: {backend_dir} ({size / 1024 / 1024:.0f} MB)")

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="NagaAgent Windows build script")
    parser.add_argument("--backend-only", action="store_true", help="Build backend only")
    parser.add_argument(
        "--phase3-closure",
        action="store_true",
        help="Run WS22 Phase3 closure chain as release gate before build",
    )
    parser.add_argument(
        "--phase3-closure-output",
        type=Path,
        default=Path("scratch/reports/ws22_phase3_release_chain_result.json"),
        help="Output path for Phase3 closure chain report",
    )
    parser.add_argument(
        "--phase3-closure-timeout-seconds",
        type=int,
        default=2400,
        help="Per-step timeout for Phase3 closure chain",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    start_time = time.time()
    backend_dist_dir = DEFAULT_BACKEND_DIST_DIR

    total_steps = 3
    if args.phase3_closure:
        total_steps += 1

    step = 0

    step += 1
    log_step(step, total_steps, "Environment checks")
    if not check_environment():
        log("Environment check failed")
        sys.exit(1)

    step += 1
    log_step(step, total_steps, "Sync Python dependencies")
    sync_dependencies()

    if args.phase3_closure:
        step += 1
        log_step(step, total_steps, "Run Phase3 closure chain gate")
        run_phase3_closure_chain(
            output_file=args.phase3_closure_output,
            timeout_seconds=max(30, int(args.phase3_closure_timeout_seconds)),
        )

    step += 1
    log_step(step, total_steps, "Build backend via PyInstaller")
    build_backend(backend_dist_dir=backend_dist_dir)

    print_summary(backend_dist_dir=backend_dist_dir)
    elapsed = time.time() - start_time
    log(f"Total elapsed: {elapsed / 60:.1f} min")


if __name__ == "__main__":
    main()
