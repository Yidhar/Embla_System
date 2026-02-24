"""NGA-WS17-003 clean-checkout dual-track validator.

Runs the same command in:
1) the current workspace checkout, and
2) a clean `git worktree` checkout at a chosen ref.

Then compares exit codes plus normalized output digest and emits a JSON report.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


REASON_DRY_RUN = "dry_run_no_execution"
REASON_MATCH = "exit_code_and_normalized_output_match"
REASON_MATCH_NONZERO_EXIT = "exit_code_match_but_nonzero"
REASON_EXIT_CODE_MISMATCH = "exit_code_mismatch"
REASON_NORMALIZED_OUTPUT_MISMATCH = "normalized_output_digest_mismatch"
REASON_EXECUTION_ERROR = "execution_error"


@dataclass(frozen=True)
class CommandExecution:
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float


GitRunner = Callable[[Path, Sequence[str]], subprocess.CompletedProcess[str]]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _format_cli_command(command: Sequence[str]) -> str:
    return subprocess.list2cmdline(list(command))


def build_worktree_add_command(worktree_path: Path, ref: str) -> list[str]:
    return ["git", "worktree", "add", "--detach", str(worktree_path), ref]


def build_worktree_remove_command(worktree_path: Path) -> list[str]:
    return ["git", "worktree", "remove", str(worktree_path)]


def normalize_output(text: str, *, replacements: Mapping[str, str] | None = None) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")

    if replacements:
        for source, target in sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True):
            if not source:
                continue
            variants = {
                source,
                source.replace("\\", "/"),
                source.replace("/", "\\"),
            }
            for variant in sorted(variants, key=len, reverse=True):
                normalized = normalized.replace(variant, target)

    lines = [line.rstrip() for line in normalized.split("\n")]
    return "\n".join(lines).strip()


def digest_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_output_digest(stdout: str, stderr: str, *, replacements: Mapping[str, str] | None = None) -> tuple[str, str]:
    merged = f"[stdout]\n{stdout}\n[stderr]\n{stderr}"
    normalized = normalize_output(merged, replacements=replacements)
    return normalized, digest_text(normalized)


def decide_dual_track_result(
    *,
    workspace_exit_code: int,
    workspace_digest: str,
    clean_exit_code: int,
    clean_digest: str,
) -> tuple[bool, str]:
    if workspace_exit_code != clean_exit_code:
        return False, REASON_EXIT_CODE_MISMATCH
    if workspace_digest != clean_digest:
        return False, REASON_NORMALIZED_OUTPUT_MISMATCH
    if workspace_exit_code != 0:
        return True, REASON_MATCH_NONZERO_EXIT
    return True, REASON_MATCH


def run_git_command(repo_root: Path, command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )


def _run_git_checked(
    *,
    repo_root: Path,
    command: Sequence[str],
    git_runner: GitRunner = run_git_command,
) -> subprocess.CompletedProcess[str]:
    result = git_runner(repo_root, command)
    if result.returncode == 0:
        return result

    failure = (result.stderr or result.stdout or "").strip()
    if not failure:
        failure = f"exit_code={result.returncode}"
    raise RuntimeError(f"git command failed: {_format_cli_command(command)} :: {failure}")


def resolve_git_repo_root(start_dir: Path, *, git_runner: GitRunner = run_git_command) -> Path:
    result = _run_git_checked(
        repo_root=start_dir,
        command=["git", "rev-parse", "--show-toplevel"],
        git_runner=git_runner,
    )
    return Path(result.stdout.strip()).resolve()


def resolve_head_sha(repo_root: Path, *, git_runner: GitRunner = run_git_command) -> str:
    result = _run_git_checked(
        repo_root=repo_root,
        command=["git", "rev-parse", "--verify", "HEAD"],
        git_runner=git_runner,
    )
    return result.stdout.strip()


def create_clean_worktree(
    repo_root: Path,
    worktree_path: Path,
    ref: str,
    *,
    git_runner: GitRunner = run_git_command,
) -> None:
    command = build_worktree_add_command(worktree_path, ref)
    _run_git_checked(repo_root=repo_root, command=command, git_runner=git_runner)


def cleanup_worktree(
    repo_root: Path,
    worktree_path: Path,
    *,
    git_runner: GitRunner = run_git_command,
) -> tuple[bool, str]:
    result = git_runner(repo_root, build_worktree_remove_command(worktree_path))
    if result.returncode == 0:
        return True, ""
    error = (result.stderr or result.stdout or "").strip()
    if not error:
        error = f"exit_code={result.returncode}"
    return False, error


def run_shell_command(command: str, *, cwd: Path) -> CommandExecution:
    started = time.perf_counter()
    result = subprocess.run(
        command,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        shell=True,
        check=False,
    )
    elapsed = time.perf_counter() - started
    return CommandExecution(
        exit_code=int(result.returncode),
        stdout=result.stdout or "",
        stderr=result.stderr or "",
        duration_seconds=round(elapsed, 6),
    )


def _build_track_report(
    *,
    command_result: CommandExecution,
    replacements: Mapping[str, str],
) -> dict[str, Any]:
    _, digest = build_output_digest(
        command_result.stdout,
        command_result.stderr,
        replacements=replacements,
    )
    return {
        "exit_code": command_result.exit_code,
        "duration_seconds": command_result.duration_seconds,
        "normalized_output_digest": digest,
    }


def _build_worktree_path(worktree_root: Path, worktree_name: str | None) -> Path:
    if worktree_name:
        return (worktree_root / worktree_name).resolve()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return (worktree_root / f"ws17_clean_{stamp}_{os.getpid()}").resolve()


def _determine_exit_code(
    *,
    dry_run: bool,
    comparison_match: bool,
    comparison_reason: str,
    cleanup_requested: bool,
    cleanup_success: bool | None,
) -> int:
    if dry_run:
        return 0
    if not comparison_match:
        return 2
    if comparison_reason == REASON_MATCH_NONZERO_EXIT:
        return 3
    if cleanup_requested and cleanup_success is False:
        return 4
    return 0


def run_dual_track_validation(
    *,
    command: str,
    repo_root: Path,
    worktree_root: Path,
    worktree_name: str | None,
    ref: str,
    cleanup: bool,
    dry_run: bool,
) -> tuple[dict[str, Any], int]:
    resolved_root = resolve_git_repo_root(repo_root.resolve())
    head_sha = resolve_head_sha(resolved_root)
    resolved_worktree_root = worktree_root if worktree_root.is_absolute() else resolved_root / worktree_root
    resolved_worktree_root.mkdir(parents=True, exist_ok=True)
    worktree_path = _build_worktree_path(resolved_worktree_root, worktree_name)
    if worktree_path.exists():
        raise RuntimeError(f"worktree path already exists: {worktree_path}")

    add_command = build_worktree_add_command(worktree_path, ref)
    remove_command = build_worktree_remove_command(worktree_path)
    replacements = {
        str(resolved_root): "<REPO_ROOT>",
        str(worktree_path): "<REPO_ROOT>",
    }

    report: dict[str, Any] = {
        "schema_version": "1.0.0",
        "task_id": "NGA-WS17-003",
        "generated_at": _utc_now_iso(),
        "command": command,
        "ref": ref,
        "git": {
            "repo_root": str(resolved_root),
            "head_sha": head_sha,
            "worktree_path": str(worktree_path),
            "cleanup_requested": cleanup,
        },
        "planned_commands": {
            "worktree_add": _format_cli_command(add_command),
            "workspace_run": command,
            "clean_checkout_run": command,
            "worktree_remove": _format_cli_command(remove_command),
        },
        "workspace": {},
        "clean_checkout": {},
        "comparison": {
            "match": False,
            "reason": "",
        },
        "cleanup": {
            "attempted": False,
            "success": None,
            "error": "",
        },
        "dry_run": bool(dry_run),
        "error": None,
    }

    if dry_run:
        report["comparison"]["match"] = True
        report["comparison"]["reason"] = REASON_DRY_RUN
        final_exit_code = _determine_exit_code(
            dry_run=True,
            comparison_match=True,
            comparison_reason=REASON_DRY_RUN,
            cleanup_requested=cleanup,
            cleanup_success=None,
        )
        report["final_exit_code"] = final_exit_code
        return report, final_exit_code

    worktree_created = False
    cleanup_success: bool | None = None

    try:
        create_clean_worktree(resolved_root, worktree_path, ref)
        worktree_created = True

        workspace_result = run_shell_command(command, cwd=resolved_root)
        clean_result = run_shell_command(command, cwd=worktree_path)

        workspace_report = _build_track_report(command_result=workspace_result, replacements=replacements)
        clean_report = _build_track_report(command_result=clean_result, replacements=replacements)

        report["workspace"] = workspace_report
        report["clean_checkout"] = clean_report

        match, reason = decide_dual_track_result(
            workspace_exit_code=workspace_result.exit_code,
            workspace_digest=str(workspace_report["normalized_output_digest"]),
            clean_exit_code=clean_result.exit_code,
            clean_digest=str(clean_report["normalized_output_digest"]),
        )
        report["comparison"]["match"] = bool(match)
        report["comparison"]["reason"] = reason
    except Exception as exc:  # pragma: no cover - defensive runtime envelope
        report["comparison"]["match"] = False
        report["comparison"]["reason"] = REASON_EXECUTION_ERROR
        report["error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
        }
    finally:
        if worktree_created and cleanup:
            report["cleanup"]["attempted"] = True
            cleanup_success, cleanup_error = cleanup_worktree(resolved_root, worktree_path)
            report["cleanup"]["success"] = cleanup_success
            report["cleanup"]["error"] = cleanup_error

    comparison = report["comparison"]
    final_exit_code = _determine_exit_code(
        dry_run=False,
        comparison_match=bool(comparison.get("match")),
        comparison_reason=str(comparison.get("reason") or ""),
        cleanup_requested=cleanup,
        cleanup_success=cleanup_success,
    )
    report["final_exit_code"] = final_exit_code
    return report, final_exit_code


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run dual-track workspace/clean-checkout validation")
    parser.add_argument("--command", required=True, help="Command string to execute in both tracks")
    parser.add_argument("--repo-root", type=Path, default=Path("."), help="Path inside the target git repository")
    parser.add_argument("--ref", default="HEAD", help="Git ref used for clean checkout worktree")
    parser.add_argument(
        "--worktree-root",
        type=Path,
        default=Path("scratch/clean_checkout_dual_track"),
        help="Directory for temporary worktree folders",
    )
    parser.add_argument("--worktree-name", default=None, help="Optional fixed worktree folder name")
    parser.add_argument("--report-file", type=Path, default=None, help="Optional path to persist JSON report")
    parser.add_argument("--dry-run", action="store_true", help="Only emit planned commands; do not execute")

    cleanup_group = parser.add_mutually_exclusive_group()
    cleanup_group.add_argument("--cleanup", dest="cleanup", action="store_true", default=True)
    cleanup_group.add_argument("--no-cleanup", dest="cleanup", action="store_false")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report, exit_code = run_dual_track_validation(
        command=str(args.command),
        repo_root=Path(args.repo_root),
        worktree_root=Path(args.worktree_root),
        worktree_name=args.worktree_name,
        ref=str(args.ref),
        cleanup=bool(args.cleanup),
        dry_run=bool(args.dry_run),
    )

    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)

    if args.report_file is not None:
        output_file = Path(args.report_file)
        if not output_file.is_absolute():
            output_file = resolve_git_repo_root(Path(args.repo_root).resolve()) / output_file
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(rendered + "\n", encoding="utf-8")

    return int(exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
