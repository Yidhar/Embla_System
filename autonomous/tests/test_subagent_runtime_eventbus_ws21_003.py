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


def test_subagent_runtime_emits_traceable_lifecycle_events() -> None:
    case_root = _make_case_root("test_subagent_runtime_eventbus")
    repo = case_root / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "a.txt").write_text("A_BASE", encoding="utf-8")

    task = OptimizationTask(
        task_id="task-eventbus",
        instruction="patch a",
        metadata={
            "subtasks": [
                {
                    "subtask_id": "worker-1",
                    "role": "backend",
                    "instruction": "patch a",
                    "contract_schema": {"request": {"id": "string"}},
                    "patches": [{"path": "a.txt", "content": "A_NEW"}],
                }
            ]
        },
    )

    runtime = SubAgentRuntime(
        project_root=repo,
        config=SubAgentRuntimeConfig(enabled=True),
    )

    events: list[tuple[str, dict]] = []

    async def _worker(subtask):
        return RuntimeSubTaskResult(
            subtask_id=subtask.subtask_id,
            role=subtask.role,
            success=True,
            patches=subtask.patches,
            summary="ok",
        )

    try:
        asyncio.run(
            runtime.run(
                task=task,
                workflow_id="wf-eventbus",
                trace_id="trace-eventbus",
                session_id="sess-eventbus",
                worker=_worker,
                emit_event=lambda event_type, payload: events.append((event_type, dict(payload))),
            )
        )
        event_types = [name for name, _ in events]
        assert "SubAgentRuntimeStarted" in event_types
        assert "SubTaskDispatching" in event_types
        assert "SubTaskExecutionCompleted" in event_types
        assert "SubTaskApproved" in event_types
        assert "SubAgentRuntimeCompleted" in event_types

        for _, payload in events:
            assert payload.get("workflow_id") == "wf-eventbus"
            assert payload.get("trace_id") == "trace-eventbus"
            assert payload.get("session_id") == "sess-eventbus"
    finally:
        _cleanup_case_root(case_root)
