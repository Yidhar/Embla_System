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
FRONTEND_DIR = PROJECT_ROOT / "frontend"
BACKEND_DIST_DIR = FRONTEND_DIR / "backend-dist"
SPEC_FILE = PROJECT_ROOT / "naga-backend.spec"

MIN_NODE_MAJOR = 22
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

    node_ver = get_cmd_version("node")
    if node_ver:
        major = int(node_ver.lstrip("v").split(".")[0])
        if major >= MIN_NODE_MAJOR:
            log(f"Node.js {node_ver} OK")
        else:
            log(f"Node.js {node_ver} too old, requires >= {MIN_NODE_MAJOR}")
            ok = False
    else:
        log(f"Node.js not found (requires >= {MIN_NODE_MAJOR})")
        ok = False

    npm_ver = get_cmd_version("npm")
    if npm_ver:
        log(f"npm {npm_ver} OK")
    else:
        log("npm not found")
        ok = False

    return ok


def sync_dependencies() -> None:
    run(["uv", "sync", "--group", "build"], cwd=PROJECT_ROOT)
    log("Python dependencies synced")


def build_backend() -> None:
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
            str(BACKEND_DIST_DIR),
            "--workpath",
            str(work_dir),
            "--clean",
            "-y",
        ],
        cwd=PROJECT_ROOT,
    )

    backend_exe = BACKEND_DIST_DIR / "naga-backend" / "naga-backend.exe"
    if not backend_exe.exists():
        raise FileNotFoundError(f"backend artifact missing: {backend_exe}")
    log(f"Backend build complete: {backend_exe}")


def build_frontend(debug: bool = False) -> None:
    node_modules = FRONTEND_DIR / "node_modules"
    if not node_modules.exists():
        log("Installing frontend dependencies...")
        run(["npm", "install"], cwd=FRONTEND_DIR)

    if debug:
        run(
            [
                "npm",
                "run",
                "dist:win",
                "--",
                "-c.extraMetadata.nagaDebugConsole=true",
            ],
            cwd=FRONTEND_DIR,
        )
    else:
        run(["npm", "run", "dist:win"], cwd=FRONTEND_DIR)

    log("Electron package build complete")


def print_summary() -> None:
    print()
    print("=" * 50)
    print("  Build complete")
    print("=" * 50)

    backend_dir = BACKEND_DIST_DIR / "naga-backend"
    if backend_dir.exists():
        size = sum(f.stat().st_size for f in backend_dir.rglob("*") if f.is_file())
        log(f"Backend artifact: {backend_dir} ({size / 1024 / 1024:.0f} MB)")

    release_dir = FRONTEND_DIR / "release"
    if release_dir.exists():
        for f in release_dir.glob("*.exe"):
            log(f"Installer: {f} ({f.stat().st_size / 1024 / 1024:.0f} MB)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="NagaAgent Windows build script")
    parser.add_argument("--backend-only", action="store_true", help="Build backend only")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Build installer with backend debug console metadata",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    start_time = time.time()

    total_steps = 3
    if not args.backend_only:
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

    step += 1
    log_step(step, total_steps, "Build backend via PyInstaller")
    build_backend()

    if not args.backend_only:
        step += 1
        title = "Build Electron frontend (DEBUG)" if args.debug else "Build Electron frontend"
        log_step(step, total_steps, title)
        build_frontend(debug=args.debug)

    print_summary()
    elapsed = time.time() - start_time
    log(f"Total elapsed: {elapsed / 60:.1f} min")


if __name__ == "__main__":
    main()
