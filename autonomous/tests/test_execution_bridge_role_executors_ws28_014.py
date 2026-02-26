from __future__ import annotations

from autonomous.scaffold_engine import ScaffoldPatch
from autonomous.tools.execution_bridge import NativeExecutionBridge
from autonomous.tools.subagent_runtime import RuntimeSubTaskSpec
from autonomous.types import OptimizationTask


def _task(task_id: str) -> OptimizationTask:
    return OptimizationTask(task_id=task_id, instruction="role executor test")


def test_frontend_role_executor_strict_allows_frontend_paths() -> None:
    bridge = NativeExecutionBridge(project_root=".")
    subtask = RuntimeSubTaskSpec(
        subtask_id="fe-1",
        role="frontend",
        instruction="update frontend page",
        patches=[ScaffoldPatch(path="Embla_core/app/page.tsx", content="export default function Page() {}")],
        metadata={"role_executor_policy": {"strict_role_paths": True}},
    )

    result = bridge.execute_subtask(task=_task("task-role-fe-ok"), subtask=subtask)

    assert result.success is True
    assert result.metadata.get("execution_bridge_role_executor") == "frontend"
    receipt = result.metadata.get("execution_bridge_receipt")
    assert isinstance(receipt, dict)
    assert receipt.get("role_executor") == "frontend"
    policy = receipt.get("role_policy")
    assert isinstance(policy, dict)
    assert policy.get("strict_role_paths") is True
    assert receipt.get("warnings") == []


def test_frontend_role_executor_strict_blocks_backend_path() -> None:
    bridge = NativeExecutionBridge(project_root=".")
    subtask = RuntimeSubTaskSpec(
        subtask_id="fe-2",
        role="frontend",
        instruction="must stay in frontend boundary",
        patches=[ScaffoldPatch(path="autonomous/system_agent.py", content="# forbidden for frontend strict")],
        metadata={"role_executor_policy": {"strict_role_paths": True}},
    )

    result = bridge.execute_subtask(task=_task("task-role-fe-block"), subtask=subtask)

    assert result.success is False
    assert result.error == "execution_bridge_role_path_violation:frontend"
    receipt = result.metadata.get("execution_bridge_receipt")
    assert isinstance(receipt, dict)
    assert receipt.get("success") is False
    assert receipt.get("role_executor") == "frontend"


def test_ops_role_executor_strict_requires_change_ticket() -> None:
    bridge = NativeExecutionBridge(project_root=".")
    subtask = RuntimeSubTaskSpec(
        subtask_id="ops-1",
        role="ops",
        instruction="update ops script",
        patches=[ScaffoldPatch(path="scripts/release_check.sh", content="echo check")],
        metadata={"role_executor_policy": {"strict_role_paths": True}},
    )

    result = bridge.execute_subtask(task=_task("task-role-ops-ticket"), subtask=subtask)

    assert result.success is False
    assert result.error == "execution_bridge_ops_ticket_required"


def test_ops_role_alias_devops_routes_to_ops_executor() -> None:
    bridge = NativeExecutionBridge(project_root=".")
    subtask = RuntimeSubTaskSpec(
        subtask_id="ops-2",
        role="devops",
        instruction="update runbook",
        patches=[ScaffoldPatch(path="doc/task/runbooks/release_m0_m5_closure_onepager.md", content="updated")],
        metadata={
            "role_executor_policy": {"strict_role_paths": True},
            "change_ticket": "OPS-1234",
        },
    )

    result = bridge.execute_subtask(task=_task("task-role-ops-alias"), subtask=subtask)

    assert result.success is True
    assert result.metadata.get("execution_bridge_role_executor") == "ops"


def test_backend_role_executor_non_strict_records_cross_domain_warning() -> None:
    bridge = NativeExecutionBridge(project_root=".")
    subtask = RuntimeSubTaskSpec(
        subtask_id="be-1",
        role="backend",
        instruction="touch frontend from backend in non-strict mode",
        patches=[ScaffoldPatch(path="Embla_core/app/layout.tsx", content="layout patch")],
    )

    result = bridge.execute_subtask(task=_task("task-role-be-warning"), subtask=subtask)

    assert result.success is True
    warnings = result.metadata.get("execution_bridge_role_warnings")
    assert isinstance(warnings, list)
    assert any(str(item).startswith("role_executor_path_violation:backend:") for item in warnings)
