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


def test_subagent_runtime_contract_mismatch_blocks_parallel_execution() -> None:
    case_root = _make_case_root("test_subagent_runtime_ws21")
    repo = case_root / "repo"
    repo.mkdir(parents=True, exist_ok=True)

    task = OptimizationTask(
        task_id="task-ws21-contract-mismatch",
        instruction="sync frontend/backend contract",
        metadata={
            "subtasks": [
                {
                    "subtask_id": "fe",
                    "role": "frontend",
                    "instruction": "update frontend",
                    "contract_schema": {"request": {"id": "string"}},
                    "patches": [{"path": "frontend.txt", "content": "FE_NEW"}],
                },
                {
                    "subtask_id": "be",
                    "role": "backend",
                    "instruction": "update backend",
                    "contract_schema": {"request": {"id": "number"}},
                    "patches": [{"path": "backend.txt", "content": "BE_NEW"}],
                },
            ]
        },
    )

    runtime = SubAgentRuntime(
        project_root=repo,
        config=SubAgentRuntimeConfig(
            enabled=True,
            require_contract_negotiation=True,
        ),
    )

    called: list[str] = []

    async def _worker(subtask):
        called.append(subtask.subtask_id)
        return RuntimeSubTaskResult(
            subtask_id=subtask.subtask_id,
            role=subtask.role,
            success=True,
            patches=subtask.patches,
            summary="ok",
        )

    try:
        result = asyncio.run(
            runtime.run(
                task=task,
                workflow_id="wf-contract-mismatch",
                trace_id="trace-contract-mismatch",
                session_id="sess-contract-mismatch",
                worker=_worker,
            )
        )
        assert result.success is False
        assert result.gate_failure == "contract"
        assert called == []
    finally:
        _cleanup_case_root(case_root)


def test_subagent_runtime_respects_dependencies_and_commits_scaffold() -> None:
    case_root = _make_case_root("test_subagent_runtime_ws21")
    repo = case_root / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "frontend.txt").write_text("FE_BASE", encoding="utf-8")
    (repo / "backend.txt").write_text("BE_BASE", encoding="utf-8")

    task = OptimizationTask(
        task_id="task-ws21-deps",
        instruction="apply frontend/backend patch",
        metadata={
            "subtasks": [
                {
                    "subtask_id": "be",
                    "role": "backend",
                    "instruction": "patch backend",
                    "dependencies": [],
                    "contract_schema": {"request": {"id": "string"}},
                    "patches": [{"path": "backend.txt", "content": "BE_NEW"}],
                },
                {
                    "subtask_id": "fe",
                    "role": "frontend",
                    "instruction": "patch frontend",
                    "dependencies": ["be"],
                    "contract_schema": {"request": {"id": "string"}},
                    "patches": [{"path": "frontend.txt", "content": "FE_NEW"}],
                },
            ]
        },
    )

    runtime = SubAgentRuntime(
        project_root=repo,
        config=SubAgentRuntimeConfig(
            enabled=True,
            require_contract_negotiation=True,
        ),
    )

    order: list[str] = []

    async def _worker(subtask):
        order.append(subtask.subtask_id)
        return RuntimeSubTaskResult(
            subtask_id=subtask.subtask_id,
            role=subtask.role,
            success=True,
            patches=subtask.patches,
            summary="ok",
        )

    try:
        result = asyncio.run(
            runtime.run(
                task=task,
                workflow_id="wf-deps",
                trace_id="trace-deps",
                session_id="sess-deps",
                worker=_worker,
            )
        )
        assert result.success is True
        assert result.approved is True
        assert order == ["be", "fe"]
        assert (repo / "frontend.txt").read_text(encoding="utf-8") == "FE_NEW"
        assert (repo / "backend.txt").read_text(encoding="utf-8") == "BE_NEW"
    finally:
        _cleanup_case_root(case_root)


def test_subagent_runtime_build_subtasks_propagates_role_policy_from_contract_schema() -> None:
    case_root = _make_case_root("test_subagent_runtime_ws21")
    try:
        repo = case_root / "repo"
        repo.mkdir(parents=True, exist_ok=True)

        task = OptimizationTask(
            task_id="task-ws21-role-policy",
            instruction="propagate role executor policy",
            metadata={
                "contract_schema": {
                    "role_executor_policy": {"strict_role_paths": True},
                    "role_executor_policy_by_role": {
                        "ops": {"strict_role_paths": True, "allowed_path_prefixes": ["scripts/", "doc/"]},
                    },
                },
                "subtasks": [
                    {
                        "subtask_id": "be",
                        "role": "backend",
                        "instruction": "backend patch",
                        "contract_schema": {"request": {"id": "string"}},
                        "patches": [{"path": "autonomous/backend.txt", "content": "BE_NEW"}],
                    },
                    {
                        "subtask_id": "ops",
                        "role": "ops",
                        "instruction": "ops patch",
                        "contract_schema": {"request": {"id": "string"}},
                        "patches": [{"path": "scripts/ops.sh", "content": "echo ok"}],
                    },
                ],
            },
        )

        runtime = SubAgentRuntime(project_root=repo, config=SubAgentRuntimeConfig(enabled=True))
        subtasks = runtime._build_subtasks(task)  # noqa: SLF001

        backend = next(item for item in subtasks if item.subtask_id == "be")
        ops = next(item for item in subtasks if item.subtask_id == "ops")
        assert backend.role_executor_policy["strict_role_paths"] is True
        assert backend.role_executor_policy_source == "task.contract_schema.role_executor_policy"
        assert ops.role_executor_policy["strict_role_paths"] is True
        assert ops.role_executor_policy["allowed_path_prefixes"] == ["scripts/", "doc/"]
        assert ops.role_executor_policy_source == "task.contract_schema.role_executor_policy"
    finally:
        _cleanup_case_root(case_root)
