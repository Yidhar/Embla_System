"""Immutable DNA loader + integrity monitor for core security plane."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except Exception:  # pragma: no cover - optional dependency
    AESGCM = None  # type: ignore[assignment]


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_text(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class EventEmitter(Protocol):
    def emit(
        self,
        event_type: str,
        payload: Dict[str, Any],
        *,
        source: str | None = None,
        severity: str | None = None,
        idempotency_key: str | None = None,
    ) -> None:
        ...


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
    manifest_file_sha256: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ImmutableDNALoader:
    """Validate prompt DNA hash and produce fixed-order injection content."""

    MANIFEST_SCHEMA_VERSION = "ws18-006-v1"
    ENCRYPTED_PREFIX = "EMBLA_DNA_ENC_V1:"
    ENCRYPTION_KEY_ENV = "EMBLA_IMMUTABLE_DNA_KEY"
    ENCRYPT_MANIFEST_ON_BOOTSTRAP_ENV = "EMBLA_IMMUTABLE_DNA_ENCRYPT_MANIFEST_ON_BOOTSTRAP"

    def __init__(
        self,
        *,
        root_dir: Path,
        dna_files: Optional[List[DNAFileSpec]] = None,
        manifest_path: Optional[Path] = None,
        audit_file: Optional[Path] = None,
        encryption_key: str | bytes | None = None,
        encryption_key_env: str = ENCRYPTION_KEY_ENV,
        encrypt_manifest_on_bootstrap: Optional[bool] = None,
    ) -> None:
        self.root_dir = Path(root_dir)
        default_files = [
            DNAFileSpec(path="conversation_style_prompt.md"),
            DNAFileSpec(path="agentic_tool_prompt.md"),
        ]
        self.dna_files = list(dna_files or default_files)
        self.manifest_path = manifest_path or (self.root_dir / "immutable_dna_manifest.json")
        self.audit_file = audit_file or (self.root_dir / "immutable_dna_audit.jsonl")
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.audit_file.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._encryption_key = self._resolve_encryption_key(
            raw_key=encryption_key,
            key_env=encryption_key_env,
        )
        if encrypt_manifest_on_bootstrap is None:
            self._encrypt_manifest_on_bootstrap = self._resolve_bool_env(
                self.ENCRYPT_MANIFEST_ON_BOOTSTRAP_ENV,
                default=False,
            )
        else:
            self._encrypt_manifest_on_bootstrap = bool(encrypt_manifest_on_bootstrap)

    @property
    def encryption_enabled(self) -> bool:
        return self._encryption_key is not None

    def bootstrap_manifest(self) -> DNAManifest:
        files_hash = self._compute_hashes()
        manifest = DNAManifest(
            schema_version=self.MANIFEST_SCHEMA_VERSION,
            generated_at=_utc_iso(),
            files=files_hash,
            injection_order=[spec.path for spec in self.dna_files],
        )
        manifest_json = json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2)
        if self._encrypt_manifest_on_bootstrap:
            if self._encryption_key is None:
                raise PermissionError("immutable DNA manifest encryption requested but encryption key is unavailable")
            manifest_json = self.encrypt_text_payload(manifest_json, key=self._encryption_key)
        self.manifest_path.write_text(manifest_json, encoding="utf-8")
        self._append_audit(
            "dna_manifest_bootstrap",
            {
                "manifest_path": str(self.manifest_path),
                "file_count": len(manifest.files),
                "encrypted": self._encrypt_manifest_on_bootstrap,
            },
        )
        return manifest

    def verify(self) -> DNAVerificationResult:
        manifest = self._load_manifest()
        manifest_file_sha = self.manifest_file_sha256()
        if manifest is None:
            result = DNAVerificationResult(
                ok=False,
                reason="manifest_missing",
                manifest_file_sha256=manifest_file_sha,
            )
            self._append_audit("dna_verify_failed", result.to_dict())
            return result

        current_hashes = self._compute_hashes()
        active_paths = self._active_file_paths()
        mismatch: List[str] = []
        missing: List[str] = []
        for path in active_paths:
            expected_hash = manifest.files.get(path)
            if not expected_hash:
                missing.append(path)
                continue
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
                manifest_file_sha256=manifest_file_sha,
            )
            self._append_audit("dna_verify_failed", result.to_dict())
            return result

        result = DNAVerificationResult(
            ok=True,
            reason="ok",
            manifest_hash=manifest_hash,
            manifest_file_sha256=manifest_file_sha,
        )
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
        assert manifest is not None
        ordered_content: List[str] = []
        for relative_path in self._active_file_paths():
            file_path = self.root_dir / relative_path
            text = self._read_text_maybe_encrypted(file_path)
            ordered_content.append(f"[DNA:{relative_path}]\n{text.strip()}\n")
        combined = "\n".join(ordered_content).strip()
        payload = {
            "schema_version": manifest.schema_version,
            "injection_order": self._active_file_paths(),
            "dna_text": combined,
            "dna_hash": _sha256_text(combined),
        }
        self._append_audit(
            "dna_injected",
            {
                "dna_hash": payload["dna_hash"],
                "schema_version": payload["schema_version"],
                "order_count": len(manifest.injection_order),
            },
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

    def manifest_file_sha256(self) -> str:
        if not self.manifest_path.exists():
            return ""
        try:
            return _sha256_bytes(self.manifest_path.read_bytes())
        except OSError:
            return ""

    def _load_manifest(self) -> Optional[DNAManifest]:
        if not self.manifest_path.exists():
            return None
        try:
            manifest_text = self._read_text_maybe_encrypted(self.manifest_path)
            payload = json.loads(manifest_text)
        except (json.JSONDecodeError, OSError, PermissionError):
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
            content = self._read_text_maybe_encrypted(file_path)
            hashes[spec.path] = _sha256_text(content)
        return hashes

    def _active_file_paths(self) -> List[str]:
        rows: List[str] = []
        for spec in self.dna_files:
            path = str(spec.path or "").strip()
            if path and path not in rows:
                rows.append(path)
        return rows

    def _append_audit(self, event: str, payload: Dict[str, Any]) -> None:
        record = {"ts": _utc_iso(), "event": event, **payload}
        line = json.dumps(record, ensure_ascii=False)
        with self._lock:
            with self.audit_file.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")

    def _read_text_maybe_encrypted(self, path: Path) -> str:
        text = path.read_text(encoding="utf-8")
        if not text.startswith(self.ENCRYPTED_PREFIX):
            return text
        if self._encryption_key is None:
            raise PermissionError(f"immutable DNA encrypted payload requires key: {path}")
        encrypted_payload = text[len(self.ENCRYPTED_PREFIX) :].strip()
        return self.decrypt_text_payload(encrypted_payload, key=self._encryption_key)

    @classmethod
    def encrypt_text_payload(cls, plaintext: str, *, key: bytes) -> str:
        if AESGCM is None:
            raise RuntimeError("cryptography dependency unavailable for immutable DNA encryption")
        key_bytes = cls._normalize_key_bytes(key)
        nonce = os.urandom(12)
        aesgcm = AESGCM(key_bytes)
        ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), associated_data=None)
        payload = {
            "v": 1,
            "alg": "AES-256-GCM",
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        }
        return cls.ENCRYPTED_PREFIX + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def decrypt_text_payload(cls, encrypted_payload: str, *, key: bytes) -> str:
        if AESGCM is None:
            raise RuntimeError("cryptography dependency unavailable for immutable DNA decryption")
        payload = json.loads(str(encrypted_payload or ""))
        if not isinstance(payload, dict):
            raise PermissionError("invalid immutable DNA encrypted payload")
        nonce_raw = payload.get("nonce")
        cipher_raw = payload.get("ciphertext")
        if not isinstance(nonce_raw, str) or not isinstance(cipher_raw, str):
            raise PermissionError("immutable DNA encrypted payload missing nonce/ciphertext")
        nonce = base64.b64decode(nonce_raw.encode("ascii"))
        ciphertext = base64.b64decode(cipher_raw.encode("ascii"))
        aesgcm = AESGCM(cls._normalize_key_bytes(key))
        plaintext = aesgcm.decrypt(nonce, ciphertext, associated_data=None)
        return plaintext.decode("utf-8")

    @classmethod
    def _resolve_encryption_key(cls, *, raw_key: str | bytes | None, key_env: str) -> bytes | None:
        candidate: str | bytes | None = raw_key
        if candidate is None:
            env_value = os.getenv(str(key_env or cls.ENCRYPTION_KEY_ENV), "")
            candidate = env_value if env_value else None
        if candidate is None:
            return None
        return cls._normalize_key_bytes(candidate)

    @staticmethod
    def _normalize_key_bytes(raw_key: str | bytes) -> bytes:
        if isinstance(raw_key, bytes):
            key_bytes = raw_key
        else:
            key_text = str(raw_key or "").strip()
            if key_text.startswith("base64:"):
                key_bytes = base64.b64decode(key_text[len("base64:") :].encode("ascii"))
            else:
                try:
                    decoded = base64.b64decode(key_text.encode("ascii"), validate=True)
                    key_bytes = decoded if len(decoded) in {16, 24, 32} else key_text.encode("utf-8")
                except Exception:
                    key_bytes = key_text.encode("utf-8")
        if len(key_bytes) in {16, 24, 32}:
            return key_bytes
        return hashlib.sha256(key_bytes).digest()

    @staticmethod
    def _resolve_bool_env(name: str, default: bool) -> bool:
        raw = os.getenv(str(name or ""), "")
        normalized = str(raw or "").strip().lower()
        if not normalized:
            return bool(default)
        return normalized not in {"0", "false", "no", "off"}


class ImmutableDNAIntegrityMonitor:
    """Periodic integrity checker that emits tamper incidents via EventBus."""

    def __init__(
        self,
        *,
        loader: ImmutableDNALoader,
        event_emitter: Optional[EventEmitter] = None,
        state_file: Path = Path("scratch/runtime/immutable_dna_integrity_state_ws30_001.json"),
        interval_seconds: float = 30.0,
        allow_manifest_hash_rotation: bool = False,
    ) -> None:
        self.loader = loader
        self.event_emitter = event_emitter
        self.state_file = Path(state_file)
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.interval_seconds = max(1.0, float(interval_seconds))
        self.allow_manifest_hash_rotation = bool(allow_manifest_hash_rotation)
        self._last_tamper_signature = ""
        self._baseline_manifest_file_sha = ""

    def run_once(self) -> Dict[str, Any]:
        generated_at = _utc_iso()
        verify = self.loader.verify()
        verify_payload = verify.to_dict()
        manifest_file_sha = str(verify_payload.get("manifest_file_sha256") or self.loader.manifest_file_sha256() or "")
        if not self._baseline_manifest_file_sha and manifest_file_sha:
            self._baseline_manifest_file_sha = manifest_file_sha

        status = "ok"
        reason_code = "IMMUTABLE_DNA_INTEGRITY_OK"
        reason_text = "immutable DNA integrity monitor check passed"
        tamper_detected = False

        if not verify.ok:
            status = "critical"
            reason_code = "IMMUTABLE_DNA_TAMPER_DETECTED"
            reason_text = f"immutable DNA verification failed: {verify.reason}"
            tamper_detected = True
        elif (
            self._baseline_manifest_file_sha
            and manifest_file_sha
            and manifest_file_sha != self._baseline_manifest_file_sha
        ):
            if self.allow_manifest_hash_rotation:
                status = "warning"
                reason_code = "IMMUTABLE_DNA_MANIFEST_HASH_ROTATED"
                reason_text = "immutable DNA manifest hash rotated during runtime"
            else:
                status = "critical"
                reason_code = "IMMUTABLE_DNA_MANIFEST_HASH_CHANGED"
                reason_text = "immutable DNA manifest hash changed during runtime"
                tamper_detected = True

        payload: Dict[str, Any] = {
            "generated_at": generated_at,
            "status": status,
            "reason_code": reason_code,
            "reason_text": reason_text,
            "tamper_detected": tamper_detected,
            "manifest_file_sha256": manifest_file_sha,
            "baseline_manifest_file_sha256": self._baseline_manifest_file_sha,
            "manifest_hash": str(verify_payload.get("manifest_hash") or ""),
            "verify": verify_payload,
            "state_file": str(self.state_file).replace("\\", "/"),
            "interval_seconds": float(self.interval_seconds),
        }
        self.state_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self._emit_sample(payload)
        if tamper_detected:
            self._emit_tamper(payload)
        return payload

    def run_daemon(
        self,
        *,
        stop_event: Optional[threading.Event] = None,
        interval_seconds: Optional[float] = None,
        max_ticks: int = 1000000000,
    ) -> Dict[str, Any]:
        stop = stop_event or threading.Event()
        tick = 0
        safe_interval = max(1.0, float(interval_seconds or self.interval_seconds))
        safe_max_ticks = max(1, int(max_ticks))
        last_payload: Dict[str, Any] = {}

        while tick < safe_max_ticks and not stop.is_set():
            tick += 1
            payload = self.run_once()
            payload["mode"] = "daemon"
            payload["tick"] = int(tick)
            self.state_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            last_payload = payload
            if tick >= safe_max_ticks or stop.is_set():
                break
            stop.wait(safe_interval)

        return {
            "mode": "daemon",
            "ticks_completed": int(tick),
            "state_file": str(self.state_file).replace("\\", "/"),
            "last_observation": last_payload,
            "stopped_by_request": bool(stop.is_set()),
        }

    @staticmethod
    def read_state(state_file: Path) -> Dict[str, Any]:
        path = Path(state_file)
        if not path.exists():
            return {
                "status": "unknown",
                "reason_code": "IMMUTABLE_DNA_MONITOR_STATE_MISSING",
                "reason_text": "immutable DNA monitor state file is missing",
                "state_file": str(path).replace("\\", "/"),
            }
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {
                "status": "warning",
                "reason_code": "IMMUTABLE_DNA_MONITOR_STATE_INVALID",
                "reason_text": "immutable DNA monitor state payload is invalid",
                "state_file": str(path).replace("\\", "/"),
            }
        if not isinstance(payload, dict):
            return {
                "status": "warning",
                "reason_code": "IMMUTABLE_DNA_MONITOR_STATE_INVALID",
                "reason_text": "immutable DNA monitor state payload is invalid",
                "state_file": str(path).replace("\\", "/"),
            }
        payload.setdefault("state_file", str(path).replace("\\", "/"))
        payload["status"] = str(payload.get("status") or "unknown").strip().lower()
        payload["reason_code"] = str(payload.get("reason_code") or "")
        payload["reason_text"] = str(payload.get("reason_text") or "")
        payload["tamper_detected"] = bool(payload.get("tamper_detected"))
        return payload

    def _emit_sample(self, payload: Dict[str, Any]) -> None:
        if self.event_emitter is None:
            return
        try:
            self.event_emitter.emit(
                "ImmutableDNAIntegritySampled",
                dict(payload),
                source="core.security.immutable_dna",
                severity="warning" if payload.get("status") == "warning" else "info",
            )
        except Exception:
            return

    def _emit_tamper(self, payload: Dict[str, Any]) -> None:
        if self.event_emitter is None:
            return
        signature = "|".join(
            [
                str(payload.get("reason_code") or ""),
                str(payload.get("manifest_hash") or ""),
                str(payload.get("manifest_file_sha256") or ""),
            ]
        )
        if signature and signature == self._last_tamper_signature:
            return
        self._last_tamper_signature = signature
        try:
            self.event_emitter.emit(
                "ImmutableDNATamperDetected",
                dict(payload),
                source="core.security.immutable_dna",
                severity="critical",
                idempotency_key=f"immutable_dna_tamper:{signature}",
            )
        except Exception:
            return


__all__ = [
    "DNAFileSpec",
    "DNAManifest",
    "DNAVerificationResult",
    "ImmutableDNALoader",
    "ImmutableDNAIntegrityMonitor",
]
