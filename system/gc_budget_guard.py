"""GC/memory injection budget guard with repeat-failure damping."""

from __future__ import annotations

import hashlib
import json
import re
from collections import deque
from dataclasses import dataclass
from typing import Any, Deque, Dict, List, Optional

_ARTIFACT_REF_RE = re.compile(r"\bartifact_[A-Za-z0-9_\-]+\b")
_WS_RE = re.compile(r"\s+")
_TRACE_ID_RE = re.compile(r"\btrace_[A-Za-z0-9_\-]{6,}\b")
_HEX_ID_RE = re.compile(r"\b0x[0-9a-fA-F]{6,}\b")


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _normalize_error_text(value: Any, *, limit: int = 240) -> str:
    if isinstance(value, str):
        raw = value
    else:
        try:
            raw = json.dumps(value, ensure_ascii=False, sort_keys=True)
        except Exception:
            raw = str(value)
    text = _WS_RE.sub(" ", raw).strip().lower()
    if not text:
        return ""
    text = _TRACE_ID_RE.sub("trace_*", text)
    text = _HEX_ID_RE.sub("0x*", text)
    if len(text) > limit:
        text = text[:limit]
    return text


def _extract_artifact_ref(result: Dict[str, Any]) -> str:
    call = result.get("tool_call")
    if isinstance(call, dict):
        for key in ("forensic_artifact_ref", "raw_result_ref", "artifact_id"):
            ref = _as_text(call.get(key))
            if ref:
                return ref

    for key in ("forensic_artifact_ref", "raw_result_ref", "artifact_id"):
        ref = _as_text(result.get(key))
        if ref:
            return ref

    result_text = _as_text(result.get("result"))
    matched = _ARTIFACT_REF_RE.search(result_text)
    return matched.group(0) if matched else ""


def _extract_hint(result: Dict[str, Any]) -> str:
    call = result.get("tool_call")
    if not isinstance(call, dict):
        return ""

    mode = _as_text(call.get("mode")).lower()
    query = _as_text(call.get("query") or call.get("jsonpath") or call.get("pattern") or call.get("keyword"))
    if mode and query:
        return f"{mode}:{query[:80]}"
    if mode:
        return mode
    if query:
        return query[:80]

    raw_hints = call.get("fetch_hints")
    if isinstance(raw_hints, list):
        for item in raw_hints:
            text = _as_text(item)
            if text:
                return text[:80]
    return ""


def _tool_name(result: Dict[str, Any]) -> str:
    name = _as_text(result.get("tool_name")).lower()
    if name:
        return name
    call = result.get("tool_call")
    if isinstance(call, dict):
        return _as_text(call.get("tool_name")).lower()
    return ""


def _is_gc_related_result(result: Dict[str, Any]) -> bool:
    name = _tool_name(result)
    if name == "artifact_reader":
        return True

    call = result.get("tool_call")
    if isinstance(call, dict):
        for key in ("forensic_artifact_ref", "raw_result_ref", "artifact_id", "fetch_hints"):
            if call.get(key):
                return True

    for key in ("forensic_artifact_ref", "raw_result_ref", "artifact_id", "fetch_hints"):
        if result.get(key):
            return True

    result_text = _as_text(result.get("result")).lower()
    if "[forensic_artifact_ref]" in result_text:
        return True
    if "artifact_reader(" in result_text:
        return True
    return False


def _is_non_progress_gc_success(result: Dict[str, Any]) -> bool:
    service_name = _as_text(result.get("service_name")).lower()
    name = _tool_name(result)
    if service_name == "gc_reader_bridge":
        return True
    if name == "artifact_reader_suggestion":
        return True

    result_text = _as_text(result.get("result")).lower()
    if "[gc_reader_bridge]" in result_text and "降级为建议" in result_text:
        return True
    return False


@dataclass(frozen=True)
class GCBudgetGuardConfig:
    repeat_threshold: int = 3
    window_size: int = 6

    def normalized(self) -> "GCBudgetGuardConfig":
        threshold = max(2, min(10, int(self.repeat_threshold)))
        window_size = max(threshold, min(30, int(self.window_size)))
        return GCBudgetGuardConfig(repeat_threshold=threshold, window_size=window_size)


