"""WS24-002 plugin manifest trust policy and schema validation."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, MutableMapping, Sequence


_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{1,63}$")
_SAFE_MODULE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_\\.]{1,127}$")
_SAFE_CLASS_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_SAFE_COMMAND_RE = re.compile(r"^[^\s`'\"|;&<>]{1,64}$")

_ALLOWED_TOP_LEVEL_KEYS = {
    "name",
    "displayName",
    "version",
    "description",
    "author",
    "agentType",
    "entryPoint",
    "capabilities",
    "isolation",
    "policy",
    "signature",
}
_ALLOWED_ENTRYPOINT_KEYS = {"module", "class"}
_ALLOWED_CAPABILITIES_KEYS = {"invocationCommands"}
_ALLOWED_INVOCATION_KEYS = {"command", "description", "example"}
_ALLOWED_ISOLATION_KEYS = {
    "mode",
    "timeout_seconds",
    "max_payload_bytes",
    "max_output_bytes",
    "max_memory_mb",
    "cpu_time_seconds",
    "max_failure_streak",
    "cooldown_seconds",
    "stale_reap_grace_seconds",
}
_ALLOWED_POLICY_KEYS = {"scopes"}
_ALLOWED_SIGNATURE_KEYS = {"algorithm", "key_id", "value"}
_FORBIDDEN_SCOPES = {"host_process", "host_memory", "host_filesystem", "disable_watchdog", "disable_fencing"}
_DEFAULT_ALLOWED_SCOPES = {
    "read_workspace",
    "write_workspace",
    "read_logs",
    "network_none",
    "network_http",
    "tool_invoke",
}


@dataclass(frozen=True)
class PluginWorkerLimits:
    timeout_seconds: float = 30.0
    max_payload_bytes: int = 131_072
    max_output_bytes: int = 262_144
    max_memory_mb: int = 256
    cpu_time_seconds: int = 20
    max_failure_streak: int = 3
    cooldown_seconds: float = 30.0
    stale_reap_grace_seconds: float = 90.0


@dataclass(frozen=True)
class PluginManifestValidationResult:
    accepted: bool
    reason: str
    normalized_manifest: Dict[str, Any]
    worker_limits: PluginWorkerLimits


def _split_env_tokens(raw: str) -> list[str]:
    text = str(raw or "").strip()
    if not text:
        return []
    normalized = text.replace(";", ",").replace("\n", ",")
    return [item.strip() for item in normalized.split(",") if item.strip()]


def load_plugin_allowlist() -> set[str]:
    allowlist = {item for item in _split_env_tokens(os.getenv("NAGA_PLUGIN_ALLOWLIST", "")) if item}
    return allowlist


def load_plugin_signing_keys() -> Dict[str, str]:
    raw = str(os.getenv("NAGA_PLUGIN_SIGNING_KEYS", "")).strip()
    if not raw:
        return {}

    parsed: Dict[str, str] = {}
    try:
        payload = json.loads(raw)
        if isinstance(payload, dict):
            for key, value in payload.items():
                key_text = str(key or "").strip()
                value_text = str(value or "").strip()
                if key_text and value_text:
                    parsed[key_text] = value_text
            if parsed:
                return parsed
    except Exception:
        pass

    for item in _split_env_tokens(raw):
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        key_text = str(key or "").strip()
        value_text = str(value or "").strip()
        if key_text and value_text:
            parsed[key_text] = value_text
    return parsed


def load_allowed_scopes() -> set[str]:
    raw_scopes = {item for item in _split_env_tokens(os.getenv("NAGA_PLUGIN_ALLOWED_SCOPES", "")) if item}
    return raw_scopes or set(_DEFAULT_ALLOWED_SCOPES)


def compute_manifest_signature(manifest: Mapping[str, Any], *, secret: str) -> str:
    """Compute hmac-sha256 signature over canonicalized manifest without signature node."""
    normalized: Dict[str, Any] = dict(manifest)
    normalized.pop("signature", None)
    canonical = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hmac.new(
        str(secret).encode("utf-8"),
        canonical.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _has_only_keys(payload: Mapping[str, Any], *, allowed: set[str]) -> bool:
    return all(str(key) in allowed for key in payload.keys())


def _normalize_scopes(policy: Mapping[str, Any]) -> list[str]:
    scopes = policy.get("scopes", [])
    if not isinstance(scopes, Sequence) or isinstance(scopes, (str, bytes)):
        return []
    normalized: list[str] = []
    for item in scopes:
        scope = str(item or "").strip()
        if scope:
            normalized.append(scope)
    return normalized


def _clamp_float(value: Any, *, default: float, lower: float, upper: float) -> float:
    try:
        parsed = float(value)
    except Exception:
        parsed = default
    return max(lower, min(upper, parsed))


def _clamp_int(value: Any, *, default: int, lower: int, upper: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(lower, min(upper, parsed))


def _normalize_worker_limits(isolation: Mapping[str, Any]) -> PluginWorkerLimits:
    return PluginWorkerLimits(
        timeout_seconds=_clamp_float(isolation.get("timeout_seconds"), default=30.0, lower=1.0, upper=300.0),
        max_payload_bytes=_clamp_int(
            isolation.get("max_payload_bytes"),
            default=131_072,
            lower=4_096,
            upper=2_097_152,
        ),
        max_output_bytes=_clamp_int(
            isolation.get("max_output_bytes"),
            default=262_144,
            lower=4_096,
            upper=4_194_304,
        ),
        max_memory_mb=_clamp_int(isolation.get("max_memory_mb"), default=256, lower=64, upper=2_048),
        cpu_time_seconds=_clamp_int(isolation.get("cpu_time_seconds"), default=20, lower=1, upper=120),
        max_failure_streak=_clamp_int(isolation.get("max_failure_streak"), default=3, lower=1, upper=10),
        cooldown_seconds=_clamp_float(isolation.get("cooldown_seconds"), default=30.0, lower=1.0, upper=300.0),
        stale_reap_grace_seconds=_clamp_float(
            isolation.get("stale_reap_grace_seconds"),
            default=90.0,
            lower=10.0,
            upper=1_800.0,
        ),
    )


def validate_plugin_manifest(
    manifest: Mapping[str, Any],
    *,
    manifest_path: Path,
) -> PluginManifestValidationResult:
    """
    Validate plugin manifest with schema + allowlist + signature checks.

    Rejections are hard-fail for isolated plugin registration.
    """
    default_limits = PluginWorkerLimits()
    payload: Dict[str, Any] = dict(manifest) if isinstance(manifest, Mapping) else {}
    if not payload:
        return PluginManifestValidationResult(False, "invalid_manifest_payload", {}, default_limits)

    if not _has_only_keys(payload, allowed=_ALLOWED_TOP_LEVEL_KEYS):
        unknown_keys = sorted([str(key) for key in payload.keys() if str(key) not in _ALLOWED_TOP_LEVEL_KEYS])
        return PluginManifestValidationResult(
            False,
            f"schema_violation:unknown_top_level_keys:{','.join(unknown_keys)}",
            {},
            default_limits,
        )

    name = str(payload.get("name") or "").strip()
    display_name = str(payload.get("displayName") or "").strip()
    if not name or not _SAFE_NAME_RE.fullmatch(name):
        return PluginManifestValidationResult(False, "schema_violation:invalid_name", {}, default_limits)
    if not display_name:
        return PluginManifestValidationResult(False, "schema_violation:missing_display_name", {}, default_limits)

    entry_point = _as_dict(payload.get("entryPoint"))
    if not _has_only_keys(entry_point, allowed=_ALLOWED_ENTRYPOINT_KEYS):
        return PluginManifestValidationResult(False, "schema_violation:entrypoint_unknown_keys", {}, default_limits)
    module_name = str(entry_point.get("module") or "").strip()
    class_name = str(entry_point.get("class") or "").strip()
    if not module_name or not _SAFE_MODULE_RE.fullmatch(module_name):
        return PluginManifestValidationResult(False, "schema_violation:invalid_entrypoint_module", {}, default_limits)
    if not class_name or not _SAFE_CLASS_RE.fullmatch(class_name):
        return PluginManifestValidationResult(False, "schema_violation:invalid_entrypoint_class", {}, default_limits)

    capabilities = _as_dict(payload.get("capabilities"))
    if not _has_only_keys(capabilities, allowed=_ALLOWED_CAPABILITIES_KEYS):
        return PluginManifestValidationResult(False, "schema_violation:capabilities_unknown_keys", {}, default_limits)
    invocation_commands = capabilities.get("invocationCommands")
    if not isinstance(invocation_commands, list) or not invocation_commands:
        return PluginManifestValidationResult(False, "schema_violation:missing_invocation_commands", {}, default_limits)
    if len(invocation_commands) > 64:
        return PluginManifestValidationResult(False, "schema_violation:too_many_invocation_commands", {}, default_limits)
    for item in invocation_commands:
        if not isinstance(item, MutableMapping):
            return PluginManifestValidationResult(False, "schema_violation:invalid_invocation_command_item", {}, default_limits)
        if not _has_only_keys(item, allowed=_ALLOWED_INVOCATION_KEYS):
            return PluginManifestValidationResult(
                False,
                "schema_violation:invocation_command_unknown_keys",
                {},
                default_limits,
            )
        command = str(item.get("command") or "").strip()
        if not command or not _SAFE_COMMAND_RE.fullmatch(command):
            return PluginManifestValidationResult(False, "schema_violation:invalid_invocation_command", {}, default_limits)

    isolation = _as_dict(payload.get("isolation"))
    if not _has_only_keys(isolation, allowed=_ALLOWED_ISOLATION_KEYS):
        return PluginManifestValidationResult(False, "schema_violation:isolation_unknown_keys", {}, default_limits)
    mode = str(isolation.get("mode") or "").strip().lower()
    if mode not in {"worker", "process", "isolated_worker"}:
        return PluginManifestValidationResult(False, "schema_violation:isolation_mode_required", {}, default_limits)
    worker_limits = _normalize_worker_limits(isolation)

    policy = _as_dict(payload.get("policy"))
    if not _has_only_keys(policy, allowed=_ALLOWED_POLICY_KEYS):
        return PluginManifestValidationResult(False, "schema_violation:policy_unknown_keys", {}, default_limits)
    scopes = _normalize_scopes(policy)
    if not scopes:
        return PluginManifestValidationResult(False, "policy_violation:missing_scopes", {}, default_limits)

    lowered_scopes = {scope.strip().lower() for scope in scopes if scope.strip()}
    if lowered_scopes & _FORBIDDEN_SCOPES:
        forbidden = ",".join(sorted(lowered_scopes & _FORBIDDEN_SCOPES))
        return PluginManifestValidationResult(False, f"policy_violation:forbidden_scope:{forbidden}", {}, default_limits)
    allowed_scopes = {scope.strip().lower() for scope in load_allowed_scopes()}
    if any(scope not in allowed_scopes for scope in lowered_scopes):
        rejected = ",".join(sorted(scope for scope in lowered_scopes if scope not in allowed_scopes))
        return PluginManifestValidationResult(False, f"policy_violation:scope_not_allowlisted:{rejected}", {}, default_limits)

    allowlist = load_plugin_allowlist()
    if not allowlist:
        return PluginManifestValidationResult(False, "trust_violation:plugin_allowlist_empty", {}, default_limits)
    if name not in allowlist:
        return PluginManifestValidationResult(False, f"trust_violation:not_in_allowlist:{name}", {}, default_limits)

    signature = _as_dict(payload.get("signature"))
    if not _has_only_keys(signature, allowed=_ALLOWED_SIGNATURE_KEYS):
        return PluginManifestValidationResult(False, "trust_violation:signature_unknown_keys", {}, default_limits)
    algorithm = str(signature.get("algorithm") or "").strip().lower()
    key_id = str(signature.get("key_id") or "").strip()
    signature_value = str(signature.get("value") or "").strip().lower()
    if algorithm != "hmac-sha256":
        return PluginManifestValidationResult(False, "trust_violation:signature_algorithm_unsupported", {}, default_limits)
    if not key_id:
        return PluginManifestValidationResult(False, "trust_violation:signature_key_id_missing", {}, default_limits)
    if not re.fullmatch(r"[0-9a-f]{64}", signature_value):
        return PluginManifestValidationResult(False, "trust_violation:signature_value_invalid", {}, default_limits)

    signing_keys = load_plugin_signing_keys()
    if not signing_keys:
        return PluginManifestValidationResult(False, "trust_violation:signing_keys_missing", {}, default_limits)
    secret = signing_keys.get(key_id)
    if not secret:
        return PluginManifestValidationResult(False, f"trust_violation:signing_key_not_found:{key_id}", {}, default_limits)

    expected = compute_manifest_signature(payload, secret=secret)
    if not hmac.compare_digest(expected, signature_value):
        return PluginManifestValidationResult(False, "trust_violation:signature_mismatch", {}, default_limits)

    normalized = dict(payload)
    normalized["policy"] = {"scopes": sorted(lowered_scopes)}
    normalized["isolation"] = {
        "mode": "isolated_worker",
        "timeout_seconds": worker_limits.timeout_seconds,
        "max_payload_bytes": worker_limits.max_payload_bytes,
        "max_output_bytes": worker_limits.max_output_bytes,
        "max_memory_mb": worker_limits.max_memory_mb,
        "cpu_time_seconds": worker_limits.cpu_time_seconds,
        "max_failure_streak": worker_limits.max_failure_streak,
        "cooldown_seconds": worker_limits.cooldown_seconds,
        "stale_reap_grace_seconds": worker_limits.stale_reap_grace_seconds,
    }
    normalized["_manifest_path"] = str(manifest_path).replace("\\", "/")
    normalized["_trust_policy"] = {
        "validated": True,
        "allowlisted": True,
        "signature_verified": True,
        "signature_algorithm": algorithm,
        "signature_key_id": key_id,
    }
    normalized["_worker_limits"] = {
        "timeout_seconds": worker_limits.timeout_seconds,
        "max_payload_bytes": worker_limits.max_payload_bytes,
        "max_output_bytes": worker_limits.max_output_bytes,
        "max_memory_mb": worker_limits.max_memory_mb,
        "cpu_time_seconds": worker_limits.cpu_time_seconds,
        "max_failure_streak": worker_limits.max_failure_streak,
        "cooldown_seconds": worker_limits.cooldown_seconds,
        "stale_reap_grace_seconds": worker_limits.stale_reap_grace_seconds,
    }

    return PluginManifestValidationResult(True, "", normalized, worker_limits)


__all__ = [
    "PluginManifestValidationResult",
    "PluginWorkerLimits",
    "compute_manifest_signature",
    "load_allowed_scopes",
    "load_plugin_allowlist",
    "load_plugin_signing_keys",
    "validate_plugin_manifest",
]
