"""Native sub-agent execution bridge (no external CLI dependency)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Sequence

from autonomous.scaffold_engine import ScaffoldPatch
from autonomous.tools.subagent_runtime import RuntimeSubTaskResult, RuntimeSubTaskSpec
from autonomous.types import OptimizationTask


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class RoleExecutionPolicy:
    strict_role_paths: bool
    allowed_path_prefixes: List[str]
    policy_source: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strict_role_paths": bool(self.strict_role_paths),
            "allowed_path_prefixes": list(self.allowed_path_prefixes),
            "policy_source": str(self.policy_source),
        }


@dataclass(frozen=True)
class RoleExecutionDecision:
    success: bool
    reason: str
    patches: List[ScaffoldPatch]
    warnings: List[str]


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
    role_executor: str = "general"
    role_policy: Dict[str, Any] | None = None
    warnings: List[str] | None = None

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
            "role_executor": str(self.role_executor or "general"),
            "role_policy": dict(self.role_policy or {}),
            "warnings": list(self.warnings or []),
            "generated_at": self.generated_at,
        }


class RoleSpecializedExecutor:
    """Role-focused patch intent guard with optional strict path policy."""

    def __init__(
        self,
        *,
        name: str,
        aliases: Sequence[str],
        allowed_path_prefixes: Sequence[str],
    ) -> None:
        self.name = str(name).strip().lower() or "general"
        self.aliases = {self._normalize_role(value) for value in list(aliases)}
        self.allowed_path_prefixes = self._normalize_prefixes(list(allowed_path_prefixes))

    def supports(self, role: str) -> bool:
        normalized = self._normalize_role(role)
        return normalized == self.name or normalized in self.aliases

    def materialize(
        self,
        *,
        task: OptimizationTask,
        subtask: RuntimeSubTaskSpec,
        patches: List[ScaffoldPatch],
        policy: RoleExecutionPolicy,
    ) -> RoleExecutionDecision:
        violations = self._find_path_violations(
            patches=patches,
            allowed_path_prefixes=policy.allowed_path_prefixes,
        )
        warnings: List[str] = []
        if violations:
            if policy.strict_role_paths:
                return RoleExecutionDecision(
                    success=False,
                    reason=f"execution_bridge_role_path_violation:{self.name}",
                    patches=[],
                    warnings=[f"path_violations={len(violations)}"],
                )
            warnings.append(f"role_executor_path_violation:{self.name}:{len(violations)}")
            warnings.extend([f"path:{value}" for value in violations[:5]])

        extra_reason = self._validate_extra(task=task, subtask=subtask, policy=policy)
        if extra_reason:
            return RoleExecutionDecision(
                success=False,
                reason=extra_reason,
                patches=[],
                warnings=warnings,
            )

        return RoleExecutionDecision(
            success=True,
            reason=f"execution_bridge_role_executor_materialized:{self.name}",
            patches=list(patches),
            warnings=warnings,
        )

    def _validate_extra(
        self,
        *,
        task: OptimizationTask,
        subtask: RuntimeSubTaskSpec,
        policy: RoleExecutionPolicy,
    ) -> str | None:
        return None

    @staticmethod
    def _find_path_violations(
        *,
        patches: List[ScaffoldPatch],
        allowed_path_prefixes: List[str],
    ) -> List[str]:
        if not allowed_path_prefixes:
            return []
        violations: List[str] = []
        for patch in list(patches):
            path = RoleSpecializedExecutor._normalize_path(str(patch.path or ""))
            if not path:
                continue
            if not RoleSpecializedExecutor._is_path_allowed(path, allowed_path_prefixes):
                violations.append(path)
        return violations

    @staticmethod
    def _is_path_allowed(path: str, prefixes: List[str]) -> bool:
        candidate = RoleSpecializedExecutor._normalize_path(path)
        if not candidate:
            return True
        for raw_prefix in list(prefixes):
            prefix = RoleSpecializedExecutor._normalize_prefix(raw_prefix)
            if not prefix:
                return True
            if candidate == prefix:
                return True
            if candidate.startswith(prefix + "/"):
                return True
        return False

    @staticmethod
    def _normalize_role(value: str) -> str:
        return str(value or "").strip().lower().replace("-", "_")

    @staticmethod
    def _normalize_path(value: str) -> str:
        return str(value or "").replace("\\", "/").strip().lstrip("./")

    @staticmethod
    def _normalize_prefix(value: str) -> str:
        return RoleSpecializedExecutor._normalize_path(str(value or "")).rstrip("/")

    @classmethod
    def _normalize_prefixes(cls, values: List[str]) -> List[str]:
        normalized: List[str] = []
        seen: set[str] = set()
        for value in list(values):
            prefix = cls._normalize_prefix(value)
            if not prefix or prefix in seen:
                continue
            seen.add(prefix)
            normalized.append(prefix)
        return normalized


class FrontendRoleExecutor(RoleSpecializedExecutor):
    def __init__(self) -> None:
        super().__init__(
            name="frontend",
            aliases=("fe", "ui", "web", "client"),
            allowed_path_prefixes=(
                "Embla_core/",
                "frontend/",
                "web/",
                "ui/",
                "public/",
                "styles/",
                "assets/",
                "app/",
                "components/",
            ),
        )


class BackendRoleExecutor(RoleSpecializedExecutor):
    def __init__(self) -> None:
        super().__init__(
            name="backend",
            aliases=("be", "server", "api", "developer"),
            allowed_path_prefixes=(
                "apiserver/",
                "autonomous/",
                "system/",
                "mcpserver/",
                "scripts/",
                "tests/",
                "policy/",
                "config/",
                "doc/",
            ),
        )


class OpsRoleExecutor(RoleSpecializedExecutor):
    def __init__(self) -> None:
        super().__init__(
            name="ops",
            aliases=("devops", "sre", "infra", "release"),
            allowed_path_prefixes=(
                "scripts/",
                "doc/",
                "policy/",
                "autonomous/config/",
                "logs/",
                "scratch/reports/",
                "ops/",
                "infra/",
            ),
        )

    def _validate_extra(
        self,
        *,
        task: OptimizationTask,
        subtask: RuntimeSubTaskSpec,
        policy: RoleExecutionPolicy,
    ) -> str | None:
        if not policy.strict_role_paths:
            return None
        task_meta = task.metadata if isinstance(task.metadata, dict) else {}
        subtask_meta = subtask.metadata if isinstance(subtask.metadata, dict) else {}
        ticket = str(
            subtask_meta.get("ops_ticket")
            or subtask_meta.get("change_ticket")
            or task_meta.get("ops_ticket")
            or task_meta.get("change_ticket")
            or ""
        ).strip()
        if not ticket:
            return "execution_bridge_ops_ticket_required"
        return None


class NativeExecutionBridge:
    """Patch-intent execution bridge with deterministic audit receipts."""

    def __init__(self, *, project_root: str | Path, mode: str = "native_patch_intent_v1") -> None:
        self.project_root = Path(project_root).resolve()
        self.mode = str(mode or "native_patch_intent_v1").strip() or "native_patch_intent_v1"
        self.role_executors: List[RoleSpecializedExecutor] = [
            FrontendRoleExecutor(),
            BackendRoleExecutor(),
            OpsRoleExecutor(),
        ]
        self.general_executor = RoleSpecializedExecutor(
            name="general",
            aliases=("worker", "general", "misc"),
            allowed_path_prefixes=(),
        )

    def execute_subtask(self, *, task: OptimizationTask, subtask: RuntimeSubTaskSpec) -> RuntimeSubTaskResult:
        metadata = subtask.metadata if isinstance(subtask.metadata, dict) else {}
        executor = self._select_role_executor(subtask.role)
        role_policy = self._resolve_role_policy(task=task, subtask=subtask, executor=executor)
        if bool(metadata.get("force_error")):
            reason = str(metadata.get("error") or "forced_subtask_error")
            receipt = self._build_receipt(
                task=task,
                subtask=subtask,
                success=False,
                reason=reason,
                patches=[],
                role_executor=executor.name,
                role_policy=role_policy,
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
                role_executor=executor.name,
                role_policy=role_policy,
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

        role_decision = executor.materialize(
            task=task,
            subtask=subtask,
            patches=patches,
            policy=role_policy,
        )
        if not role_decision.success:
            receipt = self._build_receipt(
                task=task,
                subtask=subtask,
                success=False,
                reason=role_decision.reason,
                patches=[],
                role_executor=executor.name,
                role_policy=role_policy,
                warnings=role_decision.warnings,
            )
            return RuntimeSubTaskResult(
                subtask_id=subtask.subtask_id,
                role=subtask.role,
                success=False,
                error=role_decision.reason,
                metadata={
                    "task_id": task.task_id,
                    "source": "execution_bridge.role_guard",
                    "execution_bridge_mode": self.mode,
                    "execution_bridge_role_executor": executor.name,
                    "execution_bridge_role_policy": role_policy.to_dict(),
                    "execution_bridge_role_warnings": list(role_decision.warnings),
                    "execution_bridge_receipt": receipt.to_dict(),
                },
            )

        receipt = self._build_receipt(
            task=task,
            subtask=subtask,
            success=True,
            reason=role_decision.reason or "execution_bridge_patch_intent_materialized",
            patches=role_decision.patches,
            role_executor=executor.name,
            role_policy=role_policy,
            warnings=role_decision.warnings,
        )
        return RuntimeSubTaskResult(
            subtask_id=subtask.subtask_id,
            role=subtask.role,
            success=True,
            patches=role_decision.patches,
            summary=f"execution_bridge_patch_intents={len(role_decision.patches)}",
            metadata={
                "source": "execution_bridge.native",
                "execution_bridge_mode": self.mode,
                "execution_bridge_role_executor": executor.name,
                "execution_bridge_role_policy": role_policy.to_dict(),
                "execution_bridge_role_warnings": list(role_decision.warnings),
                "execution_bridge_receipt": receipt.to_dict(),
            },
        )

    def _select_role_executor(self, role: str) -> RoleSpecializedExecutor:
        normalized = RoleSpecializedExecutor._normalize_role(role)
        for executor in list(self.role_executors):
            if executor.supports(normalized):
                return executor
        return self.general_executor

    def _resolve_role_policy(
        self,
        *,
        task: OptimizationTask,
        subtask: RuntimeSubTaskSpec,
        executor: RoleSpecializedExecutor,
    ) -> RoleExecutionPolicy:
        task_meta = task.metadata if isinstance(task.metadata, dict) else {}
        subtask_meta = subtask.metadata if isinstance(subtask.metadata, dict) else {}
        task_contract_schema = task_meta.get("contract_schema") if isinstance(task_meta.get("contract_schema"), dict) else {}

        merged: Dict[str, Any] = {}
        source = "default"
        for candidate, label in (
            (task_meta.get("execution_bridge_policy"), "task.execution_bridge_policy"),
            (task_meta.get("role_executor_policy"), "task.role_executor_policy"),
            (
                self._extract_role_executor_policy_from_contract_schema(
                    task_contract_schema,
                    role=subtask.role,
                ),
                "task.contract_schema.role_executor_policy",
            ),
            (
                self._extract_role_executor_policy_from_contract_schema(
                    subtask.contract_schema if isinstance(subtask.contract_schema, dict) else {},
                    role=subtask.role,
                ),
                "subtask.contract_schema.role_executor_policy",
            ),
            (subtask.role_executor_policy, "subtask.role_executor_policy"),
            (subtask_meta.get("execution_bridge_policy"), "subtask.execution_bridge_policy"),
            (subtask_meta.get("role_executor_policy"), "subtask.role_executor_policy"),
        ):
            if not isinstance(candidate, dict) or not candidate:
                continue
            merged.update(candidate)
            source = label

        strict_role_paths = bool(merged.get("strict_role_paths", False))
        prefixes_raw = merged.get("allowed_path_prefixes")
        if isinstance(prefixes_raw, list):
            prefixes = RoleSpecializedExecutor._normalize_prefixes([str(item) for item in prefixes_raw])
        else:
            prefixes = list(executor.allowed_path_prefixes)

        return RoleExecutionPolicy(
            strict_role_paths=strict_role_paths,
            allowed_path_prefixes=prefixes,
            policy_source=source,
        )

    @staticmethod
    def _extract_role_executor_policy_from_contract_schema(
        contract_schema: Dict[str, Any],
        *,
        role: str,
    ) -> Dict[str, Any]:
        if not isinstance(contract_schema, dict):
            return {}
        merged: Dict[str, Any] = {}
        direct = contract_schema.get("role_executor_policy")
        if isinstance(direct, dict):
            merged.update(direct)
        execution_policy = contract_schema.get("execution_policy")
        if isinstance(execution_policy, dict):
            nested = execution_policy.get("role_executor_policy")
            if isinstance(nested, dict):
                merged.update(nested)
        role_map = contract_schema.get("role_executor_policy_by_role")
        if isinstance(role_map, dict):
            normalized_role = RoleSpecializedExecutor._normalize_role(role)
            for key, value in role_map.items():
                if not isinstance(value, dict):
                    continue
                if RoleSpecializedExecutor._normalize_role(str(key)) == normalized_role:
                    merged.update(value)
        return merged

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
        role_executor: str,
        role_policy: RoleExecutionPolicy,
        warnings: List[str] | None = None,
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
            role_executor=str(role_executor or "general"),
            role_policy=role_policy.to_dict(),
            warnings=list(warnings or []),
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
    "RoleExecutionPolicy",
    "RoleExecutionDecision",
    "RoleSpecializedExecutor",
    "FrontendRoleExecutor",
    "BackendRoleExecutor",
    "OpsRoleExecutor",
    "NativeExecutionBridge",
]