@dataclass(frozen=True)
class GCBudgetGuardSignal:
    guard_hit: bool
    stop_reason: str
    fingerprint: str
    repeat_count: int
    threshold: int
    window_size: int
    artifact_ref: str
    hint: str
    error_excerpt: str
    gc_error_total: int
    gc_success_total: int
    gc_guard_hits: int

    def to_payload(self) -> Dict[str, Any]:
        return {
            "guard_hit": self.guard_hit,
            "stop_reason": self.stop_reason,
            "fingerprint": self.fingerprint,
            "repeat_count": self.repeat_count,
            "threshold": self.threshold,
            "window_size": self.window_size,
            "artifact_ref": self.artifact_ref,
            "hint": self.hint,
            "error_excerpt": self.error_excerpt,
            "gc_error_total": self.gc_error_total,
            "gc_success_total": self.gc_success_total,
            "gc_guard_hits": self.gc_guard_hits,
        }


class GCBudgetGuard:
    """Detect short-window repeated GC failures and emit damping signal."""

    def __init__(self, config: Optional[GCBudgetGuardConfig] = None):
        self.config = (config or GCBudgetGuardConfig()).normalized()
        self._recent_fingerprints: Deque[str] = deque(maxlen=self.config.window_size)
        self._last_fingerprint = ""
        self._repeat_count = 0
        self._gc_error_total = 0
        self._gc_success_total = 0
        self._gc_guard_hits = 0

    def snapshot(self) -> Dict[str, int]:
        return {
            "repeat_count": self._repeat_count,
            "gc_error_total": self._gc_error_total,
            "gc_success_total": self._gc_success_total,
            "gc_guard_hits": self._gc_guard_hits,
        }

    def observe_result(self, result: Dict[str, Any]) -> Optional[GCBudgetGuardSignal]:
        if not isinstance(result, dict):
            return None
        if not _is_gc_related_result(result):
            return None

        status = _as_text(result.get("status")).lower()
        if status == "success":
            if _is_non_progress_gc_success(result):
                return None
            self._gc_success_total += 1
            self._last_fingerprint = ""
            self._repeat_count = 0
            return None
        if status != "error":
            return None

        error_excerpt = _normalize_error_text(result.get("result"))
        artifact_ref = _extract_artifact_ref(result)
        hint = _extract_hint(result)
        name = _tool_name(result) or "unknown"
        base = f"{name}|{artifact_ref}|{hint}|{error_excerpt}"
        fingerprint = hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]

        self._gc_error_total += 1
        self._recent_fingerprints.append(fingerprint)
        if fingerprint == self._last_fingerprint:
            self._repeat_count += 1
        else:
            self._last_fingerprint = fingerprint
            self._repeat_count = 1

        guard_hit = self._repeat_count >= self.config.repeat_threshold
        if guard_hit:
            self._gc_guard_hits += 1

        signal = GCBudgetGuardSignal(
            guard_hit=guard_hit,
            stop_reason="gc_budget_guard_hit" if guard_hit else "",
            fingerprint=fingerprint,
            repeat_count=self._repeat_count,
            threshold=self.config.repeat_threshold,
            window_size=self.config.window_size,
            artifact_ref=artifact_ref,
            hint=hint,
            error_excerpt=error_excerpt,
            gc_error_total=self._gc_error_total,
            gc_success_total=self._gc_success_total,
            gc_guard_hits=self._gc_guard_hits,
        )
        result["gc_budget_guard"] = signal.to_payload()
        if guard_hit:
            result["guard_hit"] = True
            result["guard_stop_reason"] = signal.stop_reason
        return signal

    def observe_round(self, results: List[Dict[str, Any]]) -> Optional[GCBudgetGuardSignal]:
        first_hit: Optional[GCBudgetGuardSignal] = None
        for result in results:
            signal = self.observe_result(result)
            if signal and signal.guard_hit and first_hit is None:
                first_hit = signal
        return first_hit


__all__ = [
    "GCBudgetGuardConfig",
    "GCBudgetGuardSignal",
    "GCBudgetGuard",
]
