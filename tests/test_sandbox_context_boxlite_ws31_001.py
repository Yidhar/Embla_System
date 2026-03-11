from __future__ import annotations

from system.sandbox_context import SandboxContext, normalize_execution_backend


def test_sandbox_context_defaults_to_project_root_native() -> None:
    context = SandboxContext.default(session_id="agent-1")
    assert context.execution_backend == "native"
    assert context.execution_root == context.project_root


def test_sandbox_context_reads_execution_metadata() -> None:
    context = SandboxContext.from_metadata(
        {
            "workspace_mode": "worktree",
            "workspace_origin_root": "/repo",
            "workspace_root": "/repo/scratch/agent_worktrees/agent-1",
            "execution_backend": "boxlite",
            "execution_root": "/workspace",
            "box_name": "embla-agent-box-123",
            "box_profile": "default",
        },
        session_id="agent-1",
    )
    assert context.workspace_host_root == "/repo/scratch/agent_worktrees/agent-1"
    assert context.execution_backend == "boxlite"
    assert context.box_name == "embla-agent-box-123"
    assert context.execution_root == "/workspace"


def test_normalize_execution_backend_aliases() -> None:
    assert normalize_execution_backend("") == "native"
    assert normalize_execution_backend("local") == "native"
    assert normalize_execution_backend("box") == "boxlite"
