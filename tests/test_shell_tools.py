"""Tests for Shell Agent read-only tools (Phase 3.6)."""

from __future__ import annotations

import json
from pathlib import Path

import agents.shell_tools as shell_tools_module
from agents.shell_tools import (
    get_shell_tool_definitions,
    handle_shell_tool,
)
from core.event_bus.event_store import EventStore


# ── Tool Definition Tests ──────────────────────────────────────


class TestToolDefinitions:

    def test_returns_7_tools(self) -> None:
        defs = get_shell_tool_definitions()
        assert len(defs) == 7

    def test_all_have_name_and_description(self) -> None:
        for td in get_shell_tool_definitions():
            assert "name" in td
            assert "description" in td
            assert len(td["description"]) > 10

    def test_tool_names_match(self) -> None:
        names = {td["name"] for td in get_shell_tool_definitions()}
        assert names == {
            "memory_read",
            "memory_list",
            "memory_grep",
            "memory_search",
            "get_system_status",
            "list_tasks",
            "search_web",
        }

    def test_memory_search_has_query_param(self) -> None:
        for td in get_shell_tool_definitions():
            if td["name"] == "memory_search":
                assert "query" in td["parameters"]["properties"]
                assert "query" in td["parameters"]["required"]
                break


# ── memory_read ────────────────────────────────────────────────


class TestReadFile:

    def test_reads_existing_file(self, tmp_path: Path) -> None:
        test_file = tmp_path / "hello.txt"
        test_file.write_text("line1\nline2\nline3\n", encoding="utf-8")

        result = handle_shell_tool(
            "memory_read",
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
            "memory_read",
            {"path": str(test_file), "start_line": 3, "end_line": 5},
            project_root=tmp_path,
        )
        assert result["status"] == "success"
        assert "line_2" in result["result"]
        assert "line_4" in result["result"]

    def test_file_not_found(self, tmp_path: Path) -> None:
        result = handle_shell_tool(
            "memory_read",
            {"path": "nonexistent.txt"},
            project_root=tmp_path,
        )
        assert result["status"] == "error"

    def test_missing_path(self, tmp_path: Path) -> None:
        result = handle_shell_tool(
            "memory_read",
            {},
            project_root=tmp_path,
        )
        assert result["status"] == "error"

    def test_truncates_large_files(self, tmp_path: Path) -> None:
        big_file = tmp_path / "big.txt"
        big_file.write_text("x" * 10000, encoding="utf-8")

        result = handle_shell_tool(
            "memory_read",
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
                "memory_read",
                {"path": outer_path},
                project_root=project,
            )
            assert result["status"] == "error"
        finally:
            Path(outer_path).unlink(missing_ok=True)

    def test_legacy_read_file_alias_still_works(self, tmp_path: Path) -> None:
        test_file = tmp_path / "hello.txt"
        test_file.write_text("hello", encoding="utf-8")

        result = handle_shell_tool(
            "read_file",
            {"path": str(test_file)},
            project_root=tmp_path,
        )
        assert result["status"] == "success"
        assert result["tool_name"] == "memory_read"


# ── get_system_status ──────────────────────────────────────────


