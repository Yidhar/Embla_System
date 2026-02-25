"""
Workspace transaction manager for multi-file atomic apply/rollback.

WS13-004:
- begin/apply_all/verify/commit/rollback flow
- rollback all touched files when any apply/verify step fails
"""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class WorkspaceChange:
    path: str
    content: str
    mode: str = "overwrite"  # overwrite|append
    encoding: str = "utf-8"
    # optimistic-lock hash from caller's baseline. accept alias expected_file_hash upstream.
    original_file_hash: str = ""
    # optional explicit alias to ease legacy/heterogeneous callers.
    expected_file_hash: str = ""
    # baseline content used for conservative 3-way semantic rebase when hash mismatch.
    original_content: Optional[str] = None
    # conservative default: allow semantic rebase path only when safe.
    semantic_rebase: bool = True
    # Optional per-change conflict backoff overrides.
    conflict_backoff_base_ms: Optional[int] = None
    conflict_backoff_max_ms: Optional[int] = None
    conflict_backoff_attempt: Optional[int] = None
    conflict_backoff_jitter_ratio: Optional[float] = None


@dataclass
class ConflictBackoffConfig:
    base_ms: int = 200
    max_ms: int = 5000
    attempt: int = 1
    jitter_ratio: float = 0.25


@dataclass
class WorkspaceTransactionReceipt:
    transaction_id: str
    committed: bool
    clean_state: bool
    changed_files: List[str] = field(default_factory=list)
    semantic_rebased_files: List[str] = field(default_factory=list)
    rolled_back_files: List[str] = field(default_factory=list)
    rollback_failed_files: List[str] = field(default_factory=list)
    recovery_ticket: str = ""
    verify_message: str = ""
    error: str = ""
    conflict_ticket: str = ""
    conflict_signature: str = ""
    backoff_ms: int = 0
    conflict_path: str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: float = 0.0


class WorkspaceConflictError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        conflict_ticket: str,
        conflict_signature: str,
        backoff_ms: int,
        conflict_path: str,
    ) -> None:
        super().__init__(message)
        self.conflict_ticket = conflict_ticket
        self.conflict_signature = conflict_signature
        self.backoff_ms = backoff_ms
        self.conflict_path = conflict_path


