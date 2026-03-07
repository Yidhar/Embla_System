from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from core.security.audit_ledger import AuditLedger

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
_DEFAULT_AUDIT_LEDGER_RELATIVE_PATH = Path("scratch/runtime/audit_ledger.jsonl")
_DEFAULT_SUBMISSION_ROOT = Path("scratch/runtime/worktree_submissions")
_DEFAULT_DIFF_PREVIEW_CHARS = 12000


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
            "workspace_submission_state": "sandboxed",
            "workspace_change_id": "",
            "workspace_audit_report_path": "",
            "workspace_audit_diff_path": "",
            "workspace_submission_changed_files": [],
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


def _run_git_bytes(repo_root: Path, command: Sequence[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        list(command),
        cwd=str(repo_root),
        capture_output=True,
        text=False,
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
        "workspace_submission_state",
        "workspace_change_id",
        "workspace_audit_report_path",
        "workspace_audit_diff_path",
        "workspace_submission_changed_files",
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


def _is_within_root(candidate: Path, root: Path) -> bool:
    try:
        root_s = os.path.normcase(os.path.abspath(str(root)))
        cand_s = os.path.normcase(os.path.abspath(str(candidate)))
        return os.path.commonpath([root_s, cand_s]) == root_s
    except Exception:
        return False


def _safe_slug(value: Any) -> str:
    text = str(value or "").strip().replace("/", "_").replace("\\", "_")
    if not text:
        return "item"
    return "".join(ch if ch.isalnum() or ch in {"_", "-", "."} else "_" for ch in text)


def _resolve_repo_relative_path(root: Path, relative_path: str) -> Path:
    raw = Path(relative_path)
    if raw.is_absolute():
        raise ValueError(f"path must stay repo-relative: {relative_path}")
    resolved = (root / raw).resolve(strict=False)
    if not _is_within_root(resolved, root):
        raise ValueError(f"path escapes repo root: {relative_path}")
    return resolved


def _resolve_audit_ledger(repo_root: Path) -> tuple[AuditLedger, Path]:
    signing_key_env = "EMBLA_AUDIT_SIGNING_KEY"
    try:
        from system.config import get_embla_system_config

        embla_system = get_embla_system_config()
    except Exception:
        embla_system = {}

    security = embla_system.get("security") if isinstance(embla_system, dict) else {}
    ledger_raw = str(security.get("audit_ledger_file") or "").strip() if isinstance(security, dict) else ""
    if ledger_raw:
        ledger_path = Path(ledger_raw)
        if not ledger_path.is_absolute():
            ledger_path = repo_root / ledger_path
    else:
        ledger_path = repo_root / _DEFAULT_AUDIT_LEDGER_RELATIVE_PATH

    if isinstance(security, dict):
        signing_key_env = str(security.get("audit_signing_key_env") or signing_key_env).strip() or signing_key_env

    return AuditLedger(ledger_file=ledger_path, signing_key_env=signing_key_env), ledger_path


def _build_submission_dir(repo_root: Path, owner_session_id: str, change_id: str) -> Path:
    return (repo_root / _DEFAULT_SUBMISSION_ROOT / _safe_slug(owner_session_id) / _safe_slug(change_id)).resolve()


def _preview_diff(text: str, *, limit: int = _DEFAULT_DIFF_PREVIEW_CHARS) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n...(truncated, total={len(text)} chars)"


def _parse_git_status_entries(status_text: str) -> List[Dict[str, str]]:
    entries: List[Dict[str, str]] = []
    for raw_line in status_text.splitlines():
        line = raw_line.rstrip("\n")
        if not line:
            continue
        code = line[:2] if len(line) >= 2 else "??"
        remainder = line[3:] if len(line) > 3 else ""
        old_path = ""
        path = remainder
        if " -> " in remainder and ("R" in code or "C" in code):
            old_path, path = remainder.split(" -> ", 1)
        entries.append(
            {
                "code": code,
                "path": path.strip(),
                "old_path": old_path.strip(),
            }
        )
    return entries


def _read_worktree_status_entries(worktree_root: Path, *, git_runner: GitRunner) -> List[Dict[str, str]]:
    result = _run_git_checked(
        repo_root=worktree_root,
        command=["git", "-c", "core.quotepath=false", "status", "--porcelain=1", "--untracked-files=all"],
        git_runner=git_runner,
    )
    return _parse_git_status_entries(result.stdout)


def _collect_tracked_diff_text(worktree_root: Path, *, git_runner: GitRunner) -> str:
    result = _run_git_checked(
        repo_root=worktree_root,
        command=["git", "-c", "core.quotepath=false", "diff", "--binary", "HEAD", "--"],
        git_runner=git_runner,
    )
    return result.stdout


def _collect_tracked_diff_stat(worktree_root: Path, *, git_runner: GitRunner) -> List[str]:
    result = _run_git_checked(
        repo_root=worktree_root,
        command=["git", "-c", "core.quotepath=false", "diff", "--stat", "HEAD", "--"],
        git_runner=git_runner,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


def _read_git_blob_bytes(repo_root: Path, base_sha: str, relative_path: str) -> Optional[bytes]:
    normalized_base = str(base_sha or "").strip()
    normalized_path = str(relative_path or "").strip().replace("\\", "/")
    if not normalized_base or not normalized_path:
        return None
    result = _run_git_bytes(repo_root, ["git", "show", f"{normalized_base}:{normalized_path}"])
    if result.returncode != 0:
        return None
    return bytes(result.stdout)


def _build_worktree_operations(status_entries: Sequence[Mapping[str, str]]) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    operations: List[Dict[str, Any]] = []
    unsupported: List[Dict[str, Any]] = []

    for entry in status_entries:
        code = str(entry.get("code") or "??")[:2]
        path = str(entry.get("path") or "").strip()
        old_path = str(entry.get("old_path") or "").strip()
        normalized_code = code.replace(" ", "")
        flags = set(normalized_code)

        if not path:
            unsupported.append({
                "code": code,
                "path": path,
                "old_path": old_path,
                "reason": "missing path",
            })
            continue

        if "U" in flags:
            unsupported.append({
                "code": code,
                "path": path,
                "old_path": old_path,
                "reason": "unmerged status is not supported for promotion",
            })
            continue

        if normalized_code == "??":
            operations.append(
                {
                    "action": "write",
                    "path": path,
                    "source_path": path,
                    "status_code": code,
                    "kind": "untracked",
                }
            )
            continue

        if "R" in flags:
            if not old_path:
                unsupported.append({
                    "code": code,
                    "path": path,
                    "old_path": old_path,
                    "reason": "rename missing old_path",
                })
                continue
            operations.append(
                {
                    "action": "delete",
                    "path": old_path,
                    "status_code": code,
                    "kind": "rename_delete",
                }
            )
            operations.append(
                {
                    "action": "write",
                    "path": path,
                    "source_path": path,
                    "status_code": code,
                    "kind": "rename_write",
                    "old_path": old_path,
                }
            )
            continue

        if "C" in flags:
            operations.append(
                {
                    "action": "write",
                    "path": path,
                    "source_path": path,
                    "status_code": code,
                    "kind": "copy",
                    "old_path": old_path,
                }
            )
            continue

        if "D" in flags:
            operations.append(
                {
                    "action": "delete",
                    "path": path,
                    "status_code": code,
                    "kind": "delete",
                }
            )
            continue

        operations.append(
            {
                "action": "write",
                "path": path,
                "source_path": path,
                "status_code": code,
                "kind": "write",
            }
        )

    return operations, unsupported


def _build_change_id(owner_session_id: str, change_id: str = "") -> str:
    normalized = _safe_slug(change_id)
    if change_id and normalized:
        return normalized
    return f"wt_{_safe_slug(owner_session_id)}_{int(time.time() * 1000)}"


def _write_submission_artifacts(
    *,
    repo_root: Path,
    owner_session_id: str,
    change_id: str,
    report_payload: Dict[str, Any],
    tracked_diff_text: str,
) -> Dict[str, str]:
    submission_dir = _build_submission_dir(repo_root, owner_session_id, change_id)
    submission_dir.mkdir(parents=True, exist_ok=True)

    report_path = submission_dir / "audit_report.json"
    report_path.write_text(json.dumps(report_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    diff_path = submission_dir / "tracked_changes.diff"
    if tracked_diff_text.strip():
        diff_path.write_text(tracked_diff_text, encoding="utf-8")
        diff_path_text = str(diff_path)
    else:
        diff_path_text = ""
        if diff_path.exists():
            diff_path.unlink()

    return {
        "submission_dir": str(submission_dir),
        "report_path": str(report_path),
        "diff_path": diff_path_text,
    }


def _append_worktree_ledger_record(
    *,
    repo_root: Path,
    record_type: str,
    change_id: str,
    requested_by: str,
    payload: Dict[str, Any],
    approved_by: str = "",
    approval_ticket: str = "",
    evidence_refs: Optional[List[str]] = None,
    risk_level: str = "high",
) -> Dict[str, str]:
    ledger, ledger_path = _resolve_audit_ledger(repo_root)
    record = ledger.append_record(
        record_type=record_type,
        change_id=change_id,
        scope="self_maintenance_worktree",
        risk_level=risk_level,
        requested_by=str(requested_by or "worktree_runtime").strip() or "worktree_runtime",
        approved_by=str(approved_by or "").strip(),
        approval_ticket=str(approval_ticket or "").strip(),
        evidence_refs=[str(item) for item in (evidence_refs or []) if str(item or "").strip()],
        payload=payload,
    )
    return {
        "ledger_file": str(ledger_path),
        "ledger_hash": str(record.ledger_hash),
        "generated_at": str(record.generated_at),
    }


def _collect_worktree_snapshot(
    *,
    owner_session_id: str,
    worktree_root: str | Path,
    repo_root: Optional[str | Path] = None,
    base_sha: str = "",
    git_runner: GitRunner = run_git_command,
    max_diff_chars: int = _DEFAULT_DIFF_PREVIEW_CHARS,
) -> Dict[str, Any]:
    resolved_worktree_root = Path(worktree_root).resolve()
    if not resolved_worktree_root.exists():
        raise FileNotFoundError(f"worktree root not found: {resolved_worktree_root}")

    resolved_repo_root = resolve_git_repo_root(
        Path(repo_root).resolve() if repo_root else resolved_worktree_root,
        git_runner=git_runner,
    )
    status_entries = _read_worktree_status_entries(resolved_worktree_root, git_runner=git_runner)
    operations, unsupported_entries = _build_worktree_operations(status_entries)
    tracked_diff_text = _collect_tracked_diff_text(resolved_worktree_root, git_runner=git_runner)
    diff_stat_lines = _collect_tracked_diff_stat(resolved_worktree_root, git_runner=git_runner)
    current_worktree_head = resolve_head_sha(resolved_worktree_root, git_runner=git_runner)
    current_repo_head = resolve_head_sha(resolved_repo_root, git_runner=git_runner)
    normalized_base_sha = str(base_sha or "").strip() or current_worktree_head
    changed_files = sorted({str(item.get("path") or "").replace("\\", "/") for item in operations if str(item.get("path") or "").strip()})
    clean = len(status_entries) == 0
    promotion_ready = (not clean) and not unsupported_entries

    return {
        "owner_session_id": str(owner_session_id or "").strip(),
        "repo_root": str(resolved_repo_root),
        "worktree_root": str(resolved_worktree_root),
        "base_sha": normalized_base_sha,
        "worktree_head_sha": current_worktree_head,
        "repo_head_sha": current_repo_head,
        "status_entries": [dict(item) for item in status_entries],
        "operations": [dict(item) for item in operations],
        "unsupported_entries": [dict(item) for item in unsupported_entries],
        "changed_files": changed_files,
        "tracked_diff_text": tracked_diff_text,
        "tracked_diff_preview": _preview_diff(tracked_diff_text, limit=max_diff_chars),
        "diff_stat_lines": diff_stat_lines[:80],
        "clean": bool(clean),
        "promotion_ready": bool(promotion_ready),
    }


def audit_git_worktree_sandbox(
    *,
    owner_session_id: str,
    worktree_root: str | Path,
    repo_root: Optional[str | Path] = None,
    base_sha: str = "",
    change_id: str = "",
    requested_by: str = "",
    git_runner: GitRunner = run_git_command,
    max_diff_chars: int = _DEFAULT_DIFF_PREVIEW_CHARS,
) -> Dict[str, Any]:
    snapshot = _collect_worktree_snapshot(
        owner_session_id=owner_session_id,
        worktree_root=worktree_root,
        repo_root=repo_root,
        base_sha=base_sha,
        git_runner=git_runner,
        max_diff_chars=max_diff_chars,
    )
    resolved_repo_root = Path(str(snapshot["repo_root"]))
    resolved_change_id = _build_change_id(owner_session_id, change_id)
    report_payload = {
        "generated_at": _utc_now_iso(),
        "change_id": resolved_change_id,
        "owner_session_id": str(owner_session_id or "").strip(),
        "repo_root": str(snapshot["repo_root"]),
        "worktree_root": str(snapshot["worktree_root"]),
        "base_sha": str(snapshot["base_sha"]),
        "worktree_head_sha": str(snapshot["worktree_head_sha"]),
        "repo_head_sha": str(snapshot["repo_head_sha"]),
        "clean": bool(snapshot["clean"]),
        "promotion_ready": bool(snapshot["promotion_ready"]),
        "changed_files": list(snapshot["changed_files"]),
        "status_entries": list(snapshot["status_entries"]),
        "unsupported_entries": list(snapshot["unsupported_entries"]),
        "diff_stat_lines": list(snapshot["diff_stat_lines"]),
        "tracked_diff_preview": str(snapshot["tracked_diff_preview"]),
    }
    artifacts = _write_submission_artifacts(
        repo_root=resolved_repo_root,
        owner_session_id=owner_session_id,
        change_id=resolved_change_id,
        report_payload=report_payload,
        tracked_diff_text=str(snapshot["tracked_diff_text"]),
    )
    ledger_info = _append_worktree_ledger_record(
        repo_root=resolved_repo_root,
        record_type="worktree_audit",
        change_id=resolved_change_id,
        requested_by=requested_by or owner_session_id,
        payload={
            "worktree_root": str(snapshot["worktree_root"]),
            "base_sha": str(snapshot["base_sha"]),
            "worktree_head_sha": str(snapshot["worktree_head_sha"]),
            "repo_head_sha": str(snapshot["repo_head_sha"]),
            "changed_files": list(snapshot["changed_files"]),
            "promotion_ready": bool(snapshot["promotion_ready"]),
            "unsupported_entries": list(snapshot["unsupported_entries"]),
        },
        evidence_refs=[artifacts["report_path"], artifacts["diff_path"]],
        risk_level="high",
    )
    return {
        "status": "success",
        "change_id": resolved_change_id,
        "repo_root": str(snapshot["repo_root"]),
        "worktree_root": str(snapshot["worktree_root"]),
        "base_sha": str(snapshot["base_sha"]),
        "worktree_head_sha": str(snapshot["worktree_head_sha"]),
        "repo_head_sha": str(snapshot["repo_head_sha"]),
        "clean": bool(snapshot["clean"]),
        "promotion_ready": bool(snapshot["promotion_ready"]),
        "changed_files": list(snapshot["changed_files"]),
        "status_entries": list(snapshot["status_entries"]),
        "unsupported_entries": list(snapshot["unsupported_entries"]),
        "diff_stat_lines": list(snapshot["diff_stat_lines"]),
        "tracked_diff_preview": str(snapshot["tracked_diff_preview"]),
        "submission_dir": artifacts["submission_dir"],
        "report_path": artifacts["report_path"],
        "diff_path": artifacts["diff_path"],
        "audit_ledger_file": ledger_info["ledger_file"],
        "audit_ledger_hash": ledger_info["ledger_hash"],
        "audit_generated_at": ledger_info["generated_at"],
    }


def _detect_promote_conflicts(
    *,
    repo_root: Path,
    worktree_root: Path,
    base_sha: str,
    operations: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    conflicts: List[Dict[str, Any]] = []
    seen_paths: set[str] = set()

    for item in operations:
        action = str(item.get("action") or "").strip().lower()
        relative_path = str(item.get("path") or "").strip().replace("\\", "/")
        if not relative_path or relative_path in seen_paths:
            continue
        seen_paths.add(relative_path)
        target_path = _resolve_repo_relative_path(repo_root, relative_path)
        baseline_bytes = _read_git_blob_bytes(repo_root, base_sha, relative_path)
        current_exists = target_path.exists()
        current_bytes = target_path.read_bytes() if current_exists and target_path.is_file() else None

        if action == "delete":
            if baseline_bytes is None:
                continue
            if current_exists and current_bytes != baseline_bytes:
                conflicts.append(
                    {
                        "path": relative_path,
                        "reason": "target file diverged from base before delete promote",
                    }
                )
            continue

        source_path = _resolve_repo_relative_path(worktree_root, str(item.get("source_path") or relative_path))
        if not source_path.exists() or not source_path.is_file():
            conflicts.append(
                {
                    "path": relative_path,
                    "reason": "worktree source file missing during promote",
                }
            )
            continue
        desired_bytes = source_path.read_bytes()

        if current_exists and target_path.is_dir():
            conflicts.append(
                {
                    "path": relative_path,
                    "reason": "target path is a directory",
                }
            )
            continue

        if current_bytes == desired_bytes:
            continue

        if baseline_bytes is None:
            if current_exists and current_bytes != desired_bytes:
                conflicts.append(
                    {
                        "path": relative_path,
                        "reason": "new target path already exists with different content",
                    }
                )
            continue

        if current_bytes is None:
            conflicts.append(
                {
                    "path": relative_path,
                    "reason": "target path is missing but tracked baseline exists",
                }
            )
            continue

        if current_bytes != baseline_bytes and current_bytes != desired_bytes:
            conflicts.append(
                {
                    "path": relative_path,
                    "reason": "target file diverged from base before promote",
                }
            )

    return conflicts


def _apply_promote_operations(
    *,
    repo_root: Path,
    worktree_root: Path,
    operations: Sequence[Mapping[str, Any]],
    submission_dir: Path,
) -> Dict[str, Any]:
    backup_dir = submission_dir / "backup"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backups: List[Dict[str, Any]] = []
    touched_paths: List[str] = []
    seen_paths: set[str] = set()

    for item in operations:
        relative_path = str(item.get("path") or "").strip().replace("\\", "/")
        if not relative_path or relative_path in seen_paths:
            continue
        seen_paths.add(relative_path)
        touched_paths.append(relative_path)
        target_path = _resolve_repo_relative_path(repo_root, relative_path)
        backup_entry: Dict[str, Any] = {
            "path": relative_path,
            "existed": bool(target_path.exists()),
            "is_file": bool(target_path.exists() and target_path.is_file()),
            "backup_path": "",
        }
        if target_path.exists() and target_path.is_file():
            backup_path = backup_dir / relative_path
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target_path, backup_path)
            backup_entry["backup_path"] = str(backup_path)
        backups.append(backup_entry)

    changed_files: List[str] = []
    deleted_files: List[str] = []
    try:
        for item in operations:
            action = str(item.get("action") or "").strip().lower()
            relative_path = str(item.get("path") or "").strip().replace("\\", "/")
            if not relative_path:
                continue
            target_path = _resolve_repo_relative_path(repo_root, relative_path)
            if action == "delete":
                if target_path.exists() and target_path.is_file():
                    target_path.unlink()
                deleted_files.append(relative_path)
                continue

            source_path = _resolve_repo_relative_path(worktree_root, str(item.get("source_path") or relative_path))
            if not source_path.exists() or not source_path.is_file():
                raise FileNotFoundError(f"worktree source file missing: {source_path}")
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target_path)
            changed_files.append(relative_path)
    except Exception:
        for entry in reversed(backups):
            relative_path = str(entry.get("path") or "").strip().replace("\\", "/")
            if not relative_path:
                continue
            target_path = _resolve_repo_relative_path(repo_root, relative_path)
            backup_path_raw = str(entry.get("backup_path") or "").strip()
            if bool(entry.get("existed")) and backup_path_raw:
                backup_path = Path(backup_path_raw)
                target_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup_path, target_path)
            elif not bool(entry.get("existed")) and target_path.exists():
                if target_path.is_file():
                    target_path.unlink()
        raise

    return {
        "changed_files": sorted(set(changed_files)),
        "deleted_files": sorted(set(deleted_files)),
        "backup_dir": str(backup_dir),
    }


def promote_git_worktree_sandbox(
    *,
    owner_session_id: str,
    worktree_root: str | Path,
    repo_root: Optional[str | Path] = None,
    base_sha: str = "",
    change_id: str = "",
    requested_by: str = "",
    approved_by: str = "",
    approval_ticket: str,
    notes: str = "",
    git_runner: GitRunner = run_git_command,
    max_diff_chars: int = _DEFAULT_DIFF_PREVIEW_CHARS,
) -> Dict[str, Any]:
    approval_ticket_text = str(approval_ticket or "").strip()
    if not approval_ticket_text:
        raise ValueError("approval_ticket is required for worktree promote")

    snapshot = _collect_worktree_snapshot(
        owner_session_id=owner_session_id,
        worktree_root=worktree_root,
        repo_root=repo_root,
        base_sha=base_sha,
        git_runner=git_runner,
        max_diff_chars=max_diff_chars,
    )
    resolved_repo_root = Path(str(snapshot["repo_root"]))
    resolved_worktree_root = Path(str(snapshot["worktree_root"]))
    resolved_change_id = _build_change_id(owner_session_id, change_id)

    report_payload = {
        "generated_at": _utc_now_iso(),
        "change_id": resolved_change_id,
        "owner_session_id": str(owner_session_id or "").strip(),
        "repo_root": str(snapshot["repo_root"]),
        "worktree_root": str(snapshot["worktree_root"]),
        "base_sha": str(snapshot["base_sha"]),
        "worktree_head_sha": str(snapshot["worktree_head_sha"]),
        "repo_head_sha": str(snapshot["repo_head_sha"]),
        "clean": bool(snapshot["clean"]),
        "promotion_ready": bool(snapshot["promotion_ready"]),
        "changed_files": list(snapshot["changed_files"]),
        "status_entries": list(snapshot["status_entries"]),
        "unsupported_entries": list(snapshot["unsupported_entries"]),
        "diff_stat_lines": list(snapshot["diff_stat_lines"]),
        "tracked_diff_preview": str(snapshot["tracked_diff_preview"]),
        "notes": str(notes or ""),
    }
    artifacts = _write_submission_artifacts(
        repo_root=resolved_repo_root,
        owner_session_id=owner_session_id,
        change_id=resolved_change_id,
        report_payload=report_payload,
        tracked_diff_text=str(snapshot["tracked_diff_text"]),
    )

    if bool(snapshot["clean"]):
        return {
            "status": "noop",
            "change_id": resolved_change_id,
            "message": "worktree is clean; nothing to promote",
            "report_path": artifacts["report_path"],
            "diff_path": artifacts["diff_path"],
            "changed_files": [],
            "deleted_files": [],
        }

    if not bool(snapshot["promotion_ready"]):
        return {
            "status": "blocked",
            "change_id": resolved_change_id,
            "message": "worktree contains unsupported states; audit first and resolve conflicts",
            "unsupported_entries": list(snapshot["unsupported_entries"]),
            "report_path": artifacts["report_path"],
            "diff_path": artifacts["diff_path"],
            "changed_files": list(snapshot["changed_files"]),
        }

    conflicts = _detect_promote_conflicts(
        repo_root=resolved_repo_root,
        worktree_root=resolved_worktree_root,
        base_sha=str(snapshot["base_sha"]),
        operations=list(snapshot["operations"]),
    )
    if conflicts:
        return {
            "status": "blocked",
            "change_id": resolved_change_id,
            "message": "target workspace diverged from sandbox baseline; promotion blocked",
            "conflicts": conflicts,
            "report_path": artifacts["report_path"],
            "diff_path": artifacts["diff_path"],
            "changed_files": list(snapshot["changed_files"]),
        }

    apply_result = _apply_promote_operations(
        repo_root=resolved_repo_root,
        worktree_root=resolved_worktree_root,
        operations=list(snapshot["operations"]),
        submission_dir=Path(artifacts["submission_dir"]),
    )
    ledger_info = _append_worktree_ledger_record(
        repo_root=resolved_repo_root,
        record_type="worktree_promoted",
        change_id=resolved_change_id,
        requested_by=requested_by or owner_session_id,
        approved_by=approved_by or requested_by or owner_session_id,
        approval_ticket=approval_ticket_text,
        payload={
            "worktree_root": str(snapshot["worktree_root"]),
            "base_sha": str(snapshot["base_sha"]),
            "worktree_head_sha": str(snapshot["worktree_head_sha"]),
            "repo_head_sha": str(snapshot["repo_head_sha"]),
            "changed_files": list(apply_result["changed_files"]),
            "deleted_files": list(apply_result["deleted_files"]),
            "notes": str(notes or ""),
        },
        evidence_refs=[artifacts["report_path"], artifacts["diff_path"]],
        risk_level="high",
    )
    return {
        "status": "success",
        "change_id": resolved_change_id,
        "message": "worktree changes promoted to repo root",
        "repo_root": str(snapshot["repo_root"]),
        "worktree_root": str(snapshot["worktree_root"]),
        "report_path": artifacts["report_path"],
        "diff_path": artifacts["diff_path"],
        "changed_files": list(apply_result["changed_files"]),
        "deleted_files": list(apply_result["deleted_files"]),
        "audit_ledger_file": ledger_info["ledger_file"],
        "audit_ledger_hash": ledger_info["ledger_hash"],
        "audit_generated_at": ledger_info["generated_at"],
    }


def teardown_git_worktree_sandbox(
    *,
    owner_session_id: str,
    worktree_root: str | Path,
    repo_root: Optional[str | Path] = None,
    change_id: str = "",
    requested_by: str = "",
    reason: str = "",
    git_runner: GitRunner = run_git_command,
) -> Dict[str, Any]:
    resolved_repo_root = resolve_git_repo_root(
        Path(repo_root).resolve() if repo_root else Path(worktree_root).resolve(),
        git_runner=git_runner,
    )
    resolved_change_id = _build_change_id(owner_session_id, change_id)
    success, error = cleanup_git_worktree_sandbox(
        worktree_root=worktree_root,
        repo_root=resolved_repo_root,
        git_runner=git_runner,
    )
    ledger_info = _append_worktree_ledger_record(
        repo_root=resolved_repo_root,
        record_type="worktree_teardown",
        change_id=resolved_change_id,
        requested_by=requested_by or owner_session_id,
        payload={
            "worktree_root": str(Path(worktree_root).resolve()),
            "teardown_success": bool(success),
            "reason": str(reason or ""),
            "error": str(error or ""),
        },
        evidence_refs=[str(Path(worktree_root).resolve())],
        risk_level="medium",
    )
    return {
        "status": "success" if success else "error",
        "change_id": resolved_change_id,
        "message": "worktree torn down" if success else "worktree teardown failed",
        "worktree_root": str(Path(worktree_root).resolve()),
        "repo_root": str(resolved_repo_root),
        "reason": str(reason or ""),
        "error": str(error or ""),
        "audit_ledger_file": ledger_info["ledger_file"],
        "audit_ledger_hash": ledger_info["ledger_hash"],
        "audit_generated_at": ledger_info["generated_at"],
    }


__all__ = [
    "GitWorktreeSandbox",
    "apply_workspace_path_overrides",
    "audit_git_worktree_sandbox",
    "build_agent_worktree_path",
    "build_worktree_add_command",
    "build_worktree_remove_command",
    "cleanup_git_worktree_sandbox",
    "create_git_worktree_sandbox",
    "inherit_workspace_metadata",
    "normalize_workspace_mode",
    "promote_git_worktree_sandbox",
    "resolve_git_repo_root",
    "resolve_head_sha",
    "run_git_command",
    "teardown_git_worktree_sandbox",
]
