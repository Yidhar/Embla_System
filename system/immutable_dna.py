"""WS18-006 immutable DNA loader and verifier."""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_text(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class DNAFileSpec:
    path: str
    required: bool = True


@dataclass(frozen=True)
class DNAManifest:
    schema_version: str
    generated_at: str
    files: Dict[str, str] = field(default_factory=dict)
    injection_order: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DNAVerificationResult:
    ok: bool
    reason: str
    mismatch_files: List[str] = field(default_factory=list)
    missing_files: List[str] = field(default_factory=list)
    manifest_hash: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ImmutableDNALoader:
    """Validate prompt DNA hash and produce fixed-order injection content."""

    MANIFEST_SCHEMA_VERSION = "ws18-006-v1"

    def __init__(
        self,
        *,
        root_dir: Path,
        dna_files: Optional[List[DNAFileSpec]] = None,
        manifest_path: Optional[Path] = None,
        audit_file: Optional[Path] = None,
    ) -> None:
        self.root_dir = Path(root_dir)
        default_files = [
            DNAFileSpec(path="conversation_style_prompt.txt"),
            DNAFileSpec(path="conversation_analyzer_prompt.txt"),
            DNAFileSpec(path="tool_dispatch_prompt.txt"),
            DNAFileSpec(path="agentic_tool_prompt.txt"),
        ]
        self.dna_files = list(dna_files or default_files)
        self.manifest_path = manifest_path or (self.root_dir / "immutable_dna_manifest.json")
        self.audit_file = audit_file or (self.root_dir / "immutable_dna_audit.jsonl")
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.audit_file.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def bootstrap_manifest(self) -> DNAManifest:
        files_hash = self._compute_hashes()
        manifest = DNAManifest(
            schema_version=self.MANIFEST_SCHEMA_VERSION,
            generated_at=_utc_iso(),
            files=files_hash,
            injection_order=[spec.path for spec in self.dna_files],
        )
        self.manifest_path.write_text(json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        self._append_audit(
            "dna_manifest_bootstrap",
            {
                "manifest_path": str(self.manifest_path),
                "file_count": len(manifest.files),
            },
        )
        return manifest

    def verify(self) -> DNAVerificationResult:
        manifest = self._load_manifest()
        if manifest is None:
            result = DNAVerificationResult(ok=False, reason="manifest_missing")
            self._append_audit("dna_verify_failed", result.to_dict())
            return result

        current_hashes = self._compute_hashes()
        mismatch: List[str] = []
        missing: List[str] = []
        for path, expected_hash in manifest.files.items():
            actual_hash = current_hashes.get(path)
            if actual_hash is None:
                missing.append(path)
                continue
            if actual_hash != expected_hash:
                mismatch.append(path)

        manifest_hash = _sha256_text(json.dumps(manifest.to_dict(), ensure_ascii=False, sort_keys=True))
        if missing or mismatch:
            result = DNAVerificationResult(
                ok=False,
                reason="dna_hash_mismatch",
                mismatch_files=sorted(mismatch),
                missing_files=sorted(missing),
                manifest_hash=manifest_hash,
            )
            self._append_audit("dna_verify_failed", result.to_dict())
            return result

        result = DNAVerificationResult(ok=True, reason="ok", manifest_hash=manifest_hash)
        self._append_audit("dna_verify_ok", result.to_dict())
        return result

    def inject(self) -> Dict[str, Any]:
        verify_result = self.verify()
        if not verify_result.ok:
            raise PermissionError(
                "Immutable DNA verification failed: "
                f"{verify_result.reason}, mismatch={verify_result.mismatch_files}, missing={verify_result.missing_files}"
            )
        manifest = self._load_manifest()
        assert manifest is not None  # verify already checked
        ordered_content: List[str] = []
        for relative_path in manifest.injection_order:
            file_path = self.root_dir / relative_path
            text = file_path.read_text(encoding="utf-8")
            ordered_content.append(f"[DNA:{relative_path}]\n{text.strip()}\n")
        combined = "\n".join(ordered_content).strip()
        payload = {
            "schema_version": manifest.schema_version,
            "injection_order": list(manifest.injection_order),
            "dna_text": combined,
            "dna_hash": _sha256_text(combined),
        }
        self._append_audit(
            "dna_injected",
            {"dna_hash": payload["dna_hash"], "schema_version": payload["schema_version"], "order_count": len(manifest.injection_order)},
        )
        return payload

    def approved_update_manifest(self, *, approval_ticket: str) -> DNAManifest:
        ticket = str(approval_ticket or "").strip()
        if not ticket:
            self._append_audit("dna_manifest_update_rejected", {"reason": "missing_approval_ticket"})
            raise PermissionError("approval_ticket is required for immutable DNA manifest update")
        manifest = self.bootstrap_manifest()
        self._append_audit(
            "dna_manifest_update_approved",
            {"approval_ticket": ticket, "manifest_path": str(self.manifest_path), "file_count": len(manifest.files)},
        )
        return manifest

    def _load_manifest(self) -> Optional[DNAManifest]:
        if not self.manifest_path.exists():
            return None
        try:
            payload = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        files = payload.get("files")
        order = payload.get("injection_order")
        if not isinstance(files, dict) or not isinstance(order, list):
            return None
        return DNAManifest(
            schema_version=str(payload.get("schema_version") or self.MANIFEST_SCHEMA_VERSION),
            generated_at=str(payload.get("generated_at") or ""),
            files={str(k): str(v) for k, v in files.items()},
            injection_order=[str(item) for item in order],
        )

    def _compute_hashes(self) -> Dict[str, str]:
        hashes: Dict[str, str] = {}
        for spec in self.dna_files:
            file_path = self.root_dir / spec.path
            if not file_path.exists():
                if spec.required:
                    continue
                continue
            content = file_path.read_text(encoding="utf-8")
            hashes[spec.path] = _sha256_text(content)
        return hashes

    def _append_audit(self, event: str, payload: Dict[str, Any]) -> None:
        record = {"ts": _utc_iso(), "event": event, **payload}
        line = json.dumps(record, ensure_ascii=False)
        with self._lock:
            with self.audit_file.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
