from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from agents.runtime.agent_session import AgentSessionStore, AgentStatus
from agents.runtime.mailbox import AgentMailbox
from agents.runtime.parent_tools import handle_parent_tool_call
from agents.pipeline import _build_core_execution_receipt, _build_fast_track_execution_receipt
from system.git_worktree_sandbox import (
    audit_git_worktree_sandbox,
    create_git_worktree_sandbox,
    inherit_workspace_metadata,
    promote_git_worktree_sandbox,
    teardown_git_worktree_sandbox,
)


pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is required")


def _git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(f"git command failed: {' '.join(args)}\nstdout={result.stdout}\nstderr={result.stderr}")
    return result


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init")
    _git(repo, "config", "user.email", "embla@example.com")
    _git(repo, "config", "user.name", "Embla Test")

    tracked = repo / "system" / "runtime.txt"
    tracked.parent.mkdir(parents=True, exist_ok=True)
    tracked.write_text("BASE\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "init")
    return repo


@pytest.fixture
def store() -> AgentSessionStore:
    session_store = AgentSessionStore(db_path=":memory:")
    yield session_store
    session_store.close()


@pytest.fixture
def mailbox() -> AgentMailbox:
    agent_mailbox = AgentMailbox(db_path=":memory:")
    yield agent_mailbox
    agent_mailbox.close()


def _read_latest_ledger_record(ledger_path: Path) -> dict:
    rows = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert rows
    return rows[-1]


def test_worktree_audit_promote_and_teardown_roundtrip(git_repo: Path) -> None:
    sandbox = create_git_worktree_sandbox(owner_session_id="expert-1", repo_root=git_repo)
    worktree_root = Path(sandbox.worktree_root)

    tracked = worktree_root / "system" / "runtime.txt"
    tracked.write_text("UPDATED\n", encoding="utf-8")
    new_file = worktree_root / "agents" / "new_module.py"
    new_file.parent.mkdir(parents=True, exist_ok=True)
    new_file.write_text("print('embla')\n", encoding="utf-8")

    audit = audit_git_worktree_sandbox(
        owner_session_id="expert-1",
        worktree_root=worktree_root,
        repo_root=git_repo,
        base_sha=sandbox.head_sha,
        requested_by="core-1",
    )

    assert audit["status"] == "success"
    assert audit["promotion_ready"] is True
    assert sorted(audit["changed_files"]) == ["agents/new_module.py", "system/runtime.txt"]
    assert Path(audit["report_path"]).exists()
    assert Path(audit["audit_ledger_file"]).exists()
    assert _read_latest_ledger_record(Path(audit["audit_ledger_file"]))["record_type"] == "worktree_audit"

    promote = promote_git_worktree_sandbox(
        owner_session_id="expert-1",
        worktree_root=worktree_root,
        repo_root=git_repo,
        base_sha=sandbox.head_sha,
        change_id=str(audit["change_id"]),
        requested_by="core-1",
        approved_by="release-owner",
        approval_ticket="CAB-2026-2001",
        notes="self-maintenance approval",
    )

    assert promote["status"] == "success"
    assert (git_repo / "system" / "runtime.txt").read_text(encoding="utf-8") == "UPDATED\n"
    assert (git_repo / "agents" / "new_module.py").read_text(encoding="utf-8") == "print('embla')\n"
    assert _read_latest_ledger_record(Path(promote["audit_ledger_file"]))["record_type"] == "worktree_promoted"

    teardown = teardown_git_worktree_sandbox(
        owner_session_id="expert-1",
        worktree_root=worktree_root,
        repo_root=git_repo,
        change_id=str(audit["change_id"]),
        requested_by="core-1",
        reason="submission_closed",
    )

    assert teardown["status"] == "success"
    assert not worktree_root.exists()
    assert _read_latest_ledger_record(Path(teardown["audit_ledger_file"]))["record_type"] == "worktree_teardown"


def test_promote_blocks_when_repo_target_diverged_from_base(git_repo: Path) -> None:
    sandbox = create_git_worktree_sandbox(owner_session_id="expert-conflict", repo_root=git_repo)
    worktree_root = Path(sandbox.worktree_root)

    (worktree_root / "system" / "runtime.txt").write_text("FROM_WORKTREE\n", encoding="utf-8")
    (git_repo / "system" / "runtime.txt").write_text("FROM_MAIN_REPO\n", encoding="utf-8")

    result = promote_git_worktree_sandbox(
        owner_session_id="expert-conflict",
        worktree_root=worktree_root,
        repo_root=git_repo,
        base_sha=sandbox.head_sha,
        requested_by="core-1",
        approved_by="release-owner",
        approval_ticket="CAB-2026-2002",
    )

    assert result["status"] == "blocked"
    assert any(item["path"] == "system/runtime.txt" for item in result.get("conflicts", []))
    assert (git_repo / "system" / "runtime.txt").read_text(encoding="utf-8") == "FROM_MAIN_REPO\n"


def test_parent_tool_workspace_lifecycle_updates_owner_metadata(
    git_repo: Path,
    store: AgentSessionStore,
    mailbox: AgentMailbox,
) -> None:
    store.create(role="core", session_id="core-1")
    sandbox = create_git_worktree_sandbox(owner_session_id="expert-parent", repo_root=git_repo)
    owner_metadata = sandbox.to_metadata()
    owner_session = store.create(
        role="expert",
        session_id="expert-parent",
        parent_id="core-1",
        task_description="self-maintenance",
        metadata=owner_metadata,
    )
    store.update_status(owner_session.session_id, AgentStatus.WAITING)
    inherited_metadata = inherit_workspace_metadata(owner_metadata)
    child = store.create(
        role="dev",
        session_id="dev-parent",
        parent_id="expert-parent",
        task_description="modify runtime",
        metadata=inherited_metadata,
    )
    store.update_status(child.session_id, AgentStatus.WAITING)

    worktree_root = Path(sandbox.worktree_root)
    (worktree_root / "system" / "runtime.txt").write_text("OWNER_FLOW\n", encoding="utf-8")

    audit = handle_parent_tool_call(
        "audit_child_workspace",
        {"agent_id": "dev-parent"},
        parent_session_id="core-1",
        store=store,
        mailbox=mailbox,
    )
    owner_after_audit = store.get("expert-parent")
    assert audit["status"] == "success"
    assert audit["agent_id"] == "expert-parent"
    assert owner_after_audit is not None
    assert owner_after_audit.metadata["workspace_submission_state"] == "audited"
    assert owner_after_audit.metadata["workspace_change_id"] == audit["change_id"]

    promote = handle_parent_tool_call(
        "promote_child_workspace",
        {
            "agent_id": "dev-parent",
            "approval_ticket": "CAB-2026-2003",
            "approved_by": "release-owner",
        },
        parent_session_id="core-1",
        store=store,
        mailbox=mailbox,
    )
    owner_after_promote = store.get("expert-parent")
    assert promote["status"] == "success"
    assert owner_after_promote is not None
    assert owner_after_promote.metadata["workspace_submission_state"] == "promoted"
    assert owner_after_promote.metadata["workspace_promote_approval_ticket"] == "CAB-2026-2003"
    assert (git_repo / "system" / "runtime.txt").read_text(encoding="utf-8") == "OWNER_FLOW\n"

    teardown = handle_parent_tool_call(
        "teardown_child_workspace",
        {"agent_id": "expert-parent", "reason": "done"},
        parent_session_id="core-1",
        store=store,
        mailbox=mailbox,
    )
    owner_after_teardown = store.get("expert-parent")
    assert teardown["status"] == "success"
    assert owner_after_teardown is not None
    assert owner_after_teardown.metadata["workspace_submission_state"] == "teardown_complete"
    assert owner_after_teardown.metadata["workspace_root"] == ""
    assert owner_after_teardown.metadata["workspace_cleanup_on_destroy"] is False
    assert not worktree_root.exists()


def test_core_execution_receipt_includes_layered_scheduler_metrics() -> None:
    receipt = _build_core_execution_receipt(
        pipeline_id="pipe-scheduler-1",
        decomposition={"goal_id": "goal-scheduler-1", "original_goal": "refactor runtime"},
        expert_results=[{"agent_id": "expert-1"}],
        reports=[{"session_id": "expert-1", "status": "waiting", "reports": ["work complete"], "metadata": {}}],
        review_results=[],
        task_completed=True,
        stop_reason="submitted_completion",
        scheduler_metrics={
            "layer": "expert",
            "parallel_limit": 2,
            "peak_parallelism": 2,
            "layers": {
                "expert": {"layer": "expert", "parallel_limit": 2, "peak_parallelism": 2},
                "dev": {"layer": "dev", "parallel_limit": 4, "peak_parallelism": 3},
            },
        },
    )

    scheduler = receipt.get("agent_state", {}).get("scheduler", {})
    assert scheduler["layer"] == "expert"
    assert scheduler["parallel_limit"] == 2
    assert scheduler["peak_parallelism"] == 2
    assert scheduler["layers"]["expert"]["parallel_limit"] == 2
    assert scheduler["layers"]["dev"]["parallel_limit"] == 4
    assert scheduler["layers"]["dev"]["peak_parallelism"] == 3


def test_core_execution_receipt_marks_workspace_submission_pending() -> None:
    receipt = _build_core_execution_receipt(
        pipeline_id="pipe-self-1",
        decomposition={"goal_id": "goal-self-1", "original_goal": "refactor runtime"},
        expert_results=[{"agent_id": "expert-1"}],
        reports=[
            {
                "session_id": "expert-1",
                "status": "waiting",
                "reports": ["work complete"],
                "metadata": {
                    "workspace_mode": "worktree",
                    "workspace_sandbox_type": "git_worktree",
                    "workspace_root": "/repo/scratch/agent_worktrees/expert-1",
                    "workspace_origin_root": "/repo",
                    "workspace_submission_state": "audited",
                    "workspace_change_id": "wt_expert-1_123",
                    "workspace_submission_changed_files": ["system/runtime.txt"],
                    "workspace_audit_report_path": "/repo/scratch/runtime/worktree_submissions/expert-1/wt_expert-1_123/audit_report.json",
                },
            }
        ],
        review_results=[
            {
                "verdict": "approve",
                "expert_type": "backend",
                "summary": "review ok",
                "issues": [],
            }
        ],
        task_completed=True,
        stop_reason="awaiting_workspace_promotion",
    )

    agent_state = receipt.get("agent_state", {})
    assert receipt["stop_reason"] == "awaiting_workspace_promotion"
    assert agent_state["workspace_submission_required"] is True
    assert agent_state["workspace_submissions"][0]["promote_pending"] is True
    assert agent_state["workspace_submissions"][0]["change_id"] == "wt_expert-1_123"
    assert "awaiting workspace promotion approval" in str(agent_state.get("final_answer") or "").lower()


def test_core_execution_receipt_includes_execution_runtime_summary() -> None:
    receipt = _build_core_execution_receipt(
        pipeline_id="pipe-runtime-1",
        decomposition={"goal_id": "goal-runtime-1", "original_goal": "refactor runtime"},
        expert_results=[{"agent_id": "expert-1"}],
        reports=[
            {
                "session_id": "expert-1",
                "status": "waiting",
                "reports": ["work complete"],
                "metadata": {
                    "workspace_mode": "worktree",
                    "workspace_root": "/repo/scratch/agent_worktrees/expert-1",
                    "execution_backend": "os_sandbox",
                    "execution_backend_requested": "boxlite",
                    "execution_root": "/repo/scratch/agent_worktrees/expert-1",
                    "sandbox_policy": "default",
                    "network_policy": "disabled",
                    "resource_profile": "standard",
                },
            }
        ],
        review_results=[],
        task_completed=True,
        stop_reason="submitted_completion",
    )

    agent_state = receipt.get("agent_state", {})
    runtime = agent_state.get("execution_runtime", {})
    assert agent_state["execution_backend"] == "os_sandbox"
    assert agent_state["execution_backend_requested"] == "boxlite"
    assert agent_state["sandbox_policy"] == "default"
    assert agent_state["network_policy"] == "disabled"
    assert agent_state["resource_profile"] == "standard"
    assert runtime["backends"] == ["os_sandbox"]
    assert runtime["requested_backends"] == ["boxlite"]
    assert runtime["agents"][0]["workspace_mode"] == "worktree"


def test_fast_track_execution_receipt_includes_execution_runtime_summary() -> None:
    receipt = _build_fast_track_execution_receipt(
        pipeline_id="pipe-fast-runtime-1",
        goal="inspect runtime logs",
        reports=[
            {
                "session_id": "fast-track-dev-1",
                "status": "completed",
                "reports": ["read-only analysis complete"],
                "metadata": {
                    "workspace_mode": "worktree",
                    "workspace_root": "/repo/scratch/agent_worktrees/fast-track-dev-1",
                    "execution_backend": "os_sandbox",
                    "execution_backend_requested": "os_sandbox",
                    "execution_root": "/repo/scratch/agent_worktrees/fast-track-dev-1",
                    "sandbox_policy": "default",
                    "network_policy": "disabled",
                    "resource_profile": "standard",
                },
            }
        ],
        task_completed=True,
        stop_reason="completed",
        fast_track_agent_id="fast-track-dev-1",
        complexity_hint="simple",
        guard_blocked_count=0,
        touched_files=[],
    )

    agent_state = receipt.get("agent_state", {})
    runtime = agent_state.get("execution_runtime", {})
    assert agent_state["execution_backend"] == "os_sandbox"
    assert agent_state["sandbox_policy"] == "default"
    assert runtime["agents"][0]["execution_root"].endswith("fast-track-dev-1")


def test_fast_track_readonly_worktree_does_not_mark_workspace_submission_pending() -> None:
    receipt = _build_fast_track_execution_receipt(
        pipeline_id="pipe-fast-readonly-1",
        goal="inspect runtime logs",
        reports=[
            {
                "session_id": "fast-track-dev-1",
                "status": "completed",
                "reports": ["read-only analysis complete"],
                "metadata": {
                    "workspace_mode": "worktree",
                    "workspace_sandbox_type": "git_worktree",
                    "workspace_root": "/repo/scratch/agent_worktrees/fast-track-dev-1",
                    "workspace_origin_root": "/repo",
                    "workspace_submission_state": "sandboxed",
                    "workspace_change_id": "",
                    "workspace_submission_changed_files": [],
                    "workspace_audit_report_path": "",
                    "workspace_audit_diff_path": "",
                },
            }
        ],
        task_completed=True,
        stop_reason="completed",
        fast_track_agent_id="fast-track-dev-1",
        complexity_hint="simple",
        guard_blocked_count=0,
        touched_files=[],
    )

    agent_state = receipt.get("agent_state", {})
    assert agent_state["workspace_submission_required"] is False
    assert agent_state["workspace_submissions"][0]["state"] == "sandboxed"
    assert agent_state["workspace_submissions"][0]["promote_pending"] is False
    assert "awaiting workspace promotion approval" not in str(agent_state.get("final_answer") or "").lower()
