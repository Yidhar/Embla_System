"""GC memory index card helpers for tool-result injection."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

_NONE_MARKERS = {"", "(none)", "none", "null", "nil", "n/a", "undefined"}
_TAG_LINE_RE = re.compile(r"^\[([A-Za-z0-9_]+)\](?:\s*(.*))?$")


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


def _preview_text(value: str, max_chars: int = 600) -> str:
    text = value.strip()
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars].rstrip()}...(truncated)"


def _normalize_fetch_hints(value: Any) -> List[str]:
    raw_items: List[str]
    if isinstance(value, list):
        raw_items = [_as_text(item) for item in value]
    else:
        text = _as_text(value)
        if not text:
            raw_items = []
        else:
            raw_items = [seg.strip() for seg in text.split(",")]

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


def _build_readback_hint(ref: str, fetch_hints: List[str]) -> str:
    quoted_ref = json.dumps(ref, ensure_ascii=False)
    if not fetch_hints:
        return f"artifact_reader(forensic_artifact_ref={quoted_ref}, mode=\"preview\")"

    first = fetch_hints[0]
    mode, sep, payload = first.partition(":")
    mode = mode.strip().lower()
    payload = payload.strip()
    if not sep or not payload:
        return f"artifact_reader(forensic_artifact_ref={quoted_ref}, mode=\"preview\")"

    if mode == "jsonpath":
        return (
            "artifact_reader("
            f"forensic_artifact_ref={quoted_ref}, mode=\"jsonpath\", query={json.dumps(payload, ensure_ascii=False)}"
            ")"
        )
    if mode == "grep":
        return (
            "artifact_reader("
            f"forensic_artifact_ref={quoted_ref}, mode=\"grep\", query={json.dumps(payload, ensure_ascii=False)}"
            ")"
        )
    if mode == "line_range":
        start, split_ok, end = payload.partition("-")
        if split_ok and start.strip().isdigit() and end.strip().isdigit():
            return (
                "artifact_reader("
                f"forensic_artifact_ref={quoted_ref}, mode=\"line_range\", "
                f"start_line={int(start.strip())}, end_line={int(end.strip())}"
                ")"
            )
    return f"artifact_reader(forensic_artifact_ref={quoted_ref}, mode=\"preview\")"


def build_gc_memory_index_card(result: Dict[str, Any], *, index: int, total: int) -> Optional[str]:
    """Build GC memory index card text when result contains readable artifact refs."""
    service_name = _as_text(result.get("service_name")) or "unknown"
    tool_name = _as_text(result.get("tool_name"))
    status = _as_text(result.get("status")) or "unknown"
    result_payload = result.get("result")
    result_text = result_payload if isinstance(result_payload, str) else ""
    tagged = _parse_tagged_sections(result_text)

    candidates: List[Dict[str, Any]] = [result]
    if isinstance(result_payload, dict):
        candidates.append(result_payload)

    narrative_summary = ""
    forensic_ref = ""
    raw_ref = ""
    fetch_hints: List[str] = []

    for source in candidates:
        if not narrative_summary:
            narrative_summary = _as_text(source.get("narrative_summary")) or _as_text(source.get("display_preview"))
        if not forensic_ref:
            forensic_ref = _clean_ref(source.get("forensic_artifact_ref"))
        if not raw_ref:
            raw_ref = _clean_ref(source.get("raw_result_ref"))
        if not fetch_hints:
            fetch_hints = _normalize_fetch_hints(source.get("fetch_hints"))

    if not narrative_summary:
        narrative_summary = _as_text(tagged.get("narrative_summary")) or _as_text(tagged.get("display_preview"))
    if not forensic_ref:
        forensic_ref = _clean_ref(tagged.get("forensic_artifact_ref"))
    if not raw_ref:
        raw_ref = _clean_ref(tagged.get("raw_result_ref"))
    if not fetch_hints:
        fetch_hints = _normalize_fetch_hints(tagged.get("fetch_hints"))

    ref = forensic_ref or raw_ref
    if not ref:
        return None

    if not narrative_summary:
        narrative_summary = _preview_text(result_text)

    tool_label = service_name
    if tool_name:
        tool_label += f": {tool_name}"

    hint_line = ", ".join(fetch_hints) if fetch_hints else "(none)"
    readback = _build_readback_hint(ref, fetch_hints)
    lines = [
        f"[记忆索引卡片 {index}/{total} - {tool_label} ({status})]",
        f"[tool/status] {tool_label} ({status})",
        "[narrative_summary]",
        narrative_summary if narrative_summary else "(empty)",
        f"[forensic_artifact_ref] {forensic_ref or ref}",
        f"[raw_result_ref] {raw_ref or ref}",
        f"[fetch_hints] {hint_line}",
        f"[ref_readback] {readback}",
    ]
    return "\n".join(lines)


__all__ = ["build_gc_memory_index_card"]
