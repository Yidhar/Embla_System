"""WS21-002 sub-agent runtime with contract gate and scaffold commit."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Iterable, List

from autonomous.contract_negotiation import ContractProposal, ContractNegotiationResult, negotiate_contract
from autonomous.scaffold_engine import ScaffoldApplyResult, ScaffoldEngine, ScaffoldPatch
from autonomous.types import OptimizationTask
from system.subagent_contract import build_contract_checksum


@dataclass
class SubAgentRuntimeConfig:
    enabled: bool = False
    max_subtasks: int = 16
    rollout_percent: int = 100
    fail_open: bool = True
    fail_open_budget_ratio: float = 0.15
    enforce_scaffold_txn_for_write: bool = True
    allow_legacy_fail_open_for_write: bool = False
    disable_legacy_cli_fallback: bool = False
    require_contract_negotiation: bool = True
    require_scaffold_patch: bool = True
    fail_fast_on_subtask_error: bool = True


@dataclass(frozen=True)
class RuntimeSubTaskSpec:
    subtask_id: str
    role: str
    instruction: str
    dependencies: List[str] = field(default_factory=list)
    contract_schema: Dict[str, Any] = field(default_factory=dict)
    role_executor_policy: Dict[str, Any] = field(default_factory=dict)
    patches: List[ScaffoldPatch] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RuntimeSubTaskResult:
    subtask_id: str
    role: str
    success: bool
    summary: str = ""
    error: str = ""
    duration_seconds: float = 0.0
    patches: List[ScaffoldPatch] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SubAgentRuntimeResult:
    runtime_id: str
    workflow_id: str
    task_id: str
    trace_id: str
    session_id: str
    success: bool
    approved: bool
    gate_failure: str = ""
    reasons: List[str] = field(default_factory=list)
    failed_subtasks: List[str] = field(default_factory=list)
    subtask_results: List[RuntimeSubTaskResult] = field(default_factory=list)
    negotiation_result: ContractNegotiationResult | None = None
    scaffold_result: ScaffoldApplyResult | None = None
    fail_open_recommended: bool = False


RuntimeWorker = Callable[[RuntimeSubTaskSpec], Awaitable[RuntimeSubTaskResult] | RuntimeSubTaskResult]
RuntimeEventEmitter = Callable[[str, Dict[str, Any]], None]
RuntimeLeaseGuard = Callable[[], None]


class SubAgentRuntime:
    """Dependency-aware runtime that enforces contract + scaffold transaction."""

    def __init__(
        self,
        *,
        project_root: str | Path,
        config: SubAgentRuntimeConfig | None = None,
        scaffold_engine: ScaffoldEngine | None = None,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.config = config or SubAgentRuntimeConfig()
        self.scaffold_engine = scaffold_engine or ScaffoldEngine(project_root=self.project_root)

    async def run(
        self,
        *,
        task: OptimizationTask,
        workflow_id: str,
        trace_id: str,
        session_id: str,
        worker: RuntimeWorker,
        emit_event: RuntimeEventEmitter | None = None,
        lease_guard: RuntimeLeaseGuard | None = None,
    ) -> SubAgentRuntimeResult:
        runtime_id = f"sar_{uuid.uuid4().hex[:16]}"
        subtasks = self._build_subtasks(task)
        if len(subtasks) > self.config.max_subtasks:
            reason = f"subtask_count_exceeds_max_subtasks:{len(subtasks)}>{self.config.max_subtasks}"
            self._emit(
                emit_event,
                "SubAgentRuntimeRejected",
                runtime_id=runtime_id,
                workflow_id=workflow_id,
                task_id=task.task_id,
                trace_id=trace_id,
                session_id=session_id,
                reason=reason,
            )
            return SubAgentRuntimeResult(
                runtime_id=runtime_id,
                workflow_id=workflow_id,
                task_id=task.task_id,
                trace_id=trace_id,
                session_id=session_id,
                success=False,
                approved=False,
                gate_failure="runtime",
                reasons=[reason],
                fail_open_recommended=True,
            )

        spec_errors = self._validate_subtask_specs(subtasks)
        if spec_errors:
            self._emit(
                emit_event,
                "SubAgentRuntimeRejected",
                runtime_id=runtime_id,
                workflow_id=workflow_id,
                task_id=task.task_id,
                trace_id=trace_id,
                session_id=session_id,
                reason="invalid_subtask_spec",
                errors=list(spec_errors),
            )
            return SubAgentRuntimeResult(
                runtime_id=runtime_id,
                workflow_id=workflow_id,
                task_id=task.task_id,
                trace_id=trace_id,
                session_id=session_id,
                success=False,
                approved=False,
                gate_failure="runtime",
                reasons=list(spec_errors),
                fail_open_recommended=True,
            )

        self._emit(
            emit_event,
            "SubAgentRuntimeStarted",
            runtime_id=runtime_id,
            workflow_id=workflow_id,
            task_id=task.task_id,
            trace_id=trace_id,
            session_id=session_id,
            subtask_count=len(subtasks),
        )

        negotiation = self._negotiate_contract(task, subtasks)
        if self.config.require_contract_negotiation and not negotiation.agreed:
            reason = negotiation.reason or "contract_mismatch"
            self._emit(
                emit_event,
                "SubAgentContractGateFailed",
                runtime_id=runtime_id,
                workflow_id=workflow_id,
                task_id=task.task_id,
                trace_id=trace_id,
                session_id=session_id,
                reason=reason,
                mismatch_roles=list(negotiation.mismatch_roles),
            )
            self._emit(
                emit_event,
                "SubAgentRuntimeCompleted",
                runtime_id=runtime_id,
                workflow_id=workflow_id,
                task_id=task.task_id,
                trace_id=trace_id,
                session_id=session_id,
                success=False,
                gate_failure="contract",
            )
            return SubAgentRuntimeResult(
                runtime_id=runtime_id,
                workflow_id=workflow_id,
                task_id=task.task_id,
                trace_id=trace_id,
                session_id=session_id,
                success=False,
                approved=False,
                gate_failure="contract",
                reasons=[reason],
                negotiation_result=negotiation,
                fail_open_recommended=True,
            )

        pending = {item.subtask_id: item for item in subtasks}
        completed: set[str] = set()
        subtask_results: List[RuntimeSubTaskResult] = []
        all_patches: List[ScaffoldPatch] = []

        while pending:
            ready = [item for item in pending.values() if all(dep in completed for dep in item.dependencies)]
            if not ready:
                reason = "dependency_deadlock_detected"
                self._emit(
                    emit_event,
                    "SubAgentRuntimeCompleted",
                    runtime_id=runtime_id,
                    workflow_id=workflow_id,
                    task_id=task.task_id,
                    trace_id=trace_id,
                    session_id=session_id,
                    success=False,
                    gate_failure="runtime",
                    reason=reason,
                )
                return SubAgentRuntimeResult(
                    runtime_id=runtime_id,
                    workflow_id=workflow_id,
                    task_id=task.task_id,
                    trace_id=trace_id,
                    session_id=session_id,
                    success=False,
                    approved=False,
                    gate_failure="runtime",
                    reasons=[reason],
                    failed_subtasks=sorted(pending.keys()),
                    subtask_results=subtask_results,
                    negotiation_result=negotiation,
                    fail_open_recommended=True,
                )

            for subtask in ready:
                if lease_guard is not None:
                    lease_guard()

                self._emit(
                    emit_event,
                    "SubTaskDispatching",
                    runtime_id=runtime_id,
                    workflow_id=workflow_id,
                    task_id=task.task_id,
                    trace_id=trace_id,
                    session_id=session_id,
                    subtask_id=subtask.subtask_id,
                    role=subtask.role,
                    dependencies=list(subtask.dependencies),
                )

                started = time.monotonic()
                result = await self._await_worker(worker, subtask)
                duration = time.monotonic() - started
                result.duration_seconds = max(result.duration_seconds, duration)
                result.subtask_id = subtask.subtask_id
                result.role = subtask.role

                bridge_receipt = (
                    result.metadata.get("execution_bridge_receipt")
                    if isinstance(result.metadata, dict)
                    else None
                )
                if isinstance(bridge_receipt, dict):
                    self._emit(
                        emit_event,
                        "SubTaskExecutionBridgeReceipt",
                        runtime_id=runtime_id,
                        workflow_id=workflow_id,
                        task_id=task.task_id,
                        trace_id=trace_id,
                        session_id=session_id,
                        subtask_id=subtask.subtask_id,
                        role=subtask.role,
                        bridge_receipt=dict(bridge_receipt),
                    )

                subtask_results.append(result)
                completion_payload = dict(
                    runtime_id=runtime_id,
                    workflow_id=workflow_id,
                    task_id=task.task_id,
                    trace_id=trace_id,
                    session_id=session_id,
                    subtask_id=subtask.subtask_id,
                    role=subtask.role,
                    success=result.success,
                    duration_seconds=round(result.duration_seconds, 4),
                    patch_count=len(result.patches),
                )
                self._emit(
                    emit_event,
                    "SubTaskExecutionCompleted",
                    **completion_payload,
                )

                if result.success:
                    completed.add(subtask.subtask_id)
                    all_patches.extend(result.patches)
                    self._emit(
                        emit_event,
                        "SubTaskApproved",
                        runtime_id=runtime_id,
                        workflow_id=workflow_id,
                        task_id=task.task_id,
                        trace_id=trace_id,
                        session_id=session_id,
                        subtask_id=subtask.subtask_id,
                        role=subtask.role,
                        summary=result.summary,
                    )
                else:
                    self._emit(
                        emit_event,
                        "SubTaskRejected",
                        runtime_id=runtime_id,
                        workflow_id=workflow_id,
                        task_id=task.task_id,
                        trace_id=trace_id,
                        session_id=session_id,
                        subtask_id=subtask.subtask_id,
                        role=subtask.role,
                        error=result.error or result.summary or "subtask_failed",
                    )
                    if self.config.fail_fast_on_subtask_error:
                        reason = result.error or result.summary or "subtask_failed"
                        self._emit(
                            emit_event,
                            "SubAgentRuntimeCompleted",
                            runtime_id=runtime_id,
                            workflow_id=workflow_id,
                            task_id=task.task_id,
                            trace_id=trace_id,
                            session_id=session_id,
                            success=False,
                            gate_failure="runtime",
                            reason=reason,
                        )
                        return SubAgentRuntimeResult(
                            runtime_id=runtime_id,
                            workflow_id=workflow_id,
                            task_id=task.task_id,
                            trace_id=trace_id,
                            session_id=session_id,
                            success=False,
                            approved=False,
                            gate_failure="runtime",
                            reasons=[reason],
                            failed_subtasks=[subtask.subtask_id],
                            subtask_results=subtask_results,
                            negotiation_result=negotiation,
                            fail_open_recommended=True,
                        )

                pending.pop(subtask.subtask_id, None)

        if self.config.require_scaffold_patch and not all_patches:
            reason = "missing_scaffold_patch_intents"
            self._emit(
                emit_event,
                "SubAgentScaffoldGateFailed",
                runtime_id=runtime_id,
                workflow_id=workflow_id,
                task_id=task.task_id,
                trace_id=trace_id,
                session_id=session_id,
                reason=reason,
            )
            self._emit(
                emit_event,
                "SubAgentRuntimeCompleted",
                runtime_id=runtime_id,
                workflow_id=workflow_id,
                task_id=task.task_id,
                trace_id=trace_id,
                session_id=session_id,
                success=False,
                gate_failure="scaffold",
                reason=reason,
            )
            return SubAgentRuntimeResult(
                runtime_id=runtime_id,
                workflow_id=workflow_id,
                task_id=task.task_id,
                trace_id=trace_id,
                session_id=session_id,
                success=False,
                approved=False,
                gate_failure="scaffold",
                reasons=[reason],
                subtask_results=subtask_results,
                negotiation_result=negotiation,
                fail_open_recommended=True,
            )

        if lease_guard is not None:
            lease_guard()

        contract_id_for_scaffold = negotiation.contract_id if negotiation else ""
        contract_checksum_for_scaffold = negotiation.contract_checksum if negotiation else ""
        if contract_id_for_scaffold:
            changed_paths = sorted({str(item.path).replace("\\", "/").strip() for item in all_patches if str(item.path).strip()})
            contract_checksum_for_scaffold = build_contract_checksum(
                contract_id_for_scaffold,
                schema={"paths": changed_paths},
            )

        scaffold_result = self.scaffold_engine.apply(
            patches=all_patches,
            contract_id=contract_id_for_scaffold,
            contract_checksum=contract_checksum_for_scaffold,
            trace_id=trace_id,
            verify_context={
                "workflow_id": workflow_id,
                "task_id": task.task_id,
                "runtime_id": runtime_id,
            },
        )
        if not scaffold_result.committed:
            self._emit(
                emit_event,
                "SubAgentScaffoldGateFailed",
                runtime_id=runtime_id,
                workflow_id=workflow_id,
                task_id=task.task_id,
                trace_id=trace_id,
                session_id=session_id,
                reason=scaffold_result.error or "scaffold_apply_failed",
                clean_state=scaffold_result.clean_state,
                recovery_ticket=scaffold_result.recovery_ticket,
                conflict_ticket=scaffold_result.conflict_ticket,
            )
            self._emit(
                emit_event,
                "SubAgentRuntimeCompleted",
                runtime_id=runtime_id,
                workflow_id=workflow_id,
                task_id=task.task_id,
                trace_id=trace_id,
                session_id=session_id,
                success=False,
                gate_failure="scaffold",
            )
            return SubAgentRuntimeResult(
                runtime_id=runtime_id,
                workflow_id=workflow_id,
                task_id=task.task_id,
                trace_id=trace_id,
                session_id=session_id,
                success=False,
                approved=False,
                gate_failure="scaffold",
                reasons=[scaffold_result.error or "scaffold_apply_failed"],
                subtask_results=subtask_results,
                negotiation_result=negotiation,
                scaffold_result=scaffold_result,
                fail_open_recommended=True,
            )

        self._emit(
            emit_event,
            "SubAgentRuntimeCompleted",
            runtime_id=runtime_id,
            workflow_id=workflow_id,
            task_id=task.task_id,
            trace_id=trace_id,
            session_id=session_id,
            success=True,
            gate_failure="",
            scaffold_fingerprint=scaffold_result.scaffold_fingerprint,
        )
        return SubAgentRuntimeResult(
            runtime_id=runtime_id,
            workflow_id=workflow_id,
            task_id=task.task_id,
            trace_id=trace_id,
            session_id=session_id,
            success=True,
            approved=True,
            reasons=[],
            subtask_results=subtask_results,
            negotiation_result=negotiation,
            scaffold_result=scaffold_result,
            fail_open_recommended=False,
        )

    def _build_subtasks(self, task: OptimizationTask) -> List[RuntimeSubTaskSpec]:
        metadata = task.metadata if isinstance(task.metadata, dict) else {}
        raw_subtasks = metadata.get("subtasks") if isinstance(metadata.get("subtasks"), list) else []
        task_contract_schema = metadata.get("contract_schema") if isinstance(metadata.get("contract_schema"), dict) else {}
        task_metadata_role_policy = metadata.get("role_executor_policy") if isinstance(metadata.get("role_executor_policy"), dict) else {}
        if not raw_subtasks:
            raw_subtasks = [
                {
                    "subtask_id": f"{task.task_id}-worker-1",
                    "role": str(metadata.get("default_role") or "worker"),
                    "instruction": task.instruction,
                    "dependencies": [],
                    "patches": metadata.get("patches", []),
                    "contract_schema": metadata.get("contract_schema", {}),
                    "metadata": metadata,
                }
            ]

        subtasks: List[RuntimeSubTaskSpec] = []
        for idx, raw in enumerate(raw_subtasks, start=1):
            if not isinstance(raw, dict):
                continue
            subtask_id = str(raw.get("subtask_id") or f"{task.task_id}-worker-{idx}").strip()
            role = str(raw.get("role") or "worker").strip()
            instruction = str(raw.get("instruction") or task.instruction).strip()
            dependencies = [str(item).strip() for item in list(raw.get("dependencies") or []) if str(item).strip()]
            patch_payloads = raw.get("patches") if isinstance(raw.get("patches"), list) else []
            patches = [self._to_patch(item) for item in patch_payloads if isinstance(item, dict)]
            contract_schema = raw.get("contract_schema") if isinstance(raw.get("contract_schema"), dict) else {}
            role_executor_policy = self._merge_policy_dicts(
                task_metadata_role_policy,
                self._extract_role_executor_policy_from_contract_schema(task_contract_schema, role=role),
                self._extract_role_executor_policy_from_contract_schema(contract_schema, role=role),
                raw.get("role_executor_policy") if isinstance(raw.get("role_executor_policy"), dict) else {},
            )
            subtask_metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
            subtasks.append(
                RuntimeSubTaskSpec(
                    subtask_id=subtask_id,
                    role=role,
                    instruction=instruction,
                    dependencies=dependencies,
                    contract_schema=contract_schema,
                    role_executor_policy=role_executor_policy,
                    patches=patches,
                    metadata=subtask_metadata,
                )
            )
        return subtasks

    def _negotiate_contract(
        self,
        task: OptimizationTask,
        subtasks: Iterable[RuntimeSubTaskSpec],
    ) -> ContractNegotiationResult | None:
        if not self.config.require_contract_negotiation:
            return ContractNegotiationResult(agreed=True, reason="skipped")

        proposals = [
            ContractProposal(
                role=item.role,
                schema=item.contract_schema,
            )
            for item in subtasks
        ]
        metadata = task.metadata if isinstance(task.metadata, dict) else {}
        forced_id = str(metadata.get("contract_id") or "").strip()
        return negotiate_contract(proposals, contract_id=forced_id)

    @staticmethod
    async def _await_worker(worker: RuntimeWorker, subtask: RuntimeSubTaskSpec) -> RuntimeSubTaskResult:
        result = worker(subtask)
        if asyncio.iscoroutine(result):
            result = await result
        if isinstance(result, RuntimeSubTaskResult):
            return result
        return RuntimeSubTaskResult(
            subtask_id=subtask.subtask_id,
            role=subtask.role,
            success=False,
            error="invalid_worker_result",
        )

    @staticmethod
    def _emit(emit_event: RuntimeEventEmitter | None, event_type: str, **payload: Any) -> None:
        if emit_event is None:
            return
        emit_event(event_type, dict(payload))

    @staticmethod
    def _to_patch(payload: Dict[str, Any]) -> ScaffoldPatch:
        return ScaffoldPatch(
            path=str(payload.get("path") or payload.get("file_path") or "").strip(),
            content=str(payload.get("content") or ""),
            mode=str(payload.get("mode") or "overwrite").strip().lower(),
            encoding=str(payload.get("encoding") or "utf-8").strip(),
            expected_file_hash=str(
                payload.get("expected_file_hash") or payload.get("expected_hash") or payload.get("original_file_hash") or ""
            ).strip(),
            original_content=(
                str(payload.get("original_content")) if payload.get("original_content") is not None else None
            ),
            semantic_rebase=bool(payload.get("semantic_rebase", True)),
        )

    @staticmethod
    def _validate_subtask_specs(subtasks: List[RuntimeSubTaskSpec]) -> List[str]:
        errors: List[str] = []
        seen: set[str] = set()
        duplicates: set[str] = set()
        for item in subtasks:
            subtask_id = str(item.subtask_id or "").strip()
            if subtask_id in seen:
                duplicates.add(subtask_id)
            else:
                seen.add(subtask_id)
            if not str(item.instruction or "").strip():
                errors.append(f"empty_instruction:{subtask_id}")

        if duplicates:
            errors.append("duplicate_subtask_id:" + ",".join(sorted(duplicates)))

        valid_ids = {str(item.subtask_id or "").strip() for item in subtasks}
        for item in subtasks:
            subtask_id = str(item.subtask_id or "").strip()
            for dep in item.dependencies:
                dep_id = str(dep or "").strip()
                if not dep_id:
                    continue
                if dep_id == subtask_id:
                    errors.append(f"self_dependency:{subtask_id}")
                elif dep_id not in valid_ids:
                    errors.append(f"missing_dependency:{subtask_id}->{dep_id}")

        return sorted(set(errors))

    @staticmethod
    def _normalize_role(value: str) -> str:
        return str(value or "").strip().lower().replace("-", "_")

    @classmethod
    def _extract_role_executor_policy_from_contract_schema(
        cls,
        contract_schema: Dict[str, Any],
        *,
        role: str,
    ) -> Dict[str, Any]:
        if not isinstance(contract_schema, dict):
            return {}

        normalized_role = cls._normalize_role(role)
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
            for key, value in role_map.items():
                if not isinstance(value, dict):
                    continue
                if cls._normalize_role(str(key)) == normalized_role:
                    merged.update(value)
        return merged

    @staticmethod
    def _merge_policy_dicts(*payloads: Dict[str, Any]) -> Dict[str, Any]:
        merged: Dict[str, Any] = {}
        for payload in list(payloads):
            if not isinstance(payload, dict):
                continue
            merged.update(payload)
        return merged


__all__ = [
    "SubAgentRuntimeConfig",
    "RuntimeSubTaskSpec",
    "RuntimeSubTaskResult",
    "SubAgentRuntimeResult",
    "SubAgentRuntime",
]
