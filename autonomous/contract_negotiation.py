"""WS21-004 contract negotiation preflight for sub-agent runtime."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List

from system.subagent_contract import build_contract_checksum


def _stable_json(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _normalize_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize schema for deterministic checksum and equality checks."""

    text = _stable_json(schema)
    loaded = json.loads(text)
    return loaded if isinstance(loaded, dict) else {}


@dataclass(frozen=True)
class ContractProposal:
    role: str
    schema: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ContractNegotiationResult:
    agreed: bool
    contract_id: str = ""
    contract_checksum: str = ""
    canonical_schema: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    mismatch_roles: List[str] = field(default_factory=list)


def negotiate_contract(
    proposals: Iterable[ContractProposal],
    *,
    contract_id: str = "",
) -> ContractNegotiationResult:
    proposal_list = list(proposals)
    if not proposal_list:
        return ContractNegotiationResult(agreed=False, reason="no_contract_proposals")

    normalized: List[tuple[str, Dict[str, Any]]] = [
        (str(item.role or "worker"), _normalize_schema(item.schema or {})) for item in proposal_list
    ]
    canonical_schema = normalized[0][1]
    mismatch_roles = [role for role, schema in normalized[1:] if schema != canonical_schema]

    if mismatch_roles:
        return ContractNegotiationResult(
            agreed=False,
            canonical_schema=canonical_schema,
            reason="contract_mismatch",
            mismatch_roles=mismatch_roles,
        )

    normalized_contract_id = str(contract_id or "").strip()
    if not normalized_contract_id:
        digest = hashlib.sha1(_stable_json(canonical_schema).encode("utf-8")).hexdigest()[:16]
        normalized_contract_id = f"contract_{digest}"

    checksum = build_contract_checksum(normalized_contract_id, schema=canonical_schema)
    return ContractNegotiationResult(
        agreed=True,
        contract_id=normalized_contract_id,
        contract_checksum=checksum,
        canonical_schema=canonical_schema,
        reason="agreed",
    )


__all__ = [
    "ContractProposal",
    "ContractNegotiationResult",
    "negotiate_contract",
]
