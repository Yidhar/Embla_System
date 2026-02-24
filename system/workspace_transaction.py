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


@dataclass
class WorkspaceTransactionReceipt:
    transaction_id: str
    committed: bool
    clean_state: bool
    changed_files: List[str] = field(default_factory=list)
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

                if mode == "append":
                    current = backups[safe_path][1]
                    merged = current + change.content
                    self._write_text(safe_path, merged, encoding)
                else:
                    self._write_text(safe_path, change.content, encoding)

                touched.append(safe_path)
                rel = str(safe_path.relative_to(self.project_root)).replace("\\", "/")
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
