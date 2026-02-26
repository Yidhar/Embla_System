"""Native sub-agent execution bridge (no external CLI dependency)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
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
    strict_semantic_guard: bool
    allowed_semantic_toolchains: List[str]
    policy_source: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strict_role_paths": bool(self.strict_role_paths),
            "allowed_path_prefixes": list(self.allowed_path_prefixes),
            "strict_semantic_guard": bool(self.strict_semantic_guard),
            "allowed_semantic_toolchains": list(self.allowed_semantic_toolchains),
            "policy_source": str(self.policy_source),
        }


@dataclass(frozen=True)
class RoleExecutionDecision:
    success: bool
    reason: str
    patches: List[ScaffoldPatch]
    warnings: List[str]
    governance: Dict[str, Any] = field(default_factory=dict)


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
    governance: Dict[str, Any] | None = None

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
            "governance": dict(self.governance or {}),
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
        default_semantic_toolchains: Sequence[str],
    ) -> None:
        self.name = str(name).strip().lower() or "general"
        self.aliases = {self._normalize_role(value) for value in list(aliases)}
        self.allowed_path_prefixes = self._normalize_prefixes(list(allowed_path_prefixes))
        self.default_semantic_toolchains = self._normalize_semantic_toolchains(list(default_semantic_toolchains))

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
                    governance=self._build_governance(
                        status="critical",
                        category="path_policy",
                        reason_code="ROLE_PATH_VIOLATION",
                        reason=f"execution_bridge_role_path_violation:{self.name}",
                        policy=policy,
                        violations=violations,
                    ),
                )
            warnings.append(f"role_executor_path_violation:{self.name}:{len(violations)}")
            warnings.extend([f"path:{value}" for value in violations[:5]])

        semantic_violations = self._find_semantic_toolchain_violations(
            patches=patches,
            allowed_semantic_toolchains=policy.allowed_semantic_toolchains,
        )
        if semantic_violations:
            if policy.strict_semantic_guard:
                return RoleExecutionDecision(
                    success=False,
                    reason=f"execution_bridge_semantic_toolchain_violation:{self.name}",
                    patches=[],
                    warnings=warnings,
                    governance=self._build_governance(
                        status="critical",
                        category="semantic_toolchain",
                        reason_code="SEMANTIC_TOOLCHAIN_VIOLATION",
                        reason=f"execution_bridge_semantic_toolchain_violation:{self.name}",
                        policy=policy,
                        violations=semantic_violations,
                    ),
                )
            warnings.append(f"semantic_toolchain_violation:{self.name}:{len(semantic_violations)}")
            warnings.extend([f"toolchain:{value}" for value in semantic_violations[:5]])

        extra_reason = self._validate_extra(task=task, subtask=subtask, policy=policy)
        if extra_reason:
            reason_code, category = self._map_extra_reason(extra_reason)
            return RoleExecutionDecision(
                success=False,
                reason=extra_reason,
                patches=[],
                warnings=warnings,
                governance=self._build_governance(
                    status="critical",
                    category=category,
                    reason_code=reason_code,
                    reason=extra_reason,
                    policy=policy,
                    violations=[],
                ),
            )

        governance_status = "warning" if warnings else "ok"
        governance_reason_code = "ROLE_EXECUTOR_GUARD_WARNING" if warnings else "ROLE_EXECUTOR_GUARD_OK"
        governance_reason = (
            f"execution_bridge_role_executor_guard_warning:{self.name}"
            if warnings
            else f"execution_bridge_role_executor_guard_ok:{self.name}"
        )
        return RoleExecutionDecision(
            success=True,
            reason=f"execution_bridge_role_executor_materialized:{self.name}",
            patches=list(patches),
            warnings=warnings,
            governance=self._build_governance(
                status=governance_status,
                category="role_executor_guard",
                reason_code=governance_reason_code,
                reason=governance_reason,
                policy=policy,
                violations=[],
            ),
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
    def _find_semantic_toolchain_violations(
        *,
        patches: List[ScaffoldPatch],
        allowed_semantic_toolchains: List[str],
    ) -> List[str]:
        if not allowed_semantic_toolchains:
            return []
        allowed = {
            RoleSpecializedExecutor._normalize_semantic_toolchain(value)
            for value in list(allowed_semantic_toolchains)
            if RoleSpecializedExecutor._normalize_semantic_toolchain(value)
        }
        if not allowed:
            return []

        violations: List[str] = []
        for patch in list(patches):
            path = RoleSpecializedExecutor._normalize_path(str(patch.path or ""))
            if not path:
                continue
            semantic_toolchain = RoleSpecializedExecutor._classify_semantic_toolchain(path)
            if semantic_toolchain in allowed:
                continue
            violations.append(f"{path}::{semantic_toolchain}")
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

    @staticmethod
    def _normalize_semantic_toolchain(value: str) -> str:
        return str(value or "").strip().lower().replace("-", "_")

    @classmethod
    def _normalize_semantic_toolchains(cls, values: List[str]) -> List[str]:
        normalized: List[str] = []
        seen: set[str] = set()
        for value in list(values):
            semantic_toolchain = cls._normalize_semantic_toolchain(value)
            if not semantic_toolchain or semantic_toolchain in seen:
                continue
            seen.add(semantic_toolchain)
            normalized.append(semantic_toolchain)
        return normalized

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

    @staticmethod
    def _classify_semantic_toolchain(path: str) -> str:
        normalized = RoleSpecializedExecutor._normalize_path(path)
        lower = normalized.lower()
        suffix = Path(lower).suffix

        frontend_prefixes = (
            "embla_core/",
            "frontend/",
            "web/",
            "ui/",
            "public/",
            "styles/",
            "assets/",
            "app/",
            "components/",
        )
        backend_prefixes = ("apiserver/", "autonomous/", "system/", "mcpserver/")
        ops_prefixes = ("scripts/", "ops/", "infra/", "policy/")
        docs_prefixes = ("doc/",)
        config_prefixes = ("autonomous/config/", "config/")

        frontend_suffixes = {".ts", ".tsx", ".js", ".jsx", ".css", ".scss", ".less", ".sass", ".html", ".svg"}
        backend_suffixes = {".py", ".sql"}
        ops_suffixes = {".sh", ".service", ".timer", ".conf", ".ini"}
        docs_suffixes = {".md", ".rst", ".txt"}
        config_suffixes = {".yaml", ".yml", ".json", ".toml", ".ini"}

        if lower.startswith(docs_prefixes) or suffix in docs_suffixes:
            return "docs"
        if lower.startswith(config_prefixes):
            return "config"
        if lower.startswith(frontend_prefixes):
            return "frontend"
        if lower.startswith(backend_prefixes):
            return "backend"
        if lower.startswith(ops_prefixes):
            return "ops"
        if lower.startswith("tests/"):
            if "/frontend" in lower or "/ui" in lower or "/web" in lower or "/embla_core" in lower:
                return "test_frontend"
            if "/ops" in lower or "/infra" in lower or "/release" in lower:
                return "test_ops"
            return "test_backend"
        if suffix in frontend_suffixes:
            return "frontend"
        if suffix in backend_suffixes:
            return "backend"
        if suffix in ops_suffixes:
            return "ops"
        if suffix in config_suffixes:
            return "config"
        return "unknown"

    def _build_governance(
        self,
        *,
        status: str,
        category: str,
        reason_code: str,
        reason: str,
        policy: RoleExecutionPolicy,
        violations: List[str],
    ) -> Dict[str, Any]:
        return {
            "status": str(status or "unknown"),
            "severity": str(status or "unknown"),
            "category": str(category or ""),
            "reason_code": str(reason_code or ""),
            "reason": str(reason or ""),
            "executor": self.name,
            "strict_role_paths": bool(policy.strict_role_paths),
            "strict_semantic_guard": bool(policy.strict_semantic_guard),
            "policy_source": str(policy.policy_source or ""),
            "allowed_path_prefixes": list(policy.allowed_path_prefixes),
            "allowed_semantic_toolchains": list(policy.allowed_semantic_toolchains),
            "violation_count": len(list(violations)),
            "violations": list(violations),
        }

    @staticmethod
    def _map_extra_reason(reason: str) -> tuple[str, str]:
        normalized = str(reason or "").strip().lower()
        if normalized == "execution_bridge_ops_ticket_required":
            return "OPS_CHANGE_TICKET_REQUIRED", "change_control"
        if normalized.startswith("execution_bridge_"):
            return "ROLE_SPECIFIC_GUARD_REJECTED", "role_specific_guard"
        return "ROLE_SPECIFIC_GUARD_REJECTED", "role_specific_guard"


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
            default_semantic_toolchains=("frontend", "docs", "config", "test_frontend"),
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
            default_semantic_toolchains=("backend", "docs", "config", "test_backend", "ops"),
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
            default_semantic_toolchains=("ops", "docs", "config", "test_ops"),
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
            default_semantic_toolchains=(),
        )

    def execute_subtask(self, *, task: OptimizationTask, subtask: RuntimeSubTaskSpec) -> RuntimeSubTaskResult:
        metadata = subtask.metadata if isinstance(subtask.metadata, dict) else {}
        executor = self._select_role_executor(subtask.role)
        role_policy = self._resolve_role_policy(task=task, subtask=subtask, executor=executor)
        if bool(metadata.get("force_error")):
            reason = str(metadata.get("error") or "forced_subtask_error")
            governance = {
                "status": "critical",
                "severity": "critical",
                "category": "forced_error",
                "reason_code": "FORCED_SUBTASK_ERROR",
                "reason": reason,
                "executor": executor.name,
                "policy_source": role_policy.policy_source,
                "violation_count": 0,
                "violations": [],
            }
            receipt = self._build_receipt(
                task=task,
                subtask=subtask,
                success=False,
                reason=reason,
                patches=[],
                role_executor=executor.name,
                role_policy=role_policy,
                governance=governance,
            )
            return RuntimeSubTaskResult(
                subtask_id=subtask.subtask_id,
                role=subtask.role,
                success=False,
                error=reason,
                metadata={
                    "execution_bridge_mode": self.mode,
                    "execution_bridge_governance": governance,
                    "execution_bridge_receipt": receipt.to_dict(),
                    "source": "execution_bridge.force_error",
                },
            )

        patches = self._collect_patch_intents(subtask)
        if not patches:
            reason = "execution_bridge_missing_patch_intent"
            governance = {
                "status": "critical",
                "severity": "critical",
                "category": "patch_intent",
                "reason_code": "MISSING_PATCH_INTENT",
                "reason": reason,
                "executor": executor.name,
                "policy_source": role_policy.policy_source,
                "violation_count": 0,
                "violations": [],
            }
            receipt = self._build_receipt(
                task=task,
                subtask=subtask,
                success=False,
                reason=reason,
                patches=[],
                role_executor=executor.name,
                role_policy=role_policy,
                governance=governance,
            )
            return RuntimeSubTaskResult(
                subtask_id=subtask.subtask_id,
                role=subtask.role,
                success=False,
                error=reason,
                metadata={
                    "task_id": task.task_id,
                    "execution_bridge_mode": self.mode,
                    "execution_bridge_governance": governance,
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
                governance=role_decision.governance,
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
                    "execution_bridge_governance": dict(role_decision.governance),
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
            governance=role_decision.governance,
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
                "execution_bridge_governance": dict(role_decision.governance),
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
        strict_semantic_guard = bool(merged.get("strict_semantic_guard", strict_role_paths))
        prefixes_raw = merged.get("allowed_path_prefixes")
        if isinstance(prefixes_raw, list):
            prefixes = RoleSpecializedExecutor._normalize_prefixes([str(item) for item in prefixes_raw])
        else:
            prefixes = list(executor.allowed_path_prefixes)
        semantic_toolchains_raw = merged.get("allowed_semantic_toolchains")
        if isinstance(semantic_toolchains_raw, list):
            semantic_toolchains = RoleSpecializedExecutor._normalize_semantic_toolchains(
                [str(item) for item in semantic_toolchains_raw]
            )
        else:
            semantic_toolchains = list(executor.default_semantic_toolchains)

        return RoleExecutionPolicy(
            strict_role_paths=strict_role_paths,
            allowed_path_prefixes=prefixes,
            strict_semantic_guard=strict_semantic_guard,
            allowed_semantic_toolchains=semantic_toolchains,
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
        governance: Dict[str, Any] | None = None,
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
            governance=dict(governance or {}),
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
