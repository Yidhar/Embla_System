import asyncio
import shutil
import uuid
from pathlib import Path

from autonomous.tools.subagent_runtime import RuntimeSubTaskResult, SubAgentRuntime, SubAgentRuntimeConfig
from autonomous.types import OptimizationTask


def _make_case_root(prefix: str) -> Path:
    root = Path("scratch") / prefix / uuid.uuid4().hex[:12]
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_case_root(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


def test_subagent_runtime_rejects_duplicate_subtask_ids_before_worker_runs() -> None:
    case_root = _make_case_root("test_subagent_runtime_spec_validation")
    repo = case_root / "repo"
    repo.mkdir(parents=True, exist_ok=True)

    task = OptimizationTask(
        task_id="task-spec-duplicate-id",
        instruction="validate subtask spec",
        metadata={
            "subtasks": [
                {
                    "subtask_id": "dup",
                    "role": "backend",
                    "instruction": "patch backend",
                    "contract_schema": {"request": {"id": "string"}},
                    "patches": [{"path": "backend.txt", "content": "BE_NEW"}],
                },
                {
                    "subtask_id": "dup",
                    "role": "frontend",
                    "instruction": "patch frontend",
                    "contract_schema": {"request": {"id": "string"}},
                    "patches": [{"path": "frontend.txt", "content": "FE_NEW"}],
                },
            ]
        },
    )

    runtime = SubAgentRuntime(project_root=repo, config=SubAgentRuntimeConfig(enabled=True))
    called: list[str] = []

    async def _worker(subtask):
        called.append(subtask.subtask_id)
        return RuntimeSubTaskResult(subtask_id=subtask.subtask_id, role=subtask.role, success=True, patches=subtask.patches)

    try:
        result = asyncio.run(
            runtime.run(
                task=task,
                workflow_id="wf-spec-duplicate-id",
                trace_id="trace-spec-duplicate-id",
                session_id="sess-spec-duplicate-id",
                worker=_worker,
            )
        )
        assert result.success is False
        assert result.gate_failure == "runtime"
        assert any(str(item).startswith("duplicate_subtask_id:") for item in result.reasons)
        assert called == []
    finally:
        _cleanup_case_root(case_root)


def test_subagent_runtime_rejects_invalid_dependencies_before_worker_runs() -> None:
    case_root = _make_case_root("test_subagent_runtime_spec_validation")
    repo = case_root / "repo"
    repo.mkdir(parents=True, exist_ok=True)

    task = OptimizationTask(
        task_id="task-spec-invalid-deps",
        instruction="validate dependency graph",
        metadata={
            "subtasks": [
                {
                    "subtask_id": "be",
                    "role": "backend",
                    "instruction": "patch backend",
                    "dependencies": ["missing-node"],
                    "contract_schema": {"request": {"id": "string"}},
                    "patches": [{"path": "backend.txt", "content": "BE_NEW"}],
                },
                {
                    "subtask_id": "fe",
                    "role": "frontend",
                    "instruction": "patch frontend",
                    "dependencies": ["fe"],
                    "contract_schema": {"request": {"id": "string"}},
                    "patches": [{"path": "frontend.txt", "content": "FE_NEW"}],
                },
            ]
        },
    )

    runtime = SubAgentRuntime(project_root=repo, config=SubAgentRuntimeConfig(enabled=True))
    called: list[str] = []

    async def _worker(subtask):
        called.append(subtask.subtask_id)
        return RuntimeSubTaskResult(subtask_id=subtask.subtask_id, role=subtask.role, success=True, patches=subtask.patches)

    try:
        result = asyncio.run(
            runtime.run(
                task=task,
                workflow_id="wf-spec-invalid-deps",
                trace_id="trace-spec-invalid-deps",
                session_id="sess-spec-invalid-deps",
                worker=_worker,
            )
        )
        assert result.success is False
        assert result.gate_failure == "runtime"
        assert "missing_dependency:be->missing-node" in result.reasons
        assert "self_dependency:fe" in result.reasons
        assert called == []
    finally:
        _cleanup_case_root(case_root)
