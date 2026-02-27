from __future__ import annotations

import json

from autonomous.scaffold_engine import ScaffoldPatch
from autonomous.tools.execution_bridge import NativeExecutionBridge
from autonomous.tools.subagent_runtime import RuntimeSubTaskSpec
from autonomous.types import OptimizationTask


def _task(task_id: str) -> OptimizationTask:
    return OptimizationTask(task_id=task_id, instruction="role executor test")


def test_frontend_role_executor_strict_from_task_contract_policy() -> None:
    bridge = NativeExecutionBridge(project_root=".")
    task = OptimizationTask(
        task_id="task-role-fe-contract-policy",
        instruction="enforce strict role paths from task contract",
        metadata={
            "contract_schema": {
                "role_executor_policy": {"strict_role_paths": True},
            }
        },
    )
    subtask = RuntimeSubTaskSpec(
        subtask_id="fe-contract-1",
        role="frontend",
        instruction="must stay in frontend boundary",
        patches=[ScaffoldPatch(path="autonomous/system_agent.py", content="# forbidden for frontend strict")],
    )

    result = bridge.execute_subtask(task=task, subtask=subtask)

    assert result.success is False
    assert result.error == "execution_bridge_role_path_violation:frontend"
    governance = result.metadata.get("execution_bridge_governance")
    assert isinstance(governance, dict)
    assert governance.get("reason_code") == "ROLE_PATH_VIOLATION"
    assert governance.get("category") == "path_policy"
    assert governance.get("severity") == "critical"
    receipt = result.metadata.get("execution_bridge_receipt")
    assert isinstance(receipt, dict)
    assert isinstance(receipt.get("governance"), dict)
    assert receipt["governance"]["reason_code"] == "ROLE_PATH_VIOLATION"
    policy = receipt.get("role_policy")
    assert isinstance(policy, dict)
    assert policy.get("strict_role_paths") is True
    assert policy.get("policy_source") == "task.contract_schema.role_executor_policy"


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
    governance = result.metadata.get("execution_bridge_governance")
    assert isinstance(governance, dict)
    assert governance.get("reason_code") == "OPS_CHANGE_TICKET_REQUIRED"
    assert governance.get("category") == "change_control"
    assert governance.get("severity") == "critical"


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


def test_backend_role_executor_default_semantic_guard_blocks_cross_domain_patch() -> None:
    bridge = NativeExecutionBridge(project_root=".")
    subtask = RuntimeSubTaskSpec(
        subtask_id="be-1",
        role="backend",
        instruction="touch frontend from backend in non-strict mode",
        patches=[ScaffoldPatch(path="Embla_core/app/layout.tsx", content="layout patch")],
    )

    result = bridge.execute_subtask(task=_task("task-role-be-warning"), subtask=subtask)

    assert result.success is False
    assert result.error == "execution_bridge_semantic_toolchain_violation:backend"
    governance = result.metadata.get("execution_bridge_governance")
    assert isinstance(governance, dict)
    assert governance.get("severity") == "critical"
    assert governance.get("reason_code") == "SEMANTIC_TOOLCHAIN_VIOLATION"


def test_backend_role_executor_strict_semantic_toolchain_blocks_ops_patch() -> None:
    bridge = NativeExecutionBridge(project_root=".")
    subtask = RuntimeSubTaskSpec(
        subtask_id="be-2",
        role="backend",
        instruction="backend task should not emit frontend test payload in strict semantic mode",
        patches=[ScaffoldPatch(path="tests/frontend/widget.test.tsx", content="export const x = 1;")],
        metadata={"role_executor_policy": {"strict_role_paths": True, "strict_semantic_guard": True}},
    )

    result = bridge.execute_subtask(task=_task("task-role-be-semantic"), subtask=subtask)

    assert result.success is False
    assert result.error == "execution_bridge_semantic_toolchain_violation:backend"
    governance = result.metadata.get("execution_bridge_governance")
    assert isinstance(governance, dict)
    assert governance.get("reason_code") == "SEMANTIC_TOOLCHAIN_VIOLATION"
    assert governance.get("category") == "semantic_toolchain"
    violations = governance.get("violations")
    assert isinstance(violations, list)
    assert any(str(item).endswith("::test_frontend") for item in violations)


def test_execution_bridge_uses_semantic_guard_spec_as_default_policy_source(tmp_path) -> None:
    spec_path = tmp_path / "policy" / "role_executor_semantic_guard.spec"
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(
        json.dumps(
            {
                "schema_version": "ws28-role-executor-semantic-guard-v1",
                "roles": {
                    "backend": {
                        "strict_semantic_guard": True,
                        "allowed_semantic_toolchains": ["backend"],
                    }
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    bridge = NativeExecutionBridge(project_root=tmp_path)
    subtask = RuntimeSubTaskSpec(
        subtask_id="be-spec-1",
        role="backend",
        instruction="backend role with spec-driven semantic guard",
        patches=[ScaffoldPatch(path="doc/task/readme.md", content="# touched by backend")],
    )

    result = bridge.execute_subtask(task=_task("task-role-be-spec"), subtask=subtask)

    assert result.success is False
    assert result.error == "execution_bridge_semantic_toolchain_violation:backend"
    receipt = result.metadata.get("execution_bridge_receipt")
    assert isinstance(receipt, dict)
    role_policy = receipt.get("role_policy")
    assert isinstance(role_policy, dict)
    assert role_policy.get("strict_semantic_guard") is True
    assert role_policy.get("policy_source") == "policy.role_executor_semantic_guard.spec:role_executor_semantic_guard.spec"


def test_execution_bridge_invalid_semantic_guard_spec_falls_back_to_default_policy(tmp_path) -> None:
    spec_path = tmp_path / "policy" / "role_executor_semantic_guard.spec"
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    spec_path.write_text("{not-json}", encoding="utf-8")

    bridge = NativeExecutionBridge(project_root=tmp_path)
    subtask = RuntimeSubTaskSpec(
        subtask_id="be-spec-2",
        role="backend",
        instruction="backend role fallback on invalid spec",
        patches=[ScaffoldPatch(path="autonomous/system_agent.py", content="# backend update")],
    )

    result = bridge.execute_subtask(task=_task("task-role-be-spec-invalid"), subtask=subtask)

    assert result.success is True
    receipt = result.metadata.get("execution_bridge_receipt")
    assert isinstance(receipt, dict)
    role_policy = receipt.get("role_policy")
    assert isinstance(role_policy, dict)
    assert role_policy.get("policy_source") == "default"
