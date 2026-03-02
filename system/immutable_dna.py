"""Compatibility shim for immutable DNA core security implementation.

Legacy imports from `system.immutable_dna` remain supported.
Authoritative implementation lives in `core.security.immutable_dna`.
"""

from core.security.immutable_dna import (
    DNAFileSpec,
    DNAManifest,
    DNAVerificationResult,
    ImmutableDNAIntegrityMonitor,
    ImmutableDNALoader,
)

__all__ = [
    "DNAFileSpec",
    "DNAManifest",
    "DNAVerificationResult",
    "ImmutableDNALoader",
    "ImmutableDNAIntegrityMonitor",
]
