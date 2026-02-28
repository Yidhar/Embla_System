"""Append-only audit ledger with hash-chain integrity checks.

This module is designed for cross-domain governance records, where each entry
must be tamper-evident and attributable.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_text(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _canonical_json(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _trim_text(value: Any, *, field_name: str, max_len: int) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    return text[:max_len]


def _normalize_string_list(value: Any, *, max_items: int = 32, max_item_len: int = 240) -> List[str]:
    if not isinstance(value, list):
        return []
    normalized: List[str] = []
    for item in value:
        text = str(item or "").strip()
        if not text:
            continue
        normalized.append(text[:max_item_len])
        if len(normalized) >= max_items:
            break
    return normalized


class AuditLedgerRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default="ws28_audit_ledger.v1")
    generated_at: str
    record_type: str
    change_id: str
    scope: str
    risk_level: str
    requested_by: str
    approved_by: str = ""
    approval_ticket: str = ""
    evidence_refs: List[str] = Field(default_factory=list)
    payload: Dict[str, Any] = Field(default_factory=dict)
    prev_ledger_hash: str
    ledger_hash: str
    signature: str = ""


class AuditLedgerVerifyReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passed: bool
    checked_count: int
    errors: List[str] = Field(default_factory=list)


class AuditLedger:
    """Append-only hash-chain ledger.

    Each record hash covers all fields except `ledger_hash` and `signature`,
    plus the previous record hash to form an integrity chain.
    """

    def __init__(
        self,
        *,
        ledger_file: Path,
        signing_key: Optional[str] = None,
        signing_key_env: str = "EMBLA_AUDIT_SIGNING_KEY",
    ) -> None:
        self.ledger_file = Path(ledger_file)
        self.ledger_file.parent.mkdir(parents=True, exist_ok=True)
        env_signing_key = os.getenv(signing_key_env, "")
        self._signing_key = str(signing_key or env_signing_key or "").strip()
        self._lock = threading.Lock()

    def append_record(
        self,
        *,
        record_type: str,
        change_id: str,
        scope: str,
        risk_level: str,
        requested_by: str,
        approved_by: str = "",
        approval_ticket: str = "",
        evidence_refs: Optional[List[str]] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> AuditLedgerRecord:
        with self._lock:
            prev_hash = self.latest_hash()
            base_payload: Dict[str, Any] = {
                "schema_version": "ws28_audit_ledger.v1",
                "generated_at": _utc_iso(),
                "record_type": _trim_text(record_type, field_name="record_type", max_len=120),
                "change_id": _trim_text(change_id, field_name="change_id", max_len=120),
                "scope": _trim_text(scope, field_name="scope", max_len=120),
                "risk_level": _trim_text(risk_level, field_name="risk_level", max_len=64),
                "requested_by": _trim_text(requested_by, field_name="requested_by", max_len=120),
                "approved_by": str(approved_by or "").strip()[:120],
                "approval_ticket": str(approval_ticket or "").strip()[:160],
                "evidence_refs": _normalize_string_list(evidence_refs or []),
                "payload": payload if isinstance(payload, dict) else {},
                "prev_ledger_hash": prev_hash,
            }
            ledger_hash = _hash_text(_canonical_json(base_payload))
            signature = self._sign(ledger_hash)
            complete_payload = {
                **base_payload,
                "ledger_hash": ledger_hash,
                "signature": signature,
            }
            line = json.dumps(complete_payload, ensure_ascii=False)
            with self.ledger_file.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
            return AuditLedgerRecord.model_validate(complete_payload)

    def read_records(self) -> List[AuditLedgerRecord]:
        rows: List[AuditLedgerRecord] = []
        if not self.ledger_file.exists():
            return rows
        for line in self.ledger_file.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            try:
                rows.append(AuditLedgerRecord.model_validate(payload))
            except Exception:
                continue
        return rows

    def latest_hash(self) -> str:
        records = self.read_records()
        if not records:
            return "GENESIS"
        return records[-1].ledger_hash

    def verify_chain(self) -> AuditLedgerVerifyReport:
        records = self.read_records()
        errors: List[str] = []
        expected_prev = "GENESIS"

        for idx, record in enumerate(records, start=1):
            if record.prev_ledger_hash != expected_prev:
                errors.append(
                    f"record[{idx}] prev_ledger_hash mismatch: expected={expected_prev}, got={record.prev_ledger_hash}"
                )

            canonical_payload = {
                "schema_version": record.schema_version,
                "generated_at": record.generated_at,
                "record_type": record.record_type,
                "change_id": record.change_id,
                "scope": record.scope,
                "risk_level": record.risk_level,
                "requested_by": record.requested_by,
                "approved_by": record.approved_by,
                "approval_ticket": record.approval_ticket,
                "evidence_refs": list(record.evidence_refs),
                "payload": dict(record.payload),
                "prev_ledger_hash": record.prev_ledger_hash,
            }
            expected_hash = _hash_text(_canonical_json(canonical_payload))
            if record.ledger_hash != expected_hash:
                errors.append(
                    f"record[{idx}] ledger_hash mismatch: expected={expected_hash}, got={record.ledger_hash}"
                )

            if self._signing_key:
                expected_signature = self._sign(expected_hash)
                if record.signature != expected_signature:
                    errors.append(f"record[{idx}] signature mismatch")

            expected_prev = record.ledger_hash

        return AuditLedgerVerifyReport(
            passed=not errors,
            checked_count=len(records),
            errors=errors,
        )

    def _sign(self, ledger_hash: str) -> str:
        if not self._signing_key:
            return ""
        digest = hmac.new(
            self._signing_key.encode("utf-8"),
            ledger_hash.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return digest
