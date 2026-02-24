"""WS21-001 scaffold engine with contract gate + transaction rollback."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List

from autonomous.scaffold_verify_pipeline import ScaffoldVerifyPipeline, build_default_verify_pipeline
from system.subagent_contract import validate_parallel_contract
from system.workspace_transaction import ConflictBackoffConfig, WorkspaceChange, WorkspaceTransactionManager


@dataclass(frozen=True)
class ScaffoldPatch:
    path: str
    content: str
    mode: str = "overwrite"
    encoding: str = "utf-8"
    expected_file_hash: str = ""
    original_content: str | None = None
    semantic_rebase: bool = True


@dataclass
class ScaffoldApplyResult:
    committed: bool
    clean_state: bool
    gate: str = ""
    error: str = ""
    transaction_id: str = ""
    contract_id: str = ""
    contract_checksum: str = ""
    scaffold_fingerprint: str = ""
    changed_files: List[str] = field(default_factory=list)
    semantic_rebased_files: List[str] = field(default_factory=list)
    rolled_back_files: List[str] = field(default_factory=list)
    rollback_failed_files: List[str] = field(default_factory=list)
    verify_summary: str = ""
    verify_step_results: List[Dict[str, Any]] = field(default_factory=list)
    recovery_ticket: str = ""
    conflict_ticket: str = ""
    conflict_signature: str = ""
    backoff_ms: int = 0
    conflict_path: str = ""


class ScaffoldEngine:
    """Apply multi-file scaffold patches atomically through workspace transaction."""

    def __init__(
        self,
        *,
        project_root: str | Path,
        verify_pipeline: ScaffoldVerifyPipeline | None = None,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.verify_pipeline = verify_pipeline or build_default_verify_pipeline()
        self.workspace_txn = WorkspaceTransactionManager(project_root=self.project_root)

    def apply(
        self,
        *,
        patches: Iterable[ScaffoldPatch | Dict[str, Any]],
        contract_id: str = "",
        contract_checksum: str = "",
        trace_id: str = "",
        verify_context: Dict[str, Any] | None = None,
        conflict_backoff: ConflictBackoffConfig | None = None,
    ) -> ScaffoldApplyResult:
        patch_list = [self._to_patch(item) for item in patches]
        if not patch_list:
            return ScaffoldApplyResult(
                committed=False,
                clean_state=True,
                gate="scaffold",
                error="empty_patch_set",
            )

        changed_paths = [self._normalize_rel_path(item.path) for item in patch_list]
        contract_result = validate_parallel_contract(
            contract_id=str(contract_id or "").strip(),
            contract_checksum=str(contract_checksum or "").strip(),
            changed_paths=changed_paths,
        )
        if not contract_result.ok:
            return ScaffoldApplyResult(
                committed=False,
                clean_state=True,
                gate="contract",
                error=contract_result.message,
                contract_id=contract_result.normalized_contract_id,
                contract_checksum=contract_result.expected_checksum,
            )

        changes = [
            WorkspaceChange(
                path=self._normalize_rel_path(item.path),
                content=item.content,
                mode=item.mode,
                encoding=item.encoding,
                original_file_hash=item.expected_file_hash,
                expected_file_hash=item.expected_file_hash,
                original_content=item.original_content,
                semantic_rebase=item.semantic_rebase,
            )
            for item in patch_list
        ]

        verify_state: Dict[str, Any] = {"summary": "verify skipped", "steps": []}

        def _verify(receipt: Any) -> tuple[bool, str]:
            context: Dict[str, Any] = {
                "trace_id": trace_id,
                "contract_id": contract_result.normalized_contract_id,
                "contract_checksum": contract_result.expected_checksum,
                "scaffold_fingerprint": contract_result.scaffold_fingerprint,
                "changed_files": list(receipt.changed_files),
                "semantic_rebased_files": list(receipt.semantic_rebased_files),
                "receipt": receipt,
            }
            if verify_context:
                context.update(verify_context)
            pipeline_result = self.verify_pipeline.run(context)
            verify_state["summary"] = pipeline_result.summary
            verify_state["steps"] = [
                {
                    "name": item.name,
                    "passed": item.passed,
                    "severity": item.severity,
                    "detail": item.detail,
                }
                for item in pipeline_result.step_results
            ]
            return pipeline_result.passed, pipeline_result.summary

        receipt = self.workspace_txn.apply_all(changes, verify_fn=_verify, conflict_backoff=conflict_backoff)
        if not receipt.committed:
            return ScaffoldApplyResult(
                committed=False,
                clean_state=receipt.clean_state,
                gate="scaffold",
                error=receipt.error,
                transaction_id=receipt.transaction_id,
                contract_id=contract_result.normalized_contract_id,
                contract_checksum=contract_result.expected_checksum,
                scaffold_fingerprint=contract_result.scaffold_fingerprint,
                changed_files=list(receipt.changed_files),
                semantic_rebased_files=list(receipt.semantic_rebased_files),
                rolled_back_files=list(receipt.rolled_back_files),
                rollback_failed_files=list(receipt.rollback_failed_files),
                verify_summary=verify_state["summary"],
                verify_step_results=list(verify_state["steps"]),
                recovery_ticket=receipt.recovery_ticket,
                conflict_ticket=receipt.conflict_ticket,
                conflict_signature=receipt.conflict_signature,
                backoff_ms=receipt.backoff_ms,
                conflict_path=receipt.conflict_path,
            )

        return ScaffoldApplyResult(
            committed=True,
            clean_state=True,
            transaction_id=receipt.transaction_id,
            contract_id=contract_result.normalized_contract_id,
            contract_checksum=contract_result.expected_checksum,
            scaffold_fingerprint=contract_result.scaffold_fingerprint,
            changed_files=list(receipt.changed_files),
            semantic_rebased_files=list(receipt.semantic_rebased_files),
            verify_summary=verify_state["summary"],
            verify_step_results=list(verify_state["steps"]),
            recovery_ticket=receipt.recovery_ticket,
        )

    def _normalize_rel_path(self, path: str) -> str:
        raw = Path(str(path or "").strip())
        if raw.is_absolute():
            resolved = raw.resolve(strict=False)
            return str(resolved.relative_to(self.project_root)).replace("\\", "/")
        return str(raw).replace("\\", "/").strip()

    @staticmethod
    def _to_patch(payload: ScaffoldPatch | Dict[str, Any]) -> ScaffoldPatch:
        if isinstance(payload, ScaffoldPatch):
            return payload
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


__all__ = [
    "ScaffoldPatch",
    "ScaffoldApplyResult",
    "ScaffoldEngine",
]
