"""Parse loosely formatted JSON tool calls from model text outputs."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List


def _extract_brace_objects(text: str) -> List[str]:
    blocks: List[str] = []
    depth = 0
    start = -1
    in_string = False
    escape = False

    for idx, ch in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            continue

        if ch == "{":
            if depth == 0:
                start = idx
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start >= 0:
                    blocks.append(text[start : idx + 1])
                    start = -1

    return blocks


def parse_non_standard_json(text: str) -> List[Dict[str, Any]]:
    tool_calls: List[Dict[str, Any]] = []
    if not text:
        return tool_calls

    normalized = normalize_json_format(text)

    # 1) Try parsing full payload as JSON list/dict first.
    try:
        top = json.loads(normalized)
        if isinstance(top, dict) and validate_tool_call(top):
            tool_calls.append(top)
        elif isinstance(top, list):
            for item in top:
                if isinstance(item, dict) and validate_tool_call(item):
                    tool_calls.append(item)
    except Exception:
        pass

    # 2) Parse JSON code fences.
    for m in re.finditer(r"```(?:json)?\s*([\s\S]*?)```", normalized, flags=re.IGNORECASE):
        payload = m.group(1).strip()
        if not payload:
            continue
        try:
            parsed = json.loads(payload)
            if isinstance(parsed, dict) and validate_tool_call(parsed):
                tool_calls.append(parsed)
            elif isinstance(parsed, list):
                for item in parsed:
                    if isinstance(item, dict) and validate_tool_call(item):
                        tool_calls.append(item)
        except Exception:
            pass

    # 3) Fallback: scan balanced JSON object blocks.
    for block in _extract_brace_objects(normalized):
        try:
            parsed = json.loads(block)
            if isinstance(parsed, dict) and validate_tool_call(parsed):
                tool_calls.append(parsed)
        except Exception:
            continue

    # Keep order while deduplicating equivalent dict payloads.
    deduped: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for call in tool_calls:
        key = json.dumps(call, ensure_ascii=False, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(call)

    return deduped


def validate_tool_call(tool_call: Dict[str, Any]) -> bool:
    if not isinstance(tool_call, dict):
        return False

    agent_type = str(tool_call.get("agentType") or "").strip()
    if not agent_type:
        return False

    lower_agent_type = agent_type.lower()
    if lower_agent_type == "native":
        return bool(tool_call.get("tool_name") or tool_call.get("tool"))
    if lower_agent_type == "mcp":
        return bool(tool_call.get("tool_name") or tool_call.get("service_name"))
    if lower_agent_type == "live2d":
        return True

    # Unknown agent types are retained to keep parser forward-compatible.
    return True


def extract_json_blocks(text: str) -> List[str]:
    normalized = normalize_json_format(text)
    blocks = _extract_brace_objects(normalized)
    blocks.extend(re.findall(r"```(?:json)?\s*([\s\S]*?)```", normalized, flags=re.IGNORECASE))
    return [b for b in blocks if b]


def normalize_json_format(text: str) -> str:
    return (text or "").replace("｛", "{").replace("｝", "}")
