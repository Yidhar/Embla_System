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
            ],
            "contract_schema": {
                "role_executor_policy": {"strict_role_paths": True, "allowed_path_prefixes": ["autonomous/"]},
            },
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
            metadata={
                "execution_bridge_governance": {
                    "status": "warning",
                    "severity": "warning",
                    "category": "semantic_toolchain",
                    "reason_code": "SEMANTIC_TOOLCHAIN_WARNING",
                    "reason": "semantic warning",
                    "executor": "backend",
                    "policy_source": "task.contract_schema.role_executor_policy",
                    "violation_count": 1,
                    "violations": ["a.txt::unknown"],
                },
                "execution_bridge_receipt": {
                    "bridge_id": "bridge_test",
                    "role": "backend",
                    "success": True,
                    "reason": "ok",
                    "governance": {
                        "status": "warning",
                        "severity": "warning",
                        "category": "semantic_toolchain",
                        "reason_code": "SEMANTIC_TOOLCHAIN_WARNING",
                    },
                },
            },
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

        dispatch_payloads = [payload for name, payload in events if name == "SubTaskDispatching"]
        assert len(dispatch_payloads) == 1
        dispatch_payload = dispatch_payloads[0]
        assert dispatch_payload["role_executor_policy"]["strict_role_paths"] is True
        assert dispatch_payload["role_executor_policy"]["allowed_path_prefixes"] == ["autonomous/"]
        assert dispatch_payload["role_executor_policy_source"] == "task.contract_schema.role_executor_policy"

        completed_payloads = [payload for name, payload in events if name == "SubTaskExecutionCompleted"]
        assert len(completed_payloads) == 1
        completed_payload = completed_payloads[0]
        assert completed_payload["role_executor_policy"]["strict_role_paths"] is True
        assert completed_payload["role_executor_policy_source"] == "task.contract_schema.role_executor_policy"
        assert completed_payload["execution_bridge_governance"]["reason_code"] == "SEMANTIC_TOOLCHAIN_WARNING"
        assert completed_payload["execution_bridge_governance_reason_code"] == "SEMANTIC_TOOLCHAIN_WARNING"
        assert completed_payload["execution_bridge_governance_severity"] == "warning"

        receipt_payloads = [payload for name, payload in events if name == "SubTaskExecutionBridgeReceipt"]
        assert len(receipt_payloads) == 1
        receipt_payload = receipt_payloads[0]
        assert receipt_payload["execution_bridge_governance"]["reason_code"] == "SEMANTIC_TOOLCHAIN_WARNING"
        assert receipt_payload["execution_bridge_governance_category"] == "semantic_toolchain"
    finally:
        _cleanup_case_root(case_root)


def test_subagent_runtime_rejected_event_includes_structured_governance_fields() -> None:
    case_root = _make_case_root("test_subagent_runtime_eventbus")
    repo = case_root / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "a.txt").write_text("A_BASE", encoding="utf-8")

    task = OptimizationTask(
        task_id="task-eventbus-rejected",
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
            success=False,
            error="execution_bridge_semantic_toolchain_violation:backend",
            metadata={
                "execution_bridge_governance": {
                    "status": "critical",
                    "severity": "critical",
                    "category": "semantic_toolchain",
                    "reason_code": "SEMANTIC_TOOLCHAIN_VIOLATION",
                    "reason": "semantic strict rejection",
                    "executor": "backend",
                    "policy_source": "task.contract_schema.role_executor_policy",
                    "violation_count": 1,
                    "violations": ["scripts/deploy.sh::ops"],
                }
            },
        )

    try:
        asyncio.run(
            runtime.run(
                task=task,
                workflow_id="wf-eventbus-rejected",
                trace_id="trace-eventbus-rejected",
                session_id="sess-eventbus-rejected",
                worker=_worker,
                emit_event=lambda event_type, payload: events.append((event_type, dict(payload))),
            )
        )
        rejected_payloads = [payload for name, payload in events if name == "SubTaskRejected"]
        assert len(rejected_payloads) == 1
        rejected = rejected_payloads[0]
        assert rejected["execution_bridge_governance_reason_code"] == "SEMANTIC_TOOLCHAIN_VIOLATION"
        assert rejected["execution_bridge_governance_category"] == "semantic_toolchain"
        assert rejected["execution_bridge_governance_severity"] == "critical"
        assert rejected["execution_bridge_governance"]["violation_count"] == 1
    finally:
        _cleanup_case_root(case_root)
