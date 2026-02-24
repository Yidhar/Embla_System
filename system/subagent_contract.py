"""
Sub-agent contract helpers.

WS13-002/003:
- contract negotiation gate for parallel/scaffold actions
- scaffold fingerprint based on contract + patch targets
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple


def _sha256(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ContractValidationResult:
    ok: bool
    message: str
    normalized_contract_id: str = ""
    expected_checksum: str = ""
    scaffold_fingerprint: str = ""


def build_contract_checksum(contract_id: str, schema: Optional[Dict[str, object]] = None) -> str:
    normalized_id = (contract_id or "").strip()
    normalized_schema = schema or {}
    payload = json.dumps({"contract_id": normalized_id, "schema": normalized_schema}, ensure_ascii=False, sort_keys=True)
    return _sha256(payload)


def build_scaffold_fingerprint(contract_id: str, paths: Iterable[str]) -> str:
    normalized_paths = sorted({str(p).replace("\\", "/").strip() for p in paths if str(p).strip()})
    payload = json.dumps({"contract_id": (contract_id or "").strip(), "paths": normalized_paths}, ensure_ascii=False)
    return _sha256(payload)


def validate_parallel_contract(
    *,
    contract_id: str,
    contract_checksum: str,
    changed_paths: List[str],
) -> ContractValidationResult:
    paths = [str(p).replace("\\", "/").strip() for p in changed_paths if str(p).strip()]
    parallel_change = len(paths) > 1
    normalized_id = (contract_id or "").strip()
    checksum = (contract_checksum or "").strip()

    if parallel_change and not normalized_id:
        return ContractValidationResult(
            ok=False,
            message="Contract gate blocked: parallel changes require contract_id",
        )

    expected_checksum = ""
    if normalized_id:
        expected_checksum = build_contract_checksum(normalized_id, schema={"paths": sorted(paths)})
        if checksum and checksum != expected_checksum:
            return ContractValidationResult(
                ok=False,
                message="Contract gate blocked: contract_checksum mismatch",
                normalized_contract_id=normalized_id,
                expected_checksum=expected_checksum,
            )

    fingerprint = build_scaffold_fingerprint(normalized_id, paths) if normalized_id else ""
    return ContractValidationResult(
        ok=True,
        message="contract validated",
        normalized_contract_id=normalized_id,
        expected_checksum=expected_checksum,
        scaffold_fingerprint=fingerprint,
    )


__all__ = [
    "ContractValidationResult",
    "build_contract_checksum",
    "build_scaffold_fingerprint",
    "validate_parallel_contract",
]