class TestSystemStatus:

    def test_returns_status_with_empty_project(self, tmp_path: Path) -> None:
        result = handle_shell_tool(
            "get_system_status",
            {},
            project_root=tmp_path,
        )
        assert result["status"] == "success"
        assert "Runtime Posture" in result["result"]

    def test_reads_posture_from_canonical_sqlite(self, tmp_path: Path) -> None:
        """Seed the canonical SQLite event DB and verify shell_tools reads from it."""
        event_store = EventStore(file_path=tmp_path / "logs" / "autonomous" / "events.jsonl")
        for _ in range(42):
            event_store.emit("tool_result", {"k": "v"}, source="unit.test", severity="info")
        for _ in range(3):
            event_store.emit("tool_error", {"k": "v"}, source="unit.test", severity="error")

        result = handle_shell_tool(
            "get_system_status", {}, project_root=tmp_path
        )
        assert result["status"] == "success"
        assert "total=45" in result["result"]
        assert "errors=3" in result["result"]

    def test_runtime_posture_section_uses_richer_ops_summary(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(
            shell_tools_module,
            "_load_runtime_posture_payload",
            lambda *, project_root: {
                "generated_at": "2026-03-23T10:00:00Z",
                "severity": "warning",
                "reason_code": "WATCHDOG_DAEMON_WARNING",
                "reason_text": "Watchdog daemon requires attention.",
                "data": {
                    "summary": {
                        "overall_status": "warning",
                        "control_plane_mode": "single_control_plane",
                        "control_plane_mode_status": "ok",
                        "runtime_lease": {
                            "status": "ok",
                            "state": "healthy",
                            "owner_id": "core",
                            "value": 18.5,
                        },
                        "brainstem_control_plane_status": "ok",
                        "watchdog_daemon_status": "warning",
                        "process_guard_status": "ok",
                        "killswitch_guard_status": "ok",
                        "budget_guard_status": "ok",
                        "immutable_dna_status": "warning",
                        "audit_ledger_status": "ok",
                        "os_sandbox_runtime_status": "ok",
                        "boxlite_runtime_status": "warning",
                        "execution_bridge_governance_status": "ok",
                        "agentic_loop_completion_status": "ok",
                        "core_child_spawn_deferred_status": "unknown",
                        "vision_multimodal_status": "ok",
                        "route_quality": {
                            "status": "warning",
                            "dispatch_to_core_rate": 0.25,
                        },
                    }
                },
            },
        )

        result = handle_shell_tool("get_system_status", {}, project_root=tmp_path)

        assert result["status"] == "success"
        assert "总体状态: warning" in result["result"]
        assert "控制面: single_control_plane (ok)" in result["result"]
        assert "租约: ok / state=healthy / owner=core / remaining=18.5s" in result["result"]
        assert "守护链: brainstem=ok, watchdog=warning, process_guard=ok" in result["result"]
        assert "执行链: os_sandbox=ok, boxlite=warning" in result["result"]
        assert "Shell→Core 升级率: 0.250" in result["result"]

    def test_reads_topic_event_posture_from_canonical_db(self, tmp_path: Path) -> None:
        event_store = EventStore(file_path=tmp_path / "logs" / "autonomous" / "events.jsonl")
        event_store.emit(
            "TaskApproved",
            {"workflow_id": "wf-001", "task_id": "task-001"},
            source="unit.test",
            severity="info",
        )
        event_store.emit(
            "ReleaseGateRejected",
            {
                "workflow_id": "wf-001",
                "task_id": "task-001",
                "reason_code": "WATCHDOG_FUSE_PAUSE_DISPATCH_AND_ESCALATE",
            },
            source="unit.test",
            severity="critical",
        )

        result = handle_shell_tool("get_system_status", {}, project_root=tmp_path)

        assert result["status"] == "success"
        assert "total=2" in result["result"]
        assert "errors=1" in result["result"]
        assert "latest=ReleaseGateRejected" in result["result"]

    def test_reads_canonical_db_with_mixed_severities(self, tmp_path: Path) -> None:
        """Verify severity aggregation from the canonical SQLite event DB."""
        event_store = EventStore(file_path=tmp_path / "logs" / "autonomous" / "events.jsonl")
        for _ in range(9):
            event_store.emit("HeartbeatOk", {"k": "v"}, source="unit.test", severity="info")
        for _ in range(2):
            event_store.emit("CriticalFailure", {"k": "v"}, source="unit.test", severity="critical")
        for _ in range(3):
            event_store.emit("SlowResponse", {"k": "v"}, source="unit.test", severity="warning")
        # Last event emitted — should appear as latest
        event_store.emit(
            "WatchdogThresholdExceeded", {"k": "v"}, source="unit.test", severity="warning"
        )

        result = handle_shell_tool("get_system_status", {}, project_root=tmp_path)

        assert result["status"] == "success"
        assert "total=15" in result["result"]
        assert "errors=2" in result["result"]
        assert "latest=WatchdogThresholdExceeded" in result["result"]

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


# ── memory_list / memory_grep / memory_search ────────────────


class TestMemoryListAndGrep:

    def test_memory_list_lists_l1_files(self, tmp_path: Path) -> None:
        domain = tmp_path / "memory" / "domain"
        domain.mkdir(parents=True)
        (domain / "python_ast.md").write_text("# Python AST\n", encoding="utf-8")

        result = handle_shell_tool("memory_list", {"scope": "domain"}, project_root=tmp_path)
        assert result["status"] == "success"
        assert "domain/python_ast.md" in result["result"]

    def test_memory_grep_searches_l1_files(self, tmp_path: Path) -> None:
        domain = tmp_path / "memory" / "domain"
        domain.mkdir(parents=True)
        (domain / "python_ast.md").write_text("# Python AST\nmatch-token\n", encoding="utf-8")

        result = handle_shell_tool(
            "memory_grep",
            {"scope": "domain", "pattern": "match-token"},
            project_root=tmp_path,
        )
        assert result["status"] == "success"
        assert "match-token" in result["result"]


class TestSearchMemory:

    def test_missing_query(self, tmp_path: Path) -> None:
        result = handle_shell_tool(
            "memory_search",
            {},
            project_root=tmp_path,
        )
        assert result["status"] == "error"

    def test_searches_gracefully_with_no_memory(self, tmp_path: Path) -> None:
        result = handle_shell_tool(
            "memory_search",
            {"query": "pipeline refactoring"},
            project_root=tmp_path,
        )
        assert result["status"] == "success"
        assert "搜索" in result["result"]

    def test_legacy_search_memory_alias_still_works(self, tmp_path: Path) -> None:
        result = handle_shell_tool(
            "search_memory",
            {"query": "pipeline refactoring"},
            project_root=tmp_path,
        )
        assert result["status"] == "success"
        assert result["tool_name"] == "memory_search"


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

    def test_returns_result_or_fallback(self) -> None:
        result = handle_shell_tool("search_web", {"query": "python asyncio"})
        assert result["status"] == "success"
        # Should either return search results or a fallback message
        assert "搜索" in result["result"]


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
        assert "memory_read" in names
        assert "memory_list" in names
        assert "memory_grep" in names
        assert "get_system_status" in names
        assert "memory_search" in names
        assert "list_tasks" in names
        assert "search_web" in names
        assert "dispatch_to_core" in names
        assert len(defs) == 8  # 7 read-only + dispatch_to_core

    def test_execute_tool_memory_read(self) -> None:
        from agents.shell_agent import ShellAgent
        agent = ShellAgent()

        # Use a file that exists within the project root
        result = agent.execute_tool("memory_read", {"path": "pyproject.toml"})
        assert result.get("status") == "success"
        assert "result" in result

    def test_execute_tool_legacy_read_file_alias(self) -> None:
        from agents.shell_agent import ShellAgent
        agent = ShellAgent()

        result = agent.execute_tool("read_file", {"path": "pyproject.toml"})
        assert result.get("status") == "success"
        assert "result" in result

    def test_execute_tool_unknown(self) -> None:
        from agents.shell_agent import ShellAgent
        agent = ShellAgent()
        result = agent.execute_tool("rm_rf", {})
        assert result.get("status") == "error"
