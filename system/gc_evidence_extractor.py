"""
Key troubleshooting evidence extraction for GC/summary reuse.

NGA-WS15-001:
- Extract trace_id / error_code / stack token / path / memory address evidence.
- Provide reusable module-level APIs for downstream fetch/summary flows.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable

_MAX_SCAN_CHARS = 200_000
_DEFAULT_MAX_ITEMS = 8
_DEFAULT_MAX_HINTS = 16

_TRACE_KEY_RE = re.compile(
    r'(?i)\btrace[_-]?id\b\s*[:=]\s*["\']?([A-Za-z0-9._:-]{4,128})'
)
_TRACE_INLINE_RE = re.compile(r"(?i)\btrace[-_][A-Za-z0-9._:-]{4,128}\b")

_ERROR_CODE_KEY_RE = re.compile(
    r'(?i)\berror[_-]?code\b\s*[:=]\s*["\']?([A-Za-z0-9._-]{1,64})'
)
_ERROR_TOKEN_RE = re.compile(r"\bERR_[A-Z0-9_]{2,64}\b")
_HTTP_STATUS_RE = re.compile(r"(?i)\bHTTP\s*([45]\d{2})\b")

_STACK_AT_RE = re.compile(r"(?m)^\s*at\s+([A-Za-z_][\w$<>\.\-/:]*)")
_STACK_PY_RE = re.compile(
    r'(?m)^\s*File\s+["\'][^"\']+["\']\s*,\s*line\s+\d+\s*,\s*in\s+([A-Za-z_][A-Za-z0-9_]*)'
)

_WINDOWS_PATH_RE = re.compile(r"(?i)\b(?:[A-Z]:\\|\\\\)[^\s:\"*?<>|]+(?:\\[^\s:\"*?<>|]+)*")
_UNIX_PATH_RE = re.compile(r"(?<![A-Za-z0-9])/((?:[^/\s\"'<>:]+/)*[^/\s\"'<>:]+(?::\d+){0,2})")

_HEX_ADDR_RE = re.compile(r"\b0x[0-9a-fA-F]{6,18}\b")
_HEX_CONTEXT_RE = re.compile(r"(?i)\b(?:addr(?:ess)?|ptr|pointer|rip|eip)\b\s*[:=]\s*([0-9a-fA-F]{8,18})\b")

_TRACE_KEYS = {"trace_id", "traceid", "trace"}
_ERROR_KEYS = {"error_code", "errorcode", "errno", "status_code", "statuscode"}
_STACK_KEYS = {"stack", "stack_trace", "stacktrace", "traceback", "call_stack", "callstack"}
_PATH_KEYS = {"path", "file_path", "filepath", "file", "filename", "source_path", "log_path"}
_ADDRESS_KEYS = {"address", "memory_address", "addr", "pointer", "ptr", "hex_address"}


@dataclass
class GCEvidence:
    """Normalized key evidence fields for troubleshooting recall."""

    trace_ids: list[str] = field(default_factory=list)
    error_codes: list[str] = field(default_factory=list)
    stack_tokens: list[str] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)
    hex_addresses: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "trace_ids": list(self.trace_ids),
            "error_codes": list(self.error_codes),
            "stack_tokens": list(self.stack_tokens),
            "paths": list(self.paths),
            "hex_addresses": list(self.hex_addresses),
        }

    def has_any(self) -> bool:
        return any(
            [
                self.trace_ids,
                self.error_codes,
                self.stack_tokens,
                self.paths,
                self.hex_addresses,
            ]
        )


def extract_gc_evidence(
    payload: str,
    content_type: str = "text/plain",
    *,
    max_items_per_field: int = _DEFAULT_MAX_ITEMS,
) -> GCEvidence:
    """
    Extract key troubleshooting evidence from raw text/JSON payload.

    Args:
        payload: raw output text or JSON string
        content_type: MIME type hint
        max_items_per_field: cap per evidence bucket
    """
    text = (payload or "")[:_MAX_SCAN_CHARS]
    evidence = GCEvidence()

    normalized_type = (content_type or "").strip().lower()
    json_obj: Any = None
    if "json" in normalized_type:
        json_obj = _safe_json_loads(text)
    elif text.lstrip().startswith(("{", "[")):
        json_obj = _safe_json_loads(text)

    if json_obj is not None:
        _extract_from_json(json_obj, evidence, max_items_per_field)

    _extract_from_text(text, evidence, max_items_per_field)
    return evidence


def build_gc_fetch_hints(
    evidence: GCEvidence,
    content_type: str = "text/plain",
    *,
    max_hints: int = _DEFAULT_MAX_HINTS,
) -> list[str]:
    """Build fetch hints using evidence and content type."""
    normalized_type = (content_type or "").strip().lower()
    hints: list[str] = []
    if normalized_type == "application/json":
        hints.extend(
            [
                "jsonpath:$..error_code",
                "jsonpath:$..trace_id",
                "jsonpath:$..message",
                "jsonpath:$..stack",
                "jsonpath:$..path",
                "jsonpath:$..memory_address",
            ]
        )
    else:
        hints.extend(["line_range:1-100", "grep:ERROR"])

    hints.extend(f"grep:{value}" for value in evidence.trace_ids[:2])
    hints.extend(f"grep:{value}" for value in evidence.error_codes[:2])
    hints.extend(f"grep:{value}" for value in evidence.stack_tokens[:2])
    hints.extend(f"grep:{value}" for value in evidence.paths[:2])
    hints.extend(f"grep:{value}" for value in evidence.hex_addresses[:2])

    return _dedupe_and_limit(hints, max_hints)


def _extract_from_json(node: Any, evidence: GCEvidence, max_items: int) -> None:
    stack: list[Any] = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            for raw_key, value in current.items():
                key = str(raw_key).strip().lower()
                _extract_keyed_value(key, value, evidence, max_items)

                if isinstance(value, (dict, list)):
                    stack.append(value)
                elif isinstance(value, str):
                    _extract_from_text(value, evidence, max_items)
        elif isinstance(current, list):
            for value in current:
                if isinstance(value, (dict, list)):
                    stack.append(value)
                elif isinstance(value, str):
                    _extract_from_text(value, evidence, max_items)


def _extract_keyed_value(key: str, value: Any, evidence: GCEvidence, max_items: int) -> None:
    if value is None:
        return
    if key in _TRACE_KEYS:
        _add_value(evidence.trace_ids, str(value), _normalize_trace, max_items)
    if key in _ERROR_KEYS:
        _add_value(evidence.error_codes, str(value), _normalize_error_code, max_items)
    if key in _STACK_KEYS and isinstance(value, str):
        _extract_from_text(value, evidence, max_items)
    if key in _PATH_KEYS and isinstance(value, str):
        _add_value(evidence.paths, value, _normalize_path, max_items)
    if key in _ADDRESS_KEYS:
        _add_value(evidence.hex_addresses, str(value), _normalize_hex_address, max_items)

    if "path" in key and isinstance(value, str):
        _add_value(evidence.paths, value, _normalize_path, max_items)
    if "trace" in key and isinstance(value, str):
        _add_value(evidence.trace_ids, value, _normalize_trace, max_items)


def _extract_from_text(text: str, evidence: GCEvidence, max_items: int) -> None:
    for match in _TRACE_KEY_RE.finditer(text):
        _add_value(evidence.trace_ids, match.group(1), _normalize_trace, max_items)
    for match in _TRACE_INLINE_RE.finditer(text):
        _add_value(evidence.trace_ids, match.group(0), _normalize_trace, max_items)

    for match in _ERROR_CODE_KEY_RE.finditer(text):
        _add_value(evidence.error_codes, match.group(1), _normalize_error_code, max_items)
    for match in _ERROR_TOKEN_RE.finditer(text):
        _add_value(evidence.error_codes, match.group(0), _normalize_error_code, max_items)
    for match in _HTTP_STATUS_RE.finditer(text):
        _add_value(evidence.error_codes, match.group(1), _normalize_error_code, max_items)

    for match in _STACK_AT_RE.finditer(text):
        _add_value(evidence.stack_tokens, match.group(1), _normalize_stack_token, max_items)
    for match in _STACK_PY_RE.finditer(text):
        _add_value(evidence.stack_tokens, match.group(1), _normalize_stack_token, max_items)

    for match in _WINDOWS_PATH_RE.finditer(text):
        _add_value(evidence.paths, match.group(0), _normalize_path, max_items)
    for match in _UNIX_PATH_RE.finditer(text):
        _add_value(evidence.paths, "/" + match.group(1), _normalize_path, max_items)

    for match in _HEX_ADDR_RE.finditer(text):
        _add_value(evidence.hex_addresses, match.group(0), _normalize_hex_address, max_items)
    for match in _HEX_CONTEXT_RE.finditer(text):
        _add_value(evidence.hex_addresses, match.group(1), _normalize_hex_address, max_items)


def _add_value(
    bucket: list[str],
    raw_value: str,
    normalizer: Callable[[str], str | None],
    max_items: int,
) -> None:
    if len(bucket) >= max_items:
        return
    normalized = normalizer(raw_value)
    if not normalized:
        return
    normalized_key = normalized.lower()
    if any(existing.lower() == normalized_key for existing in bucket):
        return
    bucket.append(normalized)


def _normalize_trace(value: str) -> str | None:
    token = _sanitize(value)
    if len(token) < 4 or len(token) > 128:
        return None
    return token


def _normalize_error_code(value: str) -> str | None:
    token = _sanitize(value)
    if not token or len(token) > 64:
        return None
    return token


def _normalize_stack_token(value: str) -> str | None:
    token = _sanitize(value)
    if len(token) < 2 or len(token) > 128:
        return None
    return token


def _normalize_path(value: str) -> str | None:
    token = _sanitize(value)
    if not token:
        return None
    token = re.sub(r":\d+(?::\d+)?$", "", token)
    if token.startswith("/") or re.match(r"(?i)^(?:[A-Z]:\\|\\\\)", token):
        return token
    return None


def _normalize_hex_address(value: str) -> str | None:
    token = _sanitize(value).lower()
    if not token:
        return None
    if token.startswith("0x") and re.fullmatch(r"0x[0-9a-f]{6,18}", token):
        return token
    if re.fullmatch(r"[0-9a-f]{8,18}", token):
        return f"0x{token}"
    return None


def _sanitize(value: str) -> str:
    token = str(value).strip()
    token = token.strip(" \t\r\n\"'`[]{}(),;")
    return token


def _safe_json_loads(text: str) -> Any:
    try:
        return json.loads(text)
    except Exception:
        return None


def _dedupe_and_limit(values: list[str], limit: int) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        output.append(value)
        if len(output) >= limit:
            break
    return output


__all__ = ["GCEvidence", "extract_gc_evidence", "build_gc_fetch_hints"]
