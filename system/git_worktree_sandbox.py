from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Sequence

logger = logging.getLogger(__name__)

GitRunner = Callable[[Path, Sequence[str]], subprocess.CompletedProcess[str]]

_GIT_CONTEXT_TOOLS = {
    "git_status",
    "git_diff",
    "git_log",
    "git_show",
    "git_blame",
    "git_grep",
    "git_changed_files",
    "git_checkout_file",
}
_CWD_CONTEXT_TOOLS = {
    "run_cmd",
    "python_repl",
    "sleep_and_watch",
    "get_cwd",
}
_FILE_PATH_TOOLS = {
    "read_file",
    "write_file",
    "file_ast_skeleton",
    "file_ast_chunk_read",
}
_SEARCH_PATH_TOOLS = {
    "search_keyword",
    "list_files",
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class GitWorktreeSandbox:
    owner_session_id: str
    repo_root: str
    worktree_root: str
    ref: str
    head_sha: str
    created_at: str
    sandbox_type: str = "git_worktree"
    cleanup_on_destroy: bool = True

    def to_metadata(self) -> Dict[str, Any]:
        return {
            "workspace_mode": "worktree",
            "workspace_sandbox_type": self.sandbox_type,
            "workspace_origin_root": self.repo_root,
            "workspace_root": self.worktree_root,
            "workspace_ref": self.ref,
            "workspace_head_sha": self.head_sha,
            "workspace_owner_session_id": self.owner_session_id,
            "workspace_cleanup_on_destroy": bool(self.cleanup_on_destroy),
            "workspace_created_at": self.created_at,
        }


def build_worktree_add_command(worktree_path: Path, ref: str) -> list[str]:
    return ["git", "worktree", "add", "--detach", str(worktree_path), ref]


def build_worktree_remove_command(worktree_path: Path, *, force: bool = True) -> list[str]:
    command = ["git", "worktree", "remove"]
    if force:
        command.append("--force")
    command.append(str(worktree_path))
    return command


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
    failure = (result.stderr or result.stdout or "").strip() or f"exit_code={result.returncode}"
    raise RuntimeError(f"git command failed: {' '.join(command)} :: {failure}")


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


def build_agent_worktree_path(repo_root: Path, owner_session_id: str) -> Path:
    safe_owner = str(owner_session_id or "agent").strip().replace("/", "_").replace("\\", "_")
    return (repo_root / "scratch" / "agent_worktrees" / safe_owner).resolve()


def create_git_worktree_sandbox(
    *,
    owner_session_id: str,
    ref: str = "HEAD",
    repo_root: Optional[str | Path] = None,
    git_runner: GitRunner = run_git_command,
) -> GitWorktreeSandbox:
    start_dir = Path(repo_root).resolve() if repo_root else Path(__file__).resolve().parents[1]
    resolved_repo_root = resolve_git_repo_root(start_dir, git_runner=git_runner)
    worktree_path = build_agent_worktree_path(resolved_repo_root, owner_session_id)
    worktree_path.parent.mkdir(parents=True, exist_ok=True)
    if worktree_path.exists():
        raise RuntimeError(f"worktree path already exists: {worktree_path}")
    _run_git_checked(
        repo_root=resolved_repo_root,
        command=build_worktree_add_command(worktree_path, ref or "HEAD"),
        git_runner=git_runner,
    )
    return GitWorktreeSandbox(
        owner_session_id=str(owner_session_id or "").strip(),
        repo_root=str(resolved_repo_root),
        worktree_root=str(worktree_path),
        ref=str(ref or "HEAD").strip() or "HEAD",
        head_sha=resolve_head_sha(resolved_repo_root, git_runner=git_runner),
        created_at=_utc_now_iso(),
    )


def cleanup_git_worktree_sandbox(
    *,
    worktree_root: str | Path,
    repo_root: Optional[str | Path] = None,
    git_runner: GitRunner = run_git_command,
) -> tuple[bool, str]:
    worktree_path = Path(worktree_root).resolve()
    if not worktree_path.exists():
        return True, ""
    resolved_repo_root = resolve_git_repo_root(
        Path(repo_root).resolve() if repo_root else Path(__file__).resolve().parents[1],
        git_runner=git_runner,
    )
    result = git_runner(resolved_repo_root, build_worktree_remove_command(worktree_path, force=True))
    if result.returncode == 0:
        return True, ""
    error = (result.stderr or result.stdout or "").strip() or f"exit_code={result.returncode}"
    return False, error


def inherit_workspace_metadata(parent_metadata: Mapping[str, Any]) -> Dict[str, Any]:
    inherited: Dict[str, Any] = {}
    for key in (
        "workspace_mode",
        "workspace_sandbox_type",
        "workspace_origin_root",
        "workspace_root",
        "workspace_ref",
        "workspace_head_sha",
        "workspace_owner_session_id",
        "workspace_cleanup_on_destroy",
        "workspace_created_at",
    ):
        value = parent_metadata.get(key)
        if value not in (None, ""):
            inherited[key] = value
    return inherited


def normalize_workspace_mode(raw: Any) -> str:
    text = str(raw or "").strip().lower()
    aliases = {
        "": "inherit",
        "default": "inherit",
        "shared": "project",
        "repo": "project",
        "current": "project",
        "sandbox": "worktree",
        "git_worktree": "worktree",
    }
    text = aliases.get(text, text)
    if text not in {"inherit", "project", "worktree"}:
        raise ValueError(f"unsupported workspace_mode: {raw}")
    return text


def _resolve_workspace_path(value: Any, workspace_root: Path) -> str:
    text = str(value or "").strip()
    if not text:
        return text
    raw = Path(text)
    if raw.is_absolute():
        return str(raw)
    return str((workspace_root / raw).resolve())


def apply_workspace_path_overrides(
    tool_name: str,
    arguments: Dict[str, Any],
    workspace_root: str | Path,
) -> Dict[str, Any]:
    root = Path(workspace_root).resolve()
    normalized_tool = str(tool_name or "").strip().lower()
    safe_arguments = dict(arguments) if isinstance(arguments, dict) else {}

    if normalized_tool in _GIT_CONTEXT_TOOLS:
        safe_arguments.setdefault("repo_path", str(root))
        safe_arguments.setdefault("cwd", str(root))
        return safe_arguments

    if normalized_tool in _CWD_CONTEXT_TOOLS:
        safe_arguments.setdefault("cwd", str(root))
        if normalized_tool == "sleep_and_watch":
            for key in ("log_file", "path"):
                if key in safe_arguments:
                    safe_arguments[key] = _resolve_workspace_path(safe_arguments.get(key), root)
        return safe_arguments

    if normalized_tool in _FILE_PATH_TOOLS:
        for key in ("path", "file_path"):
            if key in safe_arguments:
                safe_arguments[key] = _resolve_workspace_path(safe_arguments.get(key), root)
        return safe_arguments

    if normalized_tool in _SEARCH_PATH_TOOLS:
        key = "search_path" if normalized_tool == "search_keyword" else "path"
        current = safe_arguments.get(key)
        if current in (None, "", "."):
            safe_arguments[key] = str(root)
        else:
            safe_arguments[key] = _resolve_workspace_path(current, root)
        return safe_arguments

    if normalized_tool == "workspace_txn_apply":
        raw_changes = safe_arguments.get("changes")
        if isinstance(raw_changes, list):
            rewritten = []
            for item in raw_changes:
                if not isinstance(item, dict):
                    rewritten.append(item)
                    continue
                next_item = dict(item)
                if "path" in next_item:
                    next_item["path"] = _resolve_workspace_path(next_item.get("path"), root)
                rewritten.append(next_item)
            safe_arguments["changes"] = rewritten
        return safe_arguments

    return safe_arguments


__all__ = [
    "GitWorktreeSandbox",
    "apply_workspace_path_overrides",
    "build_agent_worktree_path",
    "build_worktree_add_command",
    "build_worktree_remove_command",
    "cleanup_git_worktree_sandbox",
    "create_git_worktree_sandbox",
    "inherit_workspace_metadata",
    "normalize_workspace_mode",
    "resolve_git_repo_root",
    "resolve_head_sha",
    "run_git_command",
]
