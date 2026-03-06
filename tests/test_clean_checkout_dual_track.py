from __future__ import annotations

from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import Mock

import pytest

from scripts.clean_checkout_dual_track import (
    REASON_EXIT_CODE_MISMATCH,
    REASON_MATCH,
    REASON_MATCH_NONZERO_EXIT,
    REASON_NORMALIZED_OUTPUT_MISMATCH,
    build_worktree_add_command,
    build_worktree_remove_command,
    cleanup_worktree,
    create_clean_worktree,
    decide_dual_track_result,
    digest_text,
    normalize_output,
)


def test_normalize_output_rewrites_paths_and_newlines() -> None:
    workspace_root = r"C:\repo\Embla_System"
    clean_root = r"C:\repo\Embla_System\scratch\clean_ws17"
    raw = (
        "line-one   \r\n"
        f"workspace={workspace_root}\\tests\\case.py\r\n"
        f"clean={clean_root}/tests/case.py   \r\n"
    )
    normalized = normalize_output(
        raw,
        replacements={
            workspace_root: "<REPO_ROOT>",
            clean_root: "<REPO_ROOT>",
        },
    )

    assert "\r" not in normalized
    assert normalized.splitlines()[0] == "line-one"
    assert workspace_root not in normalized
    assert clean_root not in normalized
    assert normalized.count("<REPO_ROOT>") == 2


def test_digest_text_is_deterministic_and_sensitive() -> None:
    digest_a = digest_text("alpha\nbeta")
    digest_b = digest_text("alpha\nbeta")
    digest_c = digest_text("alpha\nbeta!")

    assert digest_a == digest_b
    assert digest_a != digest_c


def test_decide_dual_track_result_detects_exit_code_mismatch() -> None:
    match, reason = decide_dual_track_result(
        workspace_exit_code=0,
        workspace_digest="aaa",
        clean_exit_code=2,
        clean_digest="aaa",
    )
    assert match is False
    assert reason == REASON_EXIT_CODE_MISMATCH


def test_decide_dual_track_result_detects_digest_mismatch() -> None:
    match, reason = decide_dual_track_result(
        workspace_exit_code=0,
        workspace_digest="aaa",
        clean_exit_code=0,
        clean_digest="bbb",
    )
    assert match is False
    assert reason == REASON_NORMALIZED_OUTPUT_MISMATCH


def test_decide_dual_track_result_nonzero_match_reason() -> None:
    match, reason = decide_dual_track_result(
        workspace_exit_code=1,
        workspace_digest="same",
        clean_exit_code=1,
        clean_digest="same",
    )
    assert match is True
    assert reason == REASON_MATCH_NONZERO_EXIT


def test_decide_dual_track_result_zero_exit_match_reason() -> None:
    match, reason = decide_dual_track_result(
        workspace_exit_code=0,
        workspace_digest="same",
        clean_exit_code=0,
        clean_digest="same",
    )
    assert match is True
    assert reason == REASON_MATCH


def test_worktree_command_builders() -> None:
    worktree_path = Path("scratch/clean_checkout_dual_track/ws17")

    assert build_worktree_add_command(worktree_path, "HEAD") == [
        "git",
        "worktree",
        "add",
        "--detach",
        str(worktree_path),
        "HEAD",
    ]
    assert build_worktree_remove_command(worktree_path) == [
        "git",
        "worktree",
        "remove",
        str(worktree_path),
    ]


def test_create_clean_worktree_uses_git_runner_mock() -> None:
    repo_root = Path("E:/Programs/Embla_System")
    worktree_path = repo_root / "scratch" / "clean_checkout_dual_track" / "ws17"
    git_runner = Mock(return_value=CompletedProcess(args=["git"], returncode=0, stdout="", stderr=""))

    create_clean_worktree(repo_root, worktree_path, "HEAD~1", git_runner=git_runner)

    git_runner.assert_called_once_with(
        repo_root,
        ["git", "worktree", "add", "--detach", str(worktree_path), "HEAD~1"],
    )


def test_create_clean_worktree_raises_when_git_fails() -> None:
    repo_root = Path("E:/Programs/Embla_System")
    worktree_path = repo_root / "scratch" / "clean_checkout_dual_track" / "ws17_fail"
    git_runner = Mock(return_value=CompletedProcess(args=["git"], returncode=1, stdout="", stderr="boom"))

    with pytest.raises(RuntimeError, match="git command failed"):
        create_clean_worktree(repo_root, worktree_path, "HEAD", git_runner=git_runner)


def test_cleanup_worktree_returns_failure_details() -> None:
    repo_root = Path("E:/Programs/Embla_System")
    worktree_path = repo_root / "scratch" / "clean_checkout_dual_track" / "ws17_cleanup"
    git_runner = Mock(return_value=CompletedProcess(args=["git"], returncode=1, stdout="", stderr="dirty tree"))

    success, error = cleanup_worktree(repo_root, worktree_path, git_runner=git_runner)

    assert success is False
    assert "dirty tree" in error
    git_runner.assert_called_once_with(repo_root, ["git", "worktree", "remove", str(worktree_path)])
