"""Tests for Shell Agent read-only tools (Phase 3.6)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from agents.shell_tools import (
    get_shell_tool_definitions,
    handle_shell_tool,
)


# ── Tool Definition Tests ──────────────────────────────────────


class TestToolDefinitions:

    def test_returns_5_tools(self) -> None:
        defs = get_shell_tool_definitions()
        assert len(defs) == 5

    def test_all_have_name_and_description(self) -> None:
        for td in get_shell_tool_definitions():
            assert "name" in td
            assert "description" in td
            assert len(td["description"]) > 10

    def test_tool_names_match(self) -> None:
        names = {td["name"] for td in get_shell_tool_definitions()}
        assert names == {
            "read_file",
            "get_system_status",
            "search_memory",
            "list_tasks",
            "search_web",
        }

    def test_search_memory_has_query_param(self) -> None:
        for td in get_shell_tool_definitions():
            if td["name"] == "search_memory":
                assert "query" in td["parameters"]["properties"]
                assert "query" in td["parameters"]["required"]
                break


# ── read_file ──────────────────────────────────────────────────


class TestReadFile:

    def test_reads_existing_file(self, tmp_path: Path) -> None:
        test_file = tmp_path / "hello.txt"
        test_file.write_text("line1\nline2\nline3\n", encoding="utf-8")

        result = handle_shell_tool(
            "read_file",
            {"path": str(test_file)},
            project_root=tmp_path,
        )
        assert result["status"] == "success"
        assert "line1" in result["result"]
        assert "line2" in result["result"]

    def test_reads_with_line_range(self, tmp_path: Path) -> None:
        test_file = tmp_path / "code.py"
        lines = [f"line_{i}" for i in range(10)]
        test_file.write_text("\n".join(lines), encoding="utf-8")

        result = handle_shell_tool(
            "read_file",
            {"path": str(test_file), "start_line": 3, "end_line": 5},
            project_root=tmp_path,
        )
        assert result["status"] == "success"
        assert "line_2" in result["result"]
        assert "line_4" in result["result"]

    def test_file_not_found(self, tmp_path: Path) -> None:
        result = handle_shell_tool(
            "read_file",
            {"path": "nonexistent.txt"},
            project_root=tmp_path,
        )
        assert result["status"] == "error"

    def test_missing_path(self, tmp_path: Path) -> None:
        result = handle_shell_tool(
            "read_file",
            {},
            project_root=tmp_path,
        )
        assert result["status"] == "error"

    def test_truncates_large_files(self, tmp_path: Path) -> None:
        big_file = tmp_path / "big.txt"
        big_file.write_text("x" * 10000, encoding="utf-8")

        result = handle_shell_tool(
            "read_file",
            {"path": str(big_file)},
            project_root=tmp_path,
        )
        assert result["status"] == "success"
        assert "截断" in result["result"]

    def test_rejects_path_outside_project(self, tmp_path: Path) -> None:
        # Create a file outside project root
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as f:
            f.write(b"secret")
            outer_path = f.name

        try:
            project = tmp_path / "project"
            project.mkdir()
            result = handle_shell_tool(
                "read_file",
                {"path": outer_path},
                project_root=project,
            )
            assert result["status"] == "error"
        finally:
            Path(outer_path).unlink(missing_ok=True)


# ── get_system_status ──────────────────────────────────────────


class TestSystemStatus:

    def test_returns_status_with_empty_project(self, tmp_path: Path) -> None:
        result = handle_shell_tool(
            "get_system_status",
            {},
            project_root=tmp_path,
        )
        assert result["status"] == "success"
        assert "Posture" in result["result"]

    def test_reads_posture_file(self, tmp_path: Path) -> None:
        runtime_dir = tmp_path / "scratch" / "runtime"
        runtime_dir.mkdir(parents=True)
        posture_file = runtime_dir / "event_bus_runtime_posture_ws28_029.json"
        posture_file.write_text(json.dumps({
            "events_total": 42,
            "errors_total": 3,
            "latest_event_type": "tool_result",
            "updated_at": "2026-03-03T12:00:00Z",
        }), encoding="utf-8")

        result = handle_shell_tool(
            "get_system_status", {}, project_root=tmp_path
        )
        assert result["status"] == "success"
        assert "42" in result["result"]
        assert "3" in result["result"]

    def test_reads_killswitch_state(self, tmp_path: Path) -> None:
        runtime_dir = tmp_path / "scratch" / "runtime"
        runtime_dir.mkdir(parents=True)
        ks_file = runtime_dir / "killswitch_guard_state_ws28_028.json"
        ks_file.write_text(json.dumps({"active": False}), encoding="utf-8")

        result = handle_shell_tool(
            "get_system_status", {}, project_root=tmp_path
        )
        assert "正常" in result["result"]

    def test_shows_memory_stats(self, tmp_path: Path) -> None:
        # Create memory dir with some files
        episodic = tmp_path / "memory" / "episodic"
        episodic.mkdir(parents=True)
        for i in range(3):
            (episodic / f"exp_20260303_test_{i}.md").write_text(f"test {i}", encoding="utf-8")

        result = handle_shell_tool(
            "get_system_status", {}, project_root=tmp_path
        )
        assert "3 经验" in result["result"]


# ── search_memory ──────────────────────────────────────────────


class TestSearchMemory:

    def test_missing_query(self, tmp_path: Path) -> None:
        result = handle_shell_tool(
            "search_memory",
            {},
            project_root=tmp_path,
        )
        assert result["status"] == "error"

    def test_searches_gracefully_with_no_memory(self, tmp_path: Path) -> None:
        result = handle_shell_tool(
            "search_memory",
            {"query": "pipeline refactoring"},
            project_root=tmp_path,
        )
        assert result["status"] == "success"
        assert "搜索" in result["result"]


# ── list_tasks ─────────────────────────────────────────────────


class TestListTasks:

    def test_lists_tasks_gracefully(self, tmp_path: Path) -> None:
        result = handle_shell_tool(
            "list_tasks",
            {},
            project_root=tmp_path,
        )
        # Should succeed (or show TaskBoard unavailable message)
        assert result["status"] == "success"
        assert "任务" in result["result"]


# ── search_web ─────────────────────────────────────────────────


class TestSearchWeb:

    def test_missing_query(self) -> None:
        result = handle_shell_tool("search_web", {})
        assert result["status"] == "error"

    def test_returns_config_reminder(self) -> None:
        result = handle_shell_tool("search_web", {"query": "python asyncio"})
        assert result["status"] == "success"
        assert "未配置" in result["result"] or "API" in result["result"]


# ── Unknown tool ───────────────────────────────────────────────


class TestUnknownTool:

    def test_returns_error_for_unknown(self) -> None:
        result = handle_shell_tool("delete_everything", {})
        assert result["status"] == "error"


# ── ShellAgent integration ─────────────────────────────────────


class TestShellAgentIntegration:

    def test_get_tool_definitions_includes_all(self) -> None:
        from agents.shell_agent import ShellAgent
        agent = ShellAgent()
        defs = agent.get_tool_definitions()
        names = {d["name"] for d in defs}
        assert "read_file" in names
        assert "get_system_status" in names
        assert "search_memory" in names
        assert "list_tasks" in names
        assert "search_web" in names
        assert "dispatch_to_core" in names
        assert len(defs) == 6  # 5 read-only + dispatch_to_core

    def test_execute_tool_read_file(self) -> None:
        from agents.shell_agent import ShellAgent
        agent = ShellAgent()

        # Use a file that exists within the project root
        result = agent.execute_tool("read_file", {"path": "pyproject.toml"})
        assert result.get("status") == "success"
        assert "result" in result

    def test_execute_tool_unknown(self) -> None:
        from agents.shell_agent import ShellAgent
        agent = ShellAgent()
        result = agent.execute_tool("rm_rf", {})
        assert result.get("status") == "error"