class WorkspaceTransactionManager:
    PROJECT_ROOT = Path(__file__).resolve().parents[1]

    def __init__(self, project_root: Optional[Path] = None) -> None:
        self.project_root = (project_root or self.PROJECT_ROOT).resolve()
        self._active: Dict[str, WorkspaceTransactionReceipt] = {}

    def _resolve(self, path: str) -> Path:
        raw = Path(path)
        full = raw if raw.is_absolute() else (self.project_root / raw)
        resolved = full.resolve(strict=False)
        root_s = str(self.project_root).lower()
        cand_s = str(resolved).lower()
        if not cand_s.startswith(root_s):
            raise PermissionError(f"path outside project root: {path}")
        return resolved

    @staticmethod
    def _read_text(path: Path, encoding: str) -> str:
        return path.read_text(encoding=encoding)

    @staticmethod
    def _write_text(path: Path, content: str, encoding: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding=encoding)

    @staticmethod
    def _normalize_hash(value: str) -> str:
        return str(value or "").strip().lower()

    @staticmethod
    def _normalize_backoff_config(config: Optional[ConflictBackoffConfig]) -> ConflictBackoffConfig:
        cfg = config or ConflictBackoffConfig()

        base_ms = max(1, min(600000, int(getattr(cfg, "base_ms", 200) or 200)))
        max_ms_raw = int(getattr(cfg, "max_ms", 5000) or 5000)
        max_ms = max(base_ms, min(600000, max_ms_raw))
        attempt = max(1, min(32, int(getattr(cfg, "attempt", 1) or 1)))

        jitter_raw = float(getattr(cfg, "jitter_ratio", 0.25) or 0.0)
        jitter_ratio = max(0.0, min(1.0, jitter_raw))
        return ConflictBackoffConfig(base_ms=base_ms, max_ms=max_ms, attempt=attempt, jitter_ratio=jitter_ratio)

    @staticmethod
    def _calc_conflict_backoff_ms(config: ConflictBackoffConfig, *, conflict_signature: str) -> int:
        exponent = max(0, config.attempt - 1)
        exponential_ms = config.base_ms * (2 ** exponent)
        capped_ms = min(config.max_ms, exponential_ms)
        if capped_ms >= config.max_ms:
            return config.max_ms

        jitter_span = int(capped_ms * config.jitter_ratio)
        if jitter_span <= 0:
            return capped_ms

        # Deterministic jitter keeps ticket/backoff reproducible for the same conflict signature.
        jitter_seed = f"{conflict_signature}:{config.attempt}"
        jitter_hash = hashlib.sha256(jitter_seed.encode("utf-8")).hexdigest()
        fraction = int(jitter_hash[:8], 16) / 0xFFFFFFFF
        jitter = int(jitter_span * fraction)
        return min(config.max_ms, capped_ms + jitter)

    @staticmethod
    def _build_conflict_signature(
        *,
        rel_path: str,
        expected_hash: str,
        current_hash: str,
        mode: str,
        reason: str,
        incoming_content: str,
    ) -> str:
        payload = "|".join(
            [
                rel_path.strip().lower(),
                mode.strip().lower(),
                expected_hash.strip().lower(),
                current_hash.strip().lower(),
                _sha256_text(incoming_content or ""),
                reason.strip().lower(),
            ]
        )
        return _sha256_text(payload)

    def _build_conflict_error(
        self,
        *,
        rel_path: str,
        expected_hash: str,
        current_hash: str,
        mode: str,
        reason: str,
        incoming_content: str,
        backoff_config: ConflictBackoffConfig,
    ) -> WorkspaceConflictError:
        signature = self._build_conflict_signature(
            rel_path=rel_path,
            expected_hash=expected_hash,
            current_hash=current_hash,
            mode=mode,
            reason=reason,
            incoming_content=incoming_content,
        )
        ticket = f"conflict_{signature[:20]}"
        backoff_ms = self._calc_conflict_backoff_ms(backoff_config, conflict_signature=signature)
        return WorkspaceConflictError(
            "semantic rebase failed: "
            f"path={rel_path}, expected_hash={expected_hash}, current_hash={current_hash}, reason={reason}",
            conflict_ticket=ticket,
            conflict_signature=signature,
            backoff_ms=backoff_ms,
            conflict_path=rel_path,
        )

    def _resolve_change_backoff_config(
        self,
        default_config: ConflictBackoffConfig,
        change: WorkspaceChange,
    ) -> ConflictBackoffConfig:
        merged = ConflictBackoffConfig(
            base_ms=(
                change.conflict_backoff_base_ms
                if change.conflict_backoff_base_ms is not None
                else default_config.base_ms
            ),
            max_ms=(
                change.conflict_backoff_max_ms if change.conflict_backoff_max_ms is not None else default_config.max_ms
            ),
            attempt=(
                change.conflict_backoff_attempt
                if change.conflict_backoff_attempt is not None
                else default_config.attempt
            ),
            jitter_ratio=(
                change.conflict_backoff_jitter_ratio
                if change.conflict_backoff_jitter_ratio is not None
                else default_config.jitter_ratio
            ),
        )
        return self._normalize_backoff_config(merged)

    @staticmethod
    def _diff_non_equal_ops(base_lines: List[str], target_lines: List[str]) -> List[Tuple[str, int, int, int, int]]:
        matcher = SequenceMatcher(a=base_lines, b=target_lines, autojunk=False)
        return [op for op in matcher.get_opcodes() if op[0] != "equal"]

    @staticmethod
    def _ops_overlap(
        op_a: Tuple[str, int, int, int, int],
        op_b: Tuple[str, int, int, int, int],
    ) -> bool:
        _, a1, a2, _, _ = op_a
        _, b1, b2, _, _ = op_b

        a_point = a1 == a2
        b_point = b1 == b2
        if a_point and b_point:
            return a1 == b1
        if a_point:
            # Conservative: insertion touching an edited boundary is treated as conflict.
            return b1 <= a1 <= b2
        if b_point:
            return a1 <= b1 <= a2
        return not (a2 <= b1 or b2 <= a1)

    def _has_overlapping_ops(
        self,
        incoming_ops: List[Tuple[str, int, int, int, int]],
        current_ops: List[Tuple[str, int, int, int, int]],
    ) -> bool:
        for op_a in incoming_ops:
            for op_b in current_ops:
                if self._ops_overlap(op_a, op_b):
                    return True
        return False

    @staticmethod
    def _translate_base_index_to_current(
        base_index: int,
        current_ops: List[Tuple[str, int, int, int, int]],
    ) -> Optional[int]:
        translated = base_index
        for _, i1, i2, j1, j2 in current_ops:
            base_len = i2 - i1
            current_len = j2 - j1
            delta = current_len - base_len

            if base_len > 0 and i1 < base_index < i2:
                return None
            if base_index >= i2:
                translated += delta
                continue
            if base_len == 0 and base_index >= i1:
                translated += delta
                continue
            if base_index < i1:
                break
        return translated

    def _semantic_rebase_overwrite(
        self,
        *,
        base_content: str,
        incoming_content: str,
        current_content: str,
    ) -> Tuple[bool, str, str]:
        if incoming_content == current_content:
            return True, current_content, "already up to date"

        base_lines = base_content.splitlines(keepends=True)
        incoming_lines = incoming_content.splitlines(keepends=True)
        current_lines = current_content.splitlines(keepends=True)

        incoming_ops = self._diff_non_equal_ops(base_lines, incoming_lines)
        if not incoming_ops:
            # Incoming edit is effectively a no-op against baseline.
            return True, current_content, "incoming no-op on baseline"

        current_ops = self._diff_non_equal_ops(base_lines, current_lines)
        if not current_ops:
            # Workspace stayed on baseline, safe to apply incoming directly.
            return True, incoming_content, "workspace unchanged from baseline"

        if self._has_overlapping_ops(incoming_ops, current_ops):
            return False, "", "overlapping line-level edits"

        merged_lines = list(current_lines)
        for _, i1, i2, j1, j2 in reversed(incoming_ops):
            start = self._translate_base_index_to_current(i1, current_ops)
            end = self._translate_base_index_to_current(i2, current_ops)
            if start is None or end is None or start > end:
                return False, "", "index translation failed"
            merged_lines[start:end] = incoming_lines[j1:j2]

        return True, "".join(merged_lines), "non-overlap line rebase"

    def begin(self) -> WorkspaceTransactionReceipt:
        tx_id = f"txn_{uuid.uuid4().hex[:16]}"
        receipt = WorkspaceTransactionReceipt(
            transaction_id=tx_id,
            committed=False,
            clean_state=True,
            recovery_ticket=f"recover_{uuid.uuid4().hex[:12]}",
        )
        self._active[tx_id] = receipt
        return receipt

    def apply_all(
        self,
        changes: List[WorkspaceChange],
        *,
        verify_fn: Optional[Callable[[WorkspaceTransactionReceipt], Tuple[bool, str]]] = None,
        conflict_backoff: Optional[ConflictBackoffConfig] = None,
    ) -> WorkspaceTransactionReceipt:
        if not changes:
            raise ValueError("changes must not be empty")

        receipt = self.begin()
        default_backoff_config = self._normalize_backoff_config(conflict_backoff)
        backups: Dict[Path, Tuple[bool, str, str, str]] = {}

        try:
            # begin -> apply_all
            for change in changes:
                safe_path = self._resolve(change.path)
                mode = (change.mode or "overwrite").strip().lower()
                encoding = change.encoding or "utf-8"
                if mode not in {"overwrite", "append"}:
                    raise ValueError(f"unsupported mode: {mode}")

                if safe_path not in backups:
                    existed = safe_path.exists()
                    original = self._read_text(safe_path, encoding) if existed else ""
                    original_hash = _sha256_text(original) if existed else ""
                    backups[safe_path] = (existed, original, original_hash, encoding)

                rel = str(safe_path.relative_to(self.project_root)).replace("\\", "/")

                current_text = self._read_text(safe_path, encoding) if safe_path.exists() else ""
                expected_hash = self._normalize_hash(change.expected_file_hash or change.original_file_hash)
                current_hash = _sha256_text(current_text) if safe_path.exists() else ""

                if expected_hash and current_hash != expected_hash:
                    change_backoff_config = self._resolve_change_backoff_config(default_backoff_config, change)
                    if not change.semantic_rebase:
                        raise self._build_conflict_error(
                            rel_path=rel,
                            expected_hash=expected_hash,
                            current_hash=current_hash,
                            mode=mode,
                            reason="semantic rebase disabled",
                            incoming_content=change.content,
                            backoff_config=change_backoff_config,
                        )

                    if mode == "append":
                        merged = current_text + change.content
                        self._write_text(safe_path, merged, encoding)
                        if rel not in receipt.semantic_rebased_files:
                            receipt.semantic_rebased_files.append(rel)
                    else:
                        base_content = change.original_content
                        if base_content is None:
                            raise self._build_conflict_error(
                                rel_path=rel,
                                expected_hash=expected_hash,
                                current_hash=current_hash,
                                mode=mode,
                                reason="original_content missing",
                                incoming_content=change.content,
                                backoff_config=change_backoff_config,
                            )
                        base_hash = self._normalize_hash(_sha256_text(base_content))
                        if base_hash != expected_hash:
                            raise RuntimeError(
                                "original_content hash mismatch for semantic rebase: "
                                f"path={rel}, expected_hash={expected_hash}, original_content_hash={base_hash}"
                            )
                        rebase_ok, rebased_text, rebase_reason = self._semantic_rebase_overwrite(
                            base_content=base_content,
                            incoming_content=change.content,
                            current_content=current_text,
                        )
                        if not rebase_ok:
                            raise self._build_conflict_error(
                                rel_path=rel,
                                expected_hash=expected_hash,
                                current_hash=current_hash,
                                mode=mode,
                                reason=rebase_reason,
                                incoming_content=change.content,
                                backoff_config=change_backoff_config,
                            )
                        self._write_text(safe_path, rebased_text, encoding)
                        if rel not in receipt.semantic_rebased_files:
                            receipt.semantic_rebased_files.append(rel)
                else:
                    if mode == "append":
                        merged = current_text + change.content
                        self._write_text(safe_path, merged, encoding)
                    else:
                        self._write_text(safe_path, change.content, encoding)

                if rel not in receipt.changed_files:
                    receipt.changed_files.append(rel)

            # verify
            if verify_fn is not None:
                verify_ok, verify_msg = verify_fn(receipt)
                receipt.verify_message = verify_msg
                if not verify_ok:
                    raise RuntimeError(f"verify failed: {verify_msg}")

            # commit
            receipt.committed = True
            receipt.clean_state = True
            return receipt

        except Exception as exc:
            # rollback all touched files
            rolled_back: List[str] = []
            rollback_failed: List[str] = []
            rollback_ok = True
            for safe_path, (existed, original, original_hash, backup_encoding) in backups.items():
                rel = str(safe_path.relative_to(self.project_root)).replace("\\", "/")
                try:
                    if existed:
                        self._write_text(safe_path, original, backup_encoding)
                        restored = self._read_text(safe_path, backup_encoding)
                        restored_hash = _sha256_text(restored)
                        if restored_hash != original_hash:
                            raise RuntimeError(
                                "rollback verification hash mismatch: "
                                f"path={rel}, expected={original_hash}, actual={restored_hash}"
                            )
                    else:
                        if safe_path.exists():
                            safe_path.unlink()
                        if safe_path.exists():
                            raise RuntimeError(f"rollback deletion failed: path={rel}")
                    rolled_back.append(rel)
                except Exception:
                    rollback_ok = False
                    rollback_failed.append(rel)

            receipt.committed = False
            receipt.clean_state = rollback_ok
            receipt.rolled_back_files = rolled_back
            receipt.rollback_failed_files = rollback_failed
            receipt.error = str(exc)
            if not receipt.recovery_ticket:
                receipt.recovery_ticket = f"recover_{uuid.uuid4().hex[:12]}"
            if isinstance(exc, WorkspaceConflictError):
                receipt.conflict_ticket = exc.conflict_ticket
                receipt.conflict_signature = exc.conflict_signature
                receipt.backoff_ms = exc.backoff_ms
                receipt.conflict_path = exc.conflict_path
            return receipt

        finally:
            receipt.finished_at = time.time()
            self._active.pop(receipt.transaction_id, None)


__all__ = [
    "ConflictBackoffConfig",
    "WorkspaceChange",
    "WorkspaceConflictError",
    "WorkspaceTransactionReceipt",
    "WorkspaceTransactionManager",
]
