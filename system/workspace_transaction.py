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


@dataclass
class WorkspaceTransactionReceipt:
    transaction_id: str
    committed: bool
    clean_state: bool
    changed_files: List[str] = field(default_factory=list)
    semantic_rebased_files: List[str] = field(default_factory=list)
    rolled_back_files: List[str] = field(default_factory=list)
    recovery_ticket: str = ""
    verify_message: str = ""
    error: str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: float = 0.0


class WorkspaceTransactionManager:
    PROJECT_ROOT = Path(r"E:\Programs\NagaAgent").resolve()

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
    ) -> WorkspaceTransactionReceipt:
        if not changes:
            raise ValueError("changes must not be empty")

        receipt = self.begin()
        backups: Dict[Path, Tuple[bool, str, str]] = {}
        touched: List[Path] = []

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
                    backups[safe_path] = (existed, original, original_hash)

                rel = str(safe_path.relative_to(self.project_root)).replace("\\", "/")

                current_text = self._read_text(safe_path, encoding) if safe_path.exists() else ""
                expected_hash = self._normalize_hash(change.expected_file_hash or change.original_file_hash)
                current_hash = _sha256_text(current_text) if safe_path.exists() else ""

                if expected_hash and current_hash != expected_hash:
                    if not change.semantic_rebase:
                        raise RuntimeError(
                            "semantic rebase disabled: "
                            f"path={rel}, expected_hash={expected_hash}, current_hash={current_hash}"
                        )

                    if mode == "append":
                        merged = current_text + change.content
                        self._write_text(safe_path, merged, encoding)
                        if rel not in receipt.semantic_rebased_files:
                            receipt.semantic_rebased_files.append(rel)
                    else:
                        base_content = change.original_content
                        if base_content is None:
                            raise RuntimeError(
                                "semantic rebase requires original_content when overwrite hash mismatches: "
                                f"path={rel}, expected_hash={expected_hash}, current_hash={current_hash}"
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
                            raise RuntimeError(
                                "semantic rebase failed: "
                                f"path={rel}, expected_hash={expected_hash}, "
                                f"current_hash={current_hash}, reason={rebase_reason}"
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

                touched.append(safe_path)
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
            rollback_ok = True
            for safe_path, (existed, original, _) in backups.items():
                try:
                    if existed:
                        self._write_text(safe_path, original, "utf-8")
                    else:
                        if safe_path.exists():
                            safe_path.unlink()
                    rel = str(safe_path.relative_to(self.project_root)).replace("\\", "/")
                    rolled_back.append(rel)
                except Exception:
                    rollback_ok = False

            receipt.committed = False
            receipt.clean_state = rollback_ok
            receipt.rolled_back_files = rolled_back
            receipt.error = str(exc)
            return receipt

        finally:
            receipt.finished_at = time.time()
            self._active.pop(receipt.transaction_id, None)


__all__ = [
    "WorkspaceChange",
    "WorkspaceTransactionReceipt",
    "WorkspaceTransactionManager",
]
