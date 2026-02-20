#!/usr/bin/env python3
"""Coding-intent heuristics shared by tool routing components."""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

_DIRECT_CODING_KEYWORDS = (
    # English
    "bug",
    "fix",
    "implement",
    "refactor",
    "coding",
    "code",
    "compile",
    "build",
    "lint",
    "unit test",
    "integration test",
    "test case",
    "repository",
    "repo",
    "pull request",
    "commit",
    # Chinese (escaped to keep this file ASCII-friendly)
    "\u4fee\u590d",  # 修复
    "\u5b9e\u73b0",  # 实现
    "\u91cd\u6784",  # 重构
    "\u5199\u4ee3\u7801",  # 写代码
    "\u4ee3\u7801",  # 代码
    "\u5f00\u53d1",  # 开发
    "\u8c03\u8bd5",  # 调试
    "\u6392\u67e5",  # 排查
    "\u5355\u6d4b",  # 单测
    "\u6d4b\u8bd5",  # 测试
    "\u7f16\u8bd1",  # 编译
    "\u6784\u5efa",  # 构建
    "\u63a5\u53e3",  # 接口
    "\u51fd\u6570",  # 函数
    "\u6a21\u5757",  # 模块
)

_FOLLOWUP_MARKERS = (
    "continue",
    "go on",
    "keep going",
    "same task",
    "follow up",
    "\u7ee7\u7eed",  # 继续
    "\u63a5\u7740",  # 接着
    "\u6309\u4e0a\u6b21",  # 按上次
    "\u6309\u524d\u9762",  # 按前面
    "\u5728\u521a\u624d",  # 在刚才
)

_CODING_CONTEXT_MARKERS = (
    "codex-cli",
    "ask-codex",
    "mcp_call",
    "native_call",
    "git diff",
    "git status",
    "tool_results",
    "diff --git",
    "apply_patch",
)

_FILE_HINT_RE = re.compile(
    r"(?:^|[\s`'\"(])[\w./\\-]+\.(?:py|ts|tsx|js|jsx|vue|go|rs|java|kt|cpp|c|h|hpp|cs|json|ya?ml|toml|ini|sql|sh|ps1|md)\b",
    flags=re.IGNORECASE,
)
_DIFF_HINT_RE = re.compile(
    r"(^|\n)(diff --git|@@|---\s+[ab]/|\+\+\+\s+[ab]/|index [0-9a-f]{7,})",
    flags=re.IGNORECASE,
)
_CODE_SNIPPET_HINT_RE = re.compile(
    r"(^|\n)\s*(def |class |import |from |function |const |let |var |if __name__ == ['\"]__main__['\"])",
    flags=re.IGNORECASE,
)


def _normalize_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if value is None:
        return ""
    return str(value).strip()


def extract_latest_user_message(messages: Sequence[Mapping[str, Any]]) -> str:
    for msg in reversed(list(messages)):
        if str(msg.get("role", "")).strip().lower() != "user":
            continue
        content = _normalize_text(msg.get("content", ""))
        if content:
            return content
    return ""


def contains_direct_coding_signal(text: str) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return False

    lowered = normalized.lower()
    if any(keyword in lowered for keyword in _DIRECT_CODING_KEYWORDS):
        return True

    if _FILE_HINT_RE.search(normalized):
        return True
    if _DIFF_HINT_RE.search(normalized):
        return True
    if _CODE_SNIPPET_HINT_RE.search(normalized):
        return True

    return False


def is_coding_followup(text: str) -> bool:
    normalized = " ".join(_normalize_text(text).lower().split())
    if not normalized:
        return False
    if len(normalized) > 80:
        return False
    return any(marker in normalized for marker in _FOLLOWUP_MARKERS)


def has_recent_coding_context(messages: Sequence[Mapping[str, Any]], lookback: int = 10) -> bool:
    if not messages:
        return False

    recent = list(messages)[-max(1, int(lookback)) :]
    for msg in recent:
        content = _normalize_text(msg.get("content", ""))
        if not content:
            continue
        lowered = content.lower()
        if contains_direct_coding_signal(content):
            return True
        if any(marker in lowered for marker in _CODING_CONTEXT_MARKERS):
            return True
    return False


def requires_codex_for_messages(messages: Sequence[Mapping[str, Any]]) -> bool:
    latest_user = extract_latest_user_message(messages)
    if contains_direct_coding_signal(latest_user):
        return True
    if is_coding_followup(latest_user) and has_recent_coding_context(messages):
        return True
    return False
