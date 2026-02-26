"""Native sub-agent execution bridge (no external CLI dependency)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from autonomous.scaffold_engine import ScaffoldPatch
from autonomous.tools.subagent_runtime import RuntimeSubTaskResult, RuntimeSubTaskSpec
from autonomous.types import OptimizationTask


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ExecutionBridgeReceipt:
    bridge_id: str
    bridge_mode: str
    task_id: str
    subtask_id: str
    role: str
    success: bool
    reason: str
    patch_count: int
    changed_paths: List[str]
    generated_at: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bridge_id": self.bridge_id,
            "bridge_mode": self.bridge_mode,
            "task_id": self.task_id,
            "subtask_id": self.subtask_id,
            "role": self.role,
            "success": bool(self.success),
            "reason": self.reason,
            "patch_count": int(self.patch_count),
            "changed_paths": list(self.changed_paths),
            "generated_at": self.generated_at,
        }


class NativeExecutionBridge:
    """Patch-intent execution bridge with deterministic audit receipts."""

    def __init__(self, *, project_root: str | Path, mode: str = "native_patch_intent_v1") -> None:
        self.project_root = Path(project_root).resolve()
        self.mode = str(mode or "native_patch_intent_v1").strip() or "native_patch_intent_v1"

    def execute_subtask(self, *, task: OptimizationTask, subtask: RuntimeSubTaskSpec) -> RuntimeSubTaskResult:
        metadata = subtask.metadata if isinstance(subtask.metadata, dict) else {}
        if bool(metadata.get("force_error")):
            reason = str(metadata.get("error") or "forced_subtask_error")
            receipt = self._build_receipt(
                task=task,
                subtask=subtask,
                success=False,
                reason=reason,
                patches=[],
            )
            return RuntimeSubTaskResult(
                subtask_id=subtask.subtask_id,
                role=subtask.role,
                success=False,
                error=reason,
                metadata={
                    "execution_bridge_mode": self.mode,
                    "execution_bridge_receipt": receipt.to_dict(),
                    "source": "execution_bridge.force_error",
                },
            )

        patches = self._collect_patch_intents(subtask)
        if not patches:
            reason = "execution_bridge_missing_patch_intent"
            receipt = self._build_receipt(
                task=task,
                subtask=subtask,
                success=False,
                reason=reason,
                patches=[],
            )
            return RuntimeSubTaskResult(
                subtask_id=subtask.subtask_id,
                role=subtask.role,
                success=False,
                error=reason,
                metadata={
                    "task_id": task.task_id,
                    "execution_bridge_mode": self.mode,
                    "execution_bridge_receipt": receipt.to_dict(),
                },
            )

        receipt = self._build_receipt(
            task=task,
            subtask=subtask,
            success=True,
            reason="execution_bridge_patch_intent_materialized",
            patches=patches,
        )
        return RuntimeSubTaskResult(
            subtask_id=subtask.subtask_id,
            role=subtask.role,
            success=True,
            patches=patches,
            summary=f"execution_bridge_patch_intents={len(patches)}",
            metadata={
                "source": "execution_bridge.native",
                "execution_bridge_mode": self.mode,
                "execution_bridge_receipt": receipt.to_dict(),
            },
        )

    def _collect_patch_intents(self, subtask: RuntimeSubTaskSpec) -> List[ScaffoldPatch]:
        normalized: List[ScaffoldPatch] = []
        seen: set[str] = set()

        def _append_patch(patch: ScaffoldPatch) -> None:
            key = f"{patch.path}|{patch.mode}|{patch.content}"
            if key in seen:
                return
            seen.add(key)
            normalized.append(patch)

        for patch in list(subtask.patches):
            if isinstance(patch, ScaffoldPatch):
                _append_patch(self._normalize_patch(patch))

        metadata = subtask.metadata if isinstance(subtask.metadata, dict) else {}
        for source_key in ("patch_intents", "generated_patches", "patches"):
            source_items = metadata.get(source_key)
            if not isinstance(source_items, list):
                continue
            for raw in source_items:
                patch = self._to_patch(raw)
                if patch is None:
                    continue
                _append_patch(self._normalize_patch(patch))
        return normalized

    def _build_receipt(
        self,
        *,
        task: OptimizationTask,
        subtask: RuntimeSubTaskSpec,
        success: bool,
        reason: str,
        patches: List[ScaffoldPatch],
    ) -> ExecutionBridgeReceipt:
        changed_paths = [str(item.path).replace("\\", "/").strip() for item in patches if str(item.path).strip()]
        return ExecutionBridgeReceipt(
            bridge_id=f"bridge_{uuid.uuid4().hex[:12]}",
            bridge_mode=self.mode,
            task_id=str(task.task_id),
            subtask_id=str(subtask.subtask_id),
            role=str(subtask.role),
            success=bool(success),
            reason=str(reason or ""),
            patch_count=len(patches),
            changed_paths=changed_paths,
            generated_at=_utc_now_iso(),
        )

    def _normalize_patch(self, patch: ScaffoldPatch) -> ScaffoldPatch:
        path = str(patch.path or "").replace("\\", "/").strip()
        if path and not Path(path).is_absolute():
            path = str(Path(path)).replace("\\", "/")
        return ScaffoldPatch(
            path=path,
            content=str(patch.content or ""),
            mode=str(patch.mode or "overwrite").strip().lower(),
            encoding=str(patch.encoding or "utf-8").strip(),
            expected_file_hash=str(patch.expected_file_hash or "").strip(),
            original_content=patch.original_content if patch.original_content is not None else None,
            semantic_rebase=bool(patch.semantic_rebase),
        )

    @staticmethod
    def _to_patch(raw: Any) -> ScaffoldPatch | None:
        if isinstance(raw, ScaffoldPatch):
            return raw
        if not isinstance(raw, dict):
            return None
        path = str(raw.get("path") or raw.get("file_path") or "").strip()
        if not path:
            return None
        return ScaffoldPatch(
            path=path,
            content=str(raw.get("content") or ""),
            mode=str(raw.get("mode") or "overwrite").strip().lower(),
            encoding=str(raw.get("encoding") or "utf-8").strip(),
            expected_file_hash=str(
                raw.get("expected_file_hash") or raw.get("expected_hash") or raw.get("original_file_hash") or ""
            ).strip(),
            original_content=(str(raw.get("original_content")) if raw.get("original_content") is not None else None),
            semantic_rebase=bool(raw.get("semantic_rebase", True)),
        )


__all__ = [
    "ExecutionBridgeReceipt",
    "NativeExecutionBridge",
]

