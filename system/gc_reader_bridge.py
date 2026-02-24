"""GC reader bridge for automatic artifact readback follow-up."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

_NONE_MARKERS = {"", "(none)", "none", "null", "nil", "n/a", "undefined"}
_TRUTHY_MARKERS = {"1", "true", "yes", "on"}
_TAG_LINE_RE = re.compile(r"^\[([A-Za-z0-9_]+)\](?:\s*(.*))?$")
_LINE_RANGE_RE = re.compile(r"^\s*(\d+)\s*-\s*(\d+)\s*$")
_READBACK_MARKERS = (
    "use artifact_reader to access full content",
    "[truncated]",
    "...[truncated]",
)


@dataclass(frozen=True)
class GCReaderFollowupPlan:
    """Planned auto-readback action for one loop round."""

    call: Optional[Dict[str, Any]]
    suggestion: str
    reason: str
    source_index: int = -1


@dataclass(frozen=True)
class _ReaderCandidate:
    source_index: int
    status: str
    ref: str
    fetch_hints: List[str]
    truncated: bool
    preview_insufficient: bool
    reason: str


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _clean_ref(value: Any) -> str:
    text = _as_text(value)
    if text.lower() in _NONE_MARKERS:
        return ""
    return text


def _normalize_fetch_hints(value: Any) -> List[str]:
    raw_items: List[str]
    if isinstance(value, list):
        raw_items = [_as_text(item) for item in value]
    else:
        text = _as_text(value)
        raw_items = [seg.strip() for seg in text.split(",")] if text else []

    hints: List[str] = []
    seen = set()
    for item in raw_items:
        lowered = item.lower()
        if not item or lowered in _NONE_MARKERS:
            continue
        if item in seen:
            continue
        seen.add(item)
        hints.append(item)
    return hints


def _parse_tagged_sections(result_text: str) -> Dict[str, str]:
    sections: Dict[str, str] = {}
    current_tag: Optional[str] = None
    current_lines: List[str] = []

    for line in (result_text or "").splitlines():
        stripped = line.strip()
        matched = _TAG_LINE_RE.match(stripped)
        if matched:
            if current_tag is not None:
                sections[current_tag] = "\n".join(current_lines).strip()
            current_tag = matched.group(1).strip().lower()
            inline_value = _as_text(matched.group(2))
            current_lines = [inline_value] if inline_value else []
            continue

        if current_tag is not None:
            current_lines.append(line.rstrip())

    if current_tag is not None:
        sections[current_tag] = "\n".join(current_lines).strip()
    return sections


def _parse_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    text = _as_text(value).lower()
    if not text:
        return default
    return text in _TRUTHY_MARKERS


def _is_preview_insufficient(status: str, truncated: bool, result_text: str) -> tuple[bool, str]:
    if truncated:
        return True, "truncated_preview"

    # Error branches should get one focused readback to locate root cause.
    if status.lower() == "error":
        return True, "error_requires_focus"

    lowered = (result_text or "").lower()
    if any(marker in lowered for marker in _READBACK_MARKERS):
        return True, "readback_marker"

    return False, "preview_sufficient"


def _build_reader_kwargs(fetch_hints: Sequence[str]) -> Dict[str, Any]:
    normalized = _normalize_fetch_hints(fetch_hints)
    if normalized:
        for hint in normalized:
            mode, sep, payload = hint.partition(":")
            if mode.strip().lower() != "line_range" or not sep:
                continue
            matched = _LINE_RANGE_RE.match(payload.strip())
            if not matched:
                continue
            start = int(matched.group(1))
            end = int(matched.group(2))
            if start <= end:
                return {"mode": "line_range", "start_line": start, "end_line": end}

        for hint in normalized:
            mode, sep, payload = hint.partition(":")
            if mode.strip().lower() != "grep" or not sep:
                continue
            query = payload.strip()
            if query:
                return {"mode": "grep", "query": query, "max_results": 80}

        for hint in normalized:
            mode, sep, payload = hint.partition(":")
            if mode.strip().lower() != "jsonpath" or not sep:
                continue
            query = payload.strip()
            if query:
                return {"mode": "jsonpath", "query": query, "max_results": 80}

    return {"mode": "preview", "max_chars": 3200}


def _candidate_score(candidate: _ReaderCandidate) -> int:
    score = 0
    if candidate.status.lower() == "error":
        score += 100
    if candidate.truncated:
        score += 50
    if any(h.lower().startswith("line_range:") for h in candidate.fetch_hints):
        score += 30
    elif any(h.lower().startswith("grep:") for h in candidate.fetch_hints):
        score += 20
    elif any(h.lower().startswith("jsonpath:") for h in candidate.fetch_hints):
        score += 10
    score += max(0, 20 - candidate.source_index)
    return score


def _extract_reader_candidate(result: Dict[str, Any], source_index: int) -> Optional[_ReaderCandidate]:
    status = _as_text(result.get("status")) or "unknown"
    result_payload = result.get("result")
    result_text = result_payload if isinstance(result_payload, str) else ""
    tagged = _parse_tagged_sections(result_text)

    candidates: List[Dict[str, Any]] = [result]
    if isinstance(result_payload, dict):
        candidates.append(result_payload)

    forensic_ref = ""
    raw_ref = ""
    fetch_hints: List[str] = []
    truncated: Optional[bool] = None

    for source in candidates:
        if not forensic_ref:
            forensic_ref = _clean_ref(source.get("forensic_artifact_ref"))
        if not raw_ref:
            raw_ref = _clean_ref(source.get("raw_result_ref"))
        if not fetch_hints:
            fetch_hints = _normalize_fetch_hints(source.get("fetch_hints"))
        if truncated is None and source.get("truncated") is not None:
            truncated = _parse_bool(source.get("truncated"), default=False)

    if not forensic_ref:
        forensic_ref = _clean_ref(tagged.get("forensic_artifact_ref"))
    if not raw_ref:
        raw_ref = _clean_ref(tagged.get("raw_result_ref"))
    if not fetch_hints:
        fetch_hints = _normalize_fetch_hints(tagged.get("fetch_hints"))
    if truncated is None:
        truncated = _parse_bool(tagged.get("truncated"), default=False)

    ref = forensic_ref or raw_ref
    if not ref:
        return None

    preview_insufficient, reason = _is_preview_insufficient(status, truncated, result_text)
    return _ReaderCandidate(
        source_index=source_index,
        status=status,
        ref=ref,
        fetch_hints=fetch_hints,
        truncated=truncated,
        preview_insufficient=preview_insufficient,
        reason=reason,
    )


def render_artifact_reader_call(call: Dict[str, Any]) -> str:
    """Render artifact_reader call as a compact suggestion string."""
    ref = _clean_ref(call.get("forensic_artifact_ref") or call.get("raw_result_ref") or call.get("artifact_id"))
    mode = _as_text(call.get("mode")).lower() or "preview"
    if not ref:
        return "artifact_reader(mode=\"preview\")"

    quoted_ref = json.dumps(ref, ensure_ascii=False)
    if mode == "line_range":
        start = int(call.get("start_line", 1))
        end = int(call.get("end_line", start))
        return (
            "artifact_reader("
            f"forensic_artifact_ref={quoted_ref}, mode=\"line_range\", start_line={start}, end_line={end}"
            ")"
        )
    if mode == "grep":
        query = _as_text(call.get("query") or call.get("pattern") or call.get("keyword"))
        return (
            "artifact_reader("
            f"forensic_artifact_ref={quoted_ref}, mode=\"grep\", query={json.dumps(query, ensure_ascii=False)}"
            ")"
        )
    if mode == "jsonpath":
        query = _as_text(call.get("query") or call.get("jsonpath"))
        return (
            "artifact_reader("
            f"forensic_artifact_ref={quoted_ref}, mode=\"jsonpath\", query={json.dumps(query, ensure_ascii=False)}"
            ")"
        )

    return f"artifact_reader(forensic_artifact_ref={quoted_ref}, mode=\"preview\")"


def build_gc_reader_followup_plan(
    results: Sequence[Dict[str, Any]],
    *,
    round_num: int = 0,
    max_calls_per_round: int = 1,
) -> GCReaderFollowupPlan:
    """Plan one automatic artifact_reader follow-up call for the current round."""
    if max_calls_per_round <= 0:
        return GCReaderFollowupPlan(call=None, suggestion="", reason="budget_exhausted")
    if not results:
        return GCReaderFollowupPlan(call=None, suggestion="", reason="no_results")

    parsed_candidates: List[_ReaderCandidate] = []
    for idx, item in enumerate(results, 1):
        if not isinstance(item, dict):
            continue
        candidate = _extract_reader_candidate(item, source_index=idx)
        if candidate is not None:
            parsed_candidates.append(candidate)

    if not parsed_candidates:
        return GCReaderFollowupPlan(call=None, suggestion="", reason="no_forensic_ref")

    actionable = [candidate for candidate in parsed_candidates if candidate.preview_insufficient]
    if not actionable:
        fallback = parsed_candidates[0]
        fallback_call = {
            "tool_name": "artifact_reader",
            "forensic_artifact_ref": fallback.ref,
            "mode": "preview",
        }
        return GCReaderFollowupPlan(
            call=None,
            suggestion=render_artifact_reader_call(fallback_call),
            reason="preview_sufficient",
            source_index=fallback.source_index,
        )

    target = max(actionable, key=_candidate_score)
    reader_kwargs = _build_reader_kwargs(target.fetch_hints)
    call: Dict[str, Any] = {
        "agentType": "native",
        "tool_name": "artifact_reader",
        "forensic_artifact_ref": target.ref,
        "_gc_reader_bridge": True,
        **reader_kwargs,
    }
    if round_num > 0:
        call["_tool_call_id"] = f"gc_reader_bridge_r{round_num}_{target.source_index}"

    return GCReaderFollowupPlan(
        call=call,
        suggestion=render_artifact_reader_call(call),
        reason=target.reason,
        source_index=target.source_index,
    )


__all__ = [
    "GCReaderFollowupPlan",
    "build_gc_reader_followup_plan",
    "render_artifact_reader_call",
]
