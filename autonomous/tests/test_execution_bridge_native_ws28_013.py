from __future__ import annotations

from autonomous.scaffold_engine import ScaffoldPatch
from autonomous.tools.execution_bridge import NativeExecutionBridge
from autonomous.tools.subagent_runtime import RuntimeSubTaskSpec
from autonomous.types import OptimizationTask


def test_native_execution_bridge_materializes_subtask_patches() -> None:
    bridge = NativeExecutionBridge(project_root=".")
    task = OptimizationTask(task_id="task-bridge-1", instruction="patch file")
    subtask = RuntimeSubTaskSpec(
        subtask_id="backend-1",
        role="backend",
        instruction="apply patch",
        patches=[ScaffoldPatch(path="service.txt", content="PATCHED")],
    )

    result = bridge.execute_subtask(task=task, subtask=subtask)

    assert result.success is True
    assert len(result.patches) == 1
    assert result.summary == "execution_bridge_patch_intents=1"
    receipt = result.metadata.get("execution_bridge_receipt")
    assert isinstance(receipt, dict)
    assert receipt["success"] is True
    assert receipt["patch_count"] == 1
    assert receipt["task_id"] == "task-bridge-1"


def test_native_execution_bridge_uses_metadata_patch_intents_when_subtask_patch_list_empty() -> None:
    bridge = NativeExecutionBridge(project_root=".")
    task = OptimizationTask(task_id="task-bridge-2", instruction="patch file")
    subtask = RuntimeSubTaskSpec(
        subtask_id="backend-2",
        role="backend",
        instruction="apply patch",
        patches=[],
        metadata={
            "patch_intents": [
                {
                    "path": "api/server.txt",
                    "content": "NEW_CONTENT",
                    "mode": "overwrite",
                }
            ]
        },
    )

    result = bridge.execute_subtask(task=task, subtask=subtask)

    assert result.success is True
    assert len(result.patches) == 1
    assert result.patches[0].path == "api/server.txt"


def test_native_execution_bridge_rejects_missing_patch_intents() -> None:
    bridge = NativeExecutionBridge(project_root=".")
    task = OptimizationTask(task_id="task-bridge-3", instruction="patch file")
    subtask = RuntimeSubTaskSpec(
        subtask_id="backend-3",
        role="backend",
        instruction="apply patch",
        patches=[],
        metadata={},
    )

    result = bridge.execute_subtask(task=task, subtask=subtask)

    assert result.success is False
    assert result.error == "execution_bridge_missing_patch_intent"
    receipt = result.metadata.get("execution_bridge_receipt")
    assert isinstance(receipt, dict)
    assert receipt["success"] is False
    assert receipt["reason"] == "execution_bridge_missing_patch_intent"
