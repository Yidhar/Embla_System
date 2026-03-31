from __future__ import annotations

import asyncio

from agents.shell_tools import get_shell_tool_definitions
from apiserver.native_tools import NativeToolExecutor


def test_shell_readonly_tools_include_search_web() -> None:
    names = {str(item.get("name") or "") for item in get_shell_tool_definitions()}
    assert "search_web" in names


def test_native_executor_rejects_search_web_for_boundary_clarity() -> None:
    executor = NativeToolExecutor()
    result = asyncio.run(
        executor.execute(
            {"tool_name": "search_web", "query": "embla system architecture"},
            session_id="sess-shell-native-boundary",
        )
    )
    assert result.get("status") == "error"
    message = str(result.get("result") or "")
    assert ("Capability not allowlisted" in message) or ("不支持的native工具" in message)
