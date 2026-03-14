"""Tool-profile presets for child agents.

Profiles keep small-model prompts light by injecting only the memory tools
that a specific task class actually needs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional, Sequence

MEMORY_TOOL_ALIASES = {
    "read": "memory_read",
    "write": "memory_write",
    "list": "memory_list",
    "delete": "memory_delete",
    "grep": "memory_grep",
    "search": "memory_search",
    "index": "memory_index",
    "patch": "memory_patch",
    "insert": "memory_insert",
    "append": "memory_append",
    "replace": "memory_replace",
    "deprecate": "memory_deprecate",
    "tag": "memory_tag",
    "link": "memory_link",
}
MEMORY_TOOL_NAMES = set(MEMORY_TOOL_ALIASES.values())
TOOL_PROFILE_PRESETS = {
    "refactor": ["memory_read", "memory_grep", "memory_patch", "memory_tag"],
    "new_doc": ["memory_write", "memory_append", "memory_tag", "memory_link"],
    "bugfix": ["memory_read", "memory_grep", "memory_patch"],
    "review": ["memory_read", "memory_grep", "memory_tag", "memory_deprecate"],
    "cleanup": ["memory_read", "memory_grep", "memory_replace", "memory_delete"],
    "custom": [],
}


@dataclass(frozen=True)
class ToolProfileResolution:
    """Resolved child-agent tool capabilities."""

    profile_name: str
    tool_subset: List[str]
    source: str = ""


def normalize_memory_tool_name(raw_name: str) -> str:
    """Map short aliases like `read` to canonical `memory_read`."""
    text = str(raw_name or "").strip().lower()
    if not text:
        return ""
    return MEMORY_TOOL_ALIASES.get(text, text)


def is_memory_tool_name(raw_name: str) -> bool:
    return normalize_memory_tool_name(raw_name) in MEMORY_TOOL_NAMES


def normalize_tool_subset(tool_names: Optional[Sequence[Any]]) -> List[str]:
    """Normalize a tool list while preserving order and deduplicating."""
    normalized: List[str] = []
    seen: set[str] = set()
    for item in tool_names or []:
        tool_name = normalize_memory_tool_name(str(item or ""))
        if not tool_name or tool_name in seen:
            continue
        seen.add(tool_name)
        normalized.append(tool_name)
    return normalized


def infer_memory_tool_profile(
    task_description: str,
    *,
    files: Optional[Sequence[str]] = None,
    role: str = "dev",
) -> str:
    """Best-effort classifier for L1 memory editing tasks.

    The heuristic is intentionally conservative: it only selects a memory
    profile when the task obviously targets memory/docs/knowledge artifacts.
    """
    role_text = str(role or "").strip().lower()
    if role_text not in {"dev", "review", "expert"}:
        return ""

    normalized_inputs = [str(task_description or "")] + [str(item or "") for item in (files or [])]
    corpus = " ".join(normalized_inputs).lower()
    if not corpus:
        return ""

    memory_path_markers = (
        "memory/",
        "memory\\",
        "episodic/",
        "episodic\\",
        "domain/",
        "domain\\",
        "knowledge/",
        "knowledge\\",
        "knowledge_card",
        "knowledge graph",
        "memory card",
        "l1 memory",
        "l2 memory",
    )
    memory_keywords = (
        "记忆",
        "经验",
        "知识库",
        "知识卡",
        "领域知识",
        "索引",
        "标签",
        "长期记忆",
        "语义记忆",
        "episodic memory",
        "domain knowledge",
        "knowledge card",
    )
    if not any(marker in corpus for marker in memory_path_markers) and not any(keyword in corpus for keyword in memory_keywords):
        return ""

    if any(token in corpus for token in ("cleanup", "archive", "归档", "清理", "replace", "替换", "delete", "删除")):
        return "cleanup"
    if any(token in corpus for token in ("review", "audit", "审查", "审阅", "deprecated", "废弃")):
        return "review"
    if any(token in corpus for token in ("doc", "readme", "new doc", "文档", "知识卡", "新增", "append", "link")):
        return "new_doc"
    if any(token in corpus for token in ("refactor", "重构", "reorganize", "整理")):
        return "refactor"
    if any(token in corpus for token in ("bug", "fix", "修复", "patch", "冲突")):
        return "bugfix"
    return "bugfix" if role_text == "dev" else "review"


def resolve_child_tool_capabilities(
    *,
    role: str,
    tool_profile: Any = None,
    tool_subset: Optional[Sequence[Any]] = None,
    task_description: str = "",
    files: Optional[Sequence[str]] = None,
) -> ToolProfileResolution:
    """Resolve a child agent's final tool subset.

    Rules:
    - preset profile string → mapped subset
    - `tool_profile=[...]` or `tool_profile="custom"` + subset → explicit tools
    - historical alias `tool_subset=[...]` remains supported
    - if nothing explicit is provided, infer a memory profile only for obvious
      memory/doc tasks; otherwise return the original subset (possibly empty)
    """
    explicit_subset = normalize_tool_subset(tool_subset)

    if isinstance(tool_profile, (list, tuple, set)):
        return ToolProfileResolution(
            profile_name="custom",
            tool_subset=normalize_tool_subset(list(tool_profile)),
            source="profile_list",
        )

    profile_name = str(tool_profile or "").strip().lower()
    if profile_name in TOOL_PROFILE_PRESETS and profile_name != "custom":
        return ToolProfileResolution(
            profile_name=profile_name,
            tool_subset=list(TOOL_PROFILE_PRESETS[profile_name]),
            source="preset",
        )

    if profile_name == "custom":
        return ToolProfileResolution(
            profile_name="custom",
            tool_subset=explicit_subset,
            source="preset_custom",
        )

    if explicit_subset:
        source = "memory_subset" if all(is_memory_tool_name(item) for item in explicit_subset) else "explicit_subset"
        profile = "custom" if source == "memory_subset" else ""
        return ToolProfileResolution(profile_name=profile, tool_subset=explicit_subset, source=source)

    inferred = infer_memory_tool_profile(
        task_description,
        files=files,
        role=role,
    )
    if inferred:
        return ToolProfileResolution(
            profile_name=inferred,
            tool_subset=list(TOOL_PROFILE_PRESETS[inferred]),
            source="inferred",
        )

    return ToolProfileResolution(
        profile_name="discovery",
        tool_subset=[
            "search_tools", "activate_domain",
            "list_domains", "list_active_tools",
            "create_tool",
        ],
        source="discovery_fallback",
    )


__all__ = [
    "MEMORY_TOOL_ALIASES",
    "MEMORY_TOOL_NAMES",
    "TOOL_PROFILE_PRESETS",
    "ToolProfileResolution",
    "infer_memory_tool_profile",
    "is_memory_tool_name",
    "normalize_memory_tool_name",
    "normalize_tool_subset",
    "resolve_child_tool_capabilities",
]
