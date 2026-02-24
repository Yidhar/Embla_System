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


def test_subagent_runtime_rejects_when_subtask_count_exceeds_guardrail() -> None:
    case_root = _make_case_root("test_subagent_runtime_chaos")
    repo = case_root / "repo"
    repo.mkdir(parents=True, exist_ok=True)

    subtasks = []
    for idx in range(40):
        subtasks.append(
            {
                "subtask_id": f"st-{idx}",
                "role": "worker",
                "instruction": f"task {idx}",
                "contract_schema": {"req": {"id": "string"}},
                "patches": [{"path": f"f{idx}.txt", "content": f"v{idx}"}],
            }
        )

    task = OptimizationTask(
        task_id="task-chaos-max-subtasks",
        instruction="stress runtime subtask cap",
        metadata={"subtasks": subtasks},
    )

    runtime = SubAgentRuntime(
        project_root=repo,
        config=SubAgentRuntimeConfig(enabled=True, max_subtasks=16),
    )

    async def _worker(_subtask):
        return RuntimeSubTaskResult(subtask_id="x", role="worker", success=True)

    try:
        result = asyncio.run(
            runtime.run(
                task=task,
                workflow_id="wf-chaos-max",
                trace_id="trace-chaos-max",
                session_id="sess-chaos-max",
                worker=_worker,
            )
        )
        assert result.success is False
        assert result.gate_failure == "runtime"
        assert any("max_subtasks" in reason for reason in result.reasons)
    finally:
        _cleanup_case_root(case_root)


def test_subagent_runtime_fail_fast_stops_on_first_subtask_error() -> None:
    case_root = _make_case_root("test_subagent_runtime_chaos")
    repo = case_root / "repo"
    repo.mkdir(parents=True, exist_ok=True)

    task = OptimizationTask(
        task_id="task-chaos-fail-fast",
        instruction="fail fast",
        metadata={
            "subtasks": [
                {
                    "subtask_id": "st-1",
                    "role": "backend",
                    "instruction": "fail here",
                    "contract_schema": {"req": {"id": "string"}},
                    "patches": [{"path": "a.txt", "content": "A_NEW"}],
                },
                {
                    "subtask_id": "st-2",
                    "role": "frontend",
                    "instruction": "should not run",
                    "contract_schema": {"req": {"id": "string"}},
                    "patches": [{"path": "b.txt", "content": "B_NEW"}],
                },
            ]
        },
    )

    runtime = SubAgentRuntime(
        project_root=repo,
        config=SubAgentRuntimeConfig(enabled=True, fail_fast_on_subtask_error=True),
    )

    called: list[str] = []

    async def _worker(subtask):
        called.append(subtask.subtask_id)
        if subtask.subtask_id == "st-1":
            return RuntimeSubTaskResult(
                subtask_id=subtask.subtask_id,
                role=subtask.role,
                success=False,
                error="boom",
            )
        return RuntimeSubTaskResult(
            subtask_id=subtask.subtask_id,
            role=subtask.role,
            success=True,
            patches=subtask.patches,
        )

    try:
        result = asyncio.run(
            runtime.run(
                task=task,
                workflow_id="wf-chaos-fail-fast",
                trace_id="trace-chaos-fail-fast",
                session_id="sess-chaos-fail-fast",
                worker=_worker,
            )
        )
        assert result.success is False
        assert result.failed_subtasks == ["st-1"]
        assert called == ["st-1"]
    finally:
        _cleanup_case_root(case_root)
