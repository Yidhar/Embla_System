from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from agents.runtime.agent_session import AgentSessionStore
from apiserver.native_tools import NativeToolExecutor


class _FakeBoxLiteManager:
    def __init__(self):
        self.calls = []

    async def exec_in_box(self, *, box_name, workspace_host_root, command, args=None, env=None, working_dir=None, timeout_seconds=None, project_root=None):
        self.calls.append(
            {
                "box_name": box_name,
                "workspace_host_root": workspace_host_root,
                "command": command,
                "args": list(args or []),
                "env": dict(env or {}),
                "working_dir": working_dir,
                "project_root": project_root,
            }
        )
        if command == "python":
            argv = list(args or [])
            if len(argv) >= 3 and argv[:2] == ["-m", "system.boxlite.guest_tools"]:
                if argv[2] == "read_file":
                    return {"exit_code": 0, "stdout": "hello from box\n", "stderr": "", "box_id": "box-1"}
                if argv[2] == "write_file":
                    return {"exit_code": 0, "stdout": "已写入文件: /workspace/tests/demo.txt (mode=overwrite, chars=7)", "stderr": "", "box_id": "box-1"}
                if argv[2] == "search_keyword":
                    return {"exit_code": 0, "stdout": "a.txt:1: HELLO", "stderr": "", "box_id": "box-1"}
                if argv[2] == "query_docs":
                    return {"exit_code": 0, "stdout": "doc/demo.md:1: Embla docs", "stderr": "", "box_id": "box-1"}
                if argv[2] == "file_ast_skeleton":
                    return {"exit_code": 0, "stdout": "[symbols]\n   1: class Demo\n", "stderr": "", "box_id": "box-1"}
                if argv[2] == "file_ast_chunk_read":
                    return {"exit_code": 0, "stdout": "[requested_range] 1-3\n", "stderr": "", "box_id": "box-1"}
                if argv[2] == "workspace_txn_apply":
                    return {
                        "exit_code": 0,
                        "stdout": "[transaction_id] txn_boxlite\n[committed] True\n[clean_state] True\n[recovery_ticket] recovery_boxlite\n[changed_files] 1\n[semantic_rebased_files] 0\n[verify] verify ok\n[files]\npatches/demo.txt\n",
                        "stderr": "",
                        "box_id": "box-1",
                    }
            return {"exit_code": 0, "stdout": "python-result", "stderr": "", "box_id": "box-1"}
        return {"exit_code": 0, "stdout": "", "stderr": "", "box_id": "box-1"}


def _make_executor_with_box_session() -> tuple[NativeToolExecutor, AgentSessionStore]:
    store = AgentSessionStore(db_path=":memory:")
    workspace_root = str((Path("scratch") / "agent_worktrees" / "agent-box-real").resolve())
    store.create(
        role="dev",
        session_id="agent-box-real",
        metadata={
            "workspace_mode": "worktree",
            "workspace_root": workspace_root,
            "workspace_origin_root": str(Path('.').resolve()),
            "execution_backend": "boxlite",
            "execution_root": "/workspace",
            "box_name": "embla-agent-box-real",
            "box_id": "box-existing-real",
        },
    )
    executor = NativeToolExecutor()
    executor.set_agent_session_store(store)
    return executor, store


def _patch_boxlite_available(monkeypatch, executor: NativeToolExecutor) -> None:
    status = lambda *args, **kwargs: SimpleNamespace(available=True, reason="", provider="sdk", working_dir="/workspace", image="python:slim")
    monkeypatch.setattr("system.execution_backend.boxlite_backend.probe_boxlite_runtime_readiness", status)
    monkeypatch.setattr("system.execution_backend.registry.probe_boxlite_runtime_readiness", status)


def test_boxlite_backend_read_file_uses_guest_workspace(monkeypatch):
    executor, store = _make_executor_with_box_session()
    try:
        fake_manager = _FakeBoxLiteManager()
        _patch_boxlite_available(monkeypatch, executor)
        monkeypatch.setattr(executor.backend_registry._boxlite_backend, "manager", fake_manager)

        result = asyncio.run(executor.execute({"tool_name": "read_file", "path": "README.md"}, session_id="agent-box-real"))

        assert result["status"] == "success"
        assert "hello from box" in str(result["result"])
        assert fake_manager.calls[0]["command"] == "python"
        assert fake_manager.calls[0]["args"][:3] == ["-m", "system.boxlite.guest_tools", "read_file"]
        assert "/workspace/README.md" in fake_manager.calls[0]["args"]
    finally:
        store.close()


def test_boxlite_backend_search_keyword_uses_python_in_box(monkeypatch):
    executor, store = _make_executor_with_box_session()
    try:
        fake_manager = _FakeBoxLiteManager()
        _patch_boxlite_available(monkeypatch, executor)
        monkeypatch.setattr(executor.backend_registry._boxlite_backend, "manager", fake_manager)

        result = asyncio.run(executor.execute({"tool_name": "search_keyword", "keyword": "HELLO"}, session_id="agent-box-real"))

        assert result["status"] == "success"
        assert "a.txt:1: HELLO" in str(result["result"])
        assert fake_manager.calls[0]["command"] == "python"
        assert fake_manager.calls[0]["args"][:3] == ["-m", "system.boxlite.guest_tools", "search_keyword"]
        assert fake_manager.calls[0]["working_dir"] == "/workspace"
    finally:
        store.close()


def test_boxlite_backend_git_status_uses_git_in_box(monkeypatch):
    executor, store = _make_executor_with_box_session()
    try:
        fake_manager = _FakeBoxLiteManager()

        async def _exec_in_box(**kwargs):
            fake_manager.calls.append(kwargs)
            return {"exit_code": 0, "stdout": "## main\n M a.txt\n", "stderr": "", "box_id": "box-1"}

        fake_manager.exec_in_box = _exec_in_box
        _patch_boxlite_available(monkeypatch, executor)
        monkeypatch.setattr(executor.backend_registry._boxlite_backend, "manager", fake_manager)

        result = asyncio.run(executor.execute({"tool_name": "git_status"}, session_id="agent-box-real"))

        assert result["status"] == "success"
        assert "[exit_code] 0" in str(result["result"])
        assert fake_manager.calls[0]["command"] == "git"
        assert fake_manager.calls[0]["args"][:2] == ["status", "--short"]
    finally:
        store.close()


def test_boxlite_backend_workspace_txn_apply_runs_guest_helper_in_box(monkeypatch):
    executor, store = _make_executor_with_box_session()
    try:
        fake_manager = _FakeBoxLiteManager()
        _patch_boxlite_available(monkeypatch, executor)
        monkeypatch.setattr(executor.backend_registry._boxlite_backend, "manager", fake_manager)

        result = asyncio.run(
            executor.execute(
                {
                    "tool_name": "workspace_txn_apply",
                    "changes": [{"path": "patches/demo.txt", "content": "patched", "mode": "overwrite"}],
                },
                session_id="agent-box-real",
            )
        )

        assert result["status"] == "success"
        assert "[transaction_id] txn_boxlite" in str(result["result"])
        assert fake_manager.calls[0]["command"] == "python"
        assert fake_manager.calls[0]["args"][:3] == ["-m", "system.boxlite.guest_tools", "workspace_txn_apply"]
        assert "EMBLA_WORKSPACE_TXN_PAYLOAD" in fake_manager.calls[0]["env"]
    finally:
        store.close()


def test_boxlite_backend_python_repl_runs_safe_payload_and_persists_box_metadata(monkeypatch):
    executor, store = _make_executor_with_box_session()
    try:
        fake_manager = _FakeBoxLiteManager()

        async def _exec_in_box(**kwargs):
            fake_manager.calls.append(kwargs)
            return {
                "exit_code": 0,
                "stdout": '{"ok": true, "stdout": "hello", "has_result": true, "result_repr": "3", "result_type": "int"}\n',
                "stderr": "",
                "box_id": "box-repl-1",
                "box_name": kwargs.get("box_name", ""),
            }

        fake_manager.exec_in_box = _exec_in_box
        _patch_boxlite_available(monkeypatch, executor)
        monkeypatch.setattr(executor.backend_registry._boxlite_backend, "manager", fake_manager)

        result = asyncio.run(
            executor.execute({"tool_name": "python_repl", "expression": "1 + 2"}, session_id="agent-box-real")
        )

        assert result["status"] == "success"
        assert "[sandbox] boxlite" in str(result["result"])
        assert "[result]" in str(result["result"])
        assert fake_manager.calls[0]["command"] == "python"
        assert fake_manager.calls[0]["args"][:2] == ["-I", "-c"]
        assert "EMBLA_SAFE_REPL_PAYLOAD" in fake_manager.calls[0]["env"]
        session = store.get("agent-box-real")
        assert session is not None
        assert session.metadata["box_id"] == "box-repl-1"
        assert session.metadata["box_name"] == "embla-agent-box-real"
    finally:
        store.close()


def test_boxlite_backend_uses_stable_box_name_instead_of_box_id(monkeypatch):
    executor, store = _make_executor_with_box_session()
    try:
        fake_manager = _FakeBoxLiteManager()
        _patch_boxlite_available(monkeypatch, executor)
        monkeypatch.setattr(executor.backend_registry._boxlite_backend, "manager", fake_manager)

        result = asyncio.run(executor.execute({"tool_name": "read_file", "path": "README.md"}, session_id="agent-box-real"))

        assert result["status"] == "success"
        assert fake_manager.calls[0]["box_name"] == "embla-agent-box-real"
    finally:
        store.close()


def test_boxlite_backend_query_docs_runs_guest_helper_in_box(monkeypatch):
    executor, store = _make_executor_with_box_session()
    try:
        fake_manager = _FakeBoxLiteManager()
        _patch_boxlite_available(monkeypatch, executor)
        monkeypatch.setattr(executor.backend_registry._boxlite_backend, "manager", fake_manager)

        result = asyncio.run(executor.execute({"tool_name": "query_docs", "query": "Embla"}, session_id="agent-box-real"))

        assert result["status"] == "success"
        assert "doc/demo.md:1: Embla docs" in str(result["result"])
        assert fake_manager.calls[0]["command"] == "python"
        assert fake_manager.calls[0]["args"][:3] == ["-m", "system.boxlite.guest_tools", "query_docs"]
    finally:
        store.close()


def test_boxlite_backend_file_ast_skeleton_runs_guest_helper_in_box(monkeypatch):
    executor, store = _make_executor_with_box_session()
    try:
        fake_manager = _FakeBoxLiteManager()
        _patch_boxlite_available(monkeypatch, executor)
        monkeypatch.setattr(executor.backend_registry._boxlite_backend, "manager", fake_manager)

        result = asyncio.run(
            executor.execute({"tool_name": "file_ast_skeleton", "path": "src/demo.py"}, session_id="agent-box-real")
        )

        assert result["status"] == "success"
        assert fake_manager.calls[0]["command"] == "python"
        assert fake_manager.calls[0]["args"][:3] == ["-m", "system.boxlite.guest_tools", "file_ast_skeleton"]
        assert "/workspace/src/demo.py" in fake_manager.calls[0]["args"]
    finally:
        store.close()


def test_boxlite_backend_git_status_falls_back_to_host_when_git_missing(monkeypatch):
    executor, store = _make_executor_with_box_session()
    try:
        fake_manager = _FakeBoxLiteManager()

        async def _missing_git(**kwargs):
            fake_manager.calls.append(kwargs)
            return {"exit_code": 127, "stdout": "", "stderr": "git: not found", "box_id": "box-1"}

        fake_manager.exec_in_box = _missing_git
        _patch_boxlite_available(monkeypatch, executor)
        monkeypatch.setattr(executor.backend_registry._boxlite_backend, "manager", fake_manager)

        captured = {}

        async def _fake_execute_native_tool(tool_name, call):
            captured["tool_name"] = tool_name
            captured["call"] = dict(call)
            return "[host git status]"

        monkeypatch.setattr(executor, "_execute_native_tool", _fake_execute_native_tool)

        result = asyncio.run(executor.execute({"tool_name": "git_status"}, session_id="agent-box-real"))

        assert result["status"] == "success"
        assert result["result"] == "[host git status]"
        assert fake_manager.calls[0]["command"] == "git"
        assert captured["tool_name"] == "git_status"
        assert captured["call"]["repo_path"].replace("\\", "/").endswith("scratch/agent_worktrees/agent-box-real")
    finally:
        store.close()


def test_boxlite_backend_run_cmd_falls_back_to_sh_when_bash_missing(monkeypatch):
    executor, store = _make_executor_with_box_session()
    try:
        fake_manager = _FakeBoxLiteManager()

        async def _exec_in_box(**kwargs):
            fake_manager.calls.append(kwargs)
            if kwargs.get("command") == "bash":
                return {"exit_code": 127, "stdout": "", "stderr": "bash: not found", "box_id": "box-1"}
            return {"exit_code": 0, "stdout": "ok\n", "stderr": "", "box_id": "box-1"}

        fake_manager.exec_in_box = _exec_in_box
        _patch_boxlite_available(monkeypatch, executor)
        monkeypatch.setattr(executor.backend_registry._boxlite_backend, "manager", fake_manager)

        result = asyncio.run(executor.execute({"tool_name": "run_cmd", "command": "echo ok"}, session_id="agent-box-real"))

        assert result["status"] == "success"
        assert "ok" in str(result["result"])
        assert [call["command"] for call in fake_manager.calls] == ["bash", "sh"]
    finally:
        store.close()


def test_boxlite_backend_write_file_honors_test_baseline_guard(monkeypatch):
    executor, store = _make_executor_with_box_session()
    try:
        fake_manager = _FakeBoxLiteManager()
        _patch_boxlite_available(monkeypatch, executor)
        monkeypatch.setattr(executor.backend_registry._boxlite_backend, "manager", fake_manager)
        monkeypatch.setattr(
            "system.execution_backend.boxlite_backend.TestBaselineGuard.check_modification_allowed",
            lambda self, safe_path, requester=None: (False, f"blocked baseline: {safe_path.name}"),
        )

        result = asyncio.run(
            executor.execute(
                {
                    "tool_name": "write_file",
                    "path": "tests/blocked_by_guard.py",
                    "content": "def test_ok():\n    assert 1 == 1\n",
                },
                session_id="agent-box-real",
            )
        )

        assert result["status"] == "error"
        assert "blocked baseline" in str(result["result"])
        assert fake_manager.calls == []
    finally:
        store.close()


def test_boxlite_backend_write_file_blocks_test_poisoning_patterns(monkeypatch):
    executor, store = _make_executor_with_box_session()
    try:
        fake_manager = _FakeBoxLiteManager()
        workspace_root = Path(store.get("agent-box-real").metadata["workspace_root"])
        poison_path = workspace_root / "tests" / "tmp_poison_guard_case_boxlite.py"
        poison_path.unlink(missing_ok=True)

        _patch_boxlite_available(monkeypatch, executor)
        monkeypatch.setattr(executor.backend_registry._boxlite_backend, "manager", fake_manager)

        result = asyncio.run(
            executor.execute(
                {
                    "tool_name": "write_file",
                    "path": "tests/tmp_poison_guard_case_boxlite.py",
                    "content": "import pytest\n\n@pytest.mark.skip(reason='nope')\ndef test_poisoned():\n    assert True\n",
                },
                session_id="agent-box-real",
            )
        )

        assert result["status"] == "error"
        assert "Anti-Test-Poisoning blocked write" in str(result["result"])
        assert poison_path.exists() is False
        assert fake_manager.calls == []
    finally:
        store.close()


def test_boxlite_backend_run_cmd_respects_call_cwd(monkeypatch):
    executor, store = _make_executor_with_box_session()
    try:
        fake_manager = _FakeBoxLiteManager()
        _patch_boxlite_available(monkeypatch, executor)
        monkeypatch.setattr(executor.backend_registry._boxlite_backend, "manager", fake_manager)

        result = asyncio.run(
            executor.execute(
                {"tool_name": "run_cmd", "command": "echo ok", "cwd": "Embla_core"},
                session_id="agent-box-real",
            )
        )

        assert result["status"] == "success"
        assert fake_manager.calls[0]["working_dir"] == "/workspace/Embla_core"
    finally:
        store.close()


def test_boxlite_backend_falls_back_to_native_and_persists_session_fallback(monkeypatch):
    executor, store = _make_executor_with_box_session()
    try:
        fake_manager = _FakeBoxLiteManager()

        async def _explode_exec_in_box(**kwargs):
            fake_manager.calls.append(kwargs)
            raise RuntimeError("boxlite_runtime_panic: can't start new thread")

        fake_manager.exec_in_box = _explode_exec_in_box
        _patch_boxlite_available(monkeypatch, executor)
        monkeypatch.setattr(executor.backend_registry._boxlite_backend, "manager", fake_manager)

        captured = {}

        async def _fake_execute_native_tool(tool_name, call):
            captured["tool_name"] = tool_name
            captured["call"] = dict(call)
            return "[host fallback read]"

        monkeypatch.setattr(executor, "_execute_native_tool", _fake_execute_native_tool)

        result = asyncio.run(executor.execute({"tool_name": "read_file", "path": "README.md"}, session_id="agent-box-real"))

        assert result["status"] == "success"
        assert result["result"] == "[host fallback read]"
        assert result["service_name"] == "native"
        assert result["execution_backend"] == "native"
        assert "boxlite_runtime_panic" in result["box_fallback_reason"]
        session = store.get("agent-box-real")
        assert session is not None
        assert session.metadata["execution_backend"] == "native"
        assert session.metadata["execution_root"].replace("\\", "/").endswith("scratch/agent_worktrees/agent-box-real")
        assert "boxlite_runtime_panic" in session.metadata["box_fallback_reason"]
        assert captured["tool_name"] == "read_file"
        assert captured["call"]["path"].replace("\\", "/").endswith("scratch/agent_worktrees/agent-box-real/README.md")
    finally:
        store.close()


def test_boxlite_backend_search_keyword_honors_regex_and_case_sensitive(monkeypatch):
    executor, store = _make_executor_with_box_session()
    workspace_root = Path(store.get("agent-box-real").metadata["workspace_root"])
    target = workspace_root / "src" / "case_demo.txt"
    shutil.rmtree(workspace_root, ignore_errors=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("HelloWorld\nhelloworld\n", encoding="utf-8")

    class _LocalPythonBoxLiteManager(_FakeBoxLiteManager):
        async def exec_in_box(self, *, box_name, workspace_host_root, command, args=None, env=None, working_dir=None, timeout_seconds=None, project_root=None):
            self.calls.append(
                {
                    "box_name": box_name,
                    "workspace_host_root": workspace_host_root,
                    "command": command,
                    "args": list(args or []),
                    "env": dict(env or {}),
                    "working_dir": working_dir,
                    "project_root": project_root,
                }
            )
            if command != "python":
                return {"exit_code": 1, "stdout": "", "stderr": f"unexpected command: {command}", "box_id": "box-1"}
            rewritten_args = [str(item).replace("/workspace", workspace_host_root.replace("\\", "/")) for item in (args or [])]
            rewritten_env = {
                key: (str(value).replace("/workspace", workspace_host_root.replace("\\", "/")) if isinstance(value, str) else value)
                for key, value in dict(env or {}).items()
            }
            proc = subprocess.run(
                [sys.executable, *rewritten_args],
                capture_output=True,
                text=True,
                cwd=str(working_dir or workspace_host_root).replace("/workspace", workspace_host_root.replace("\\", "/")),
                env={**os.environ, **rewritten_env},
                timeout=timeout_seconds or 30,
            )
            return {"exit_code": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr, "box_id": "box-1"}

    try:
        fake_manager = _LocalPythonBoxLiteManager()
        _patch_boxlite_available(monkeypatch, executor)
        monkeypatch.setattr(executor.backend_registry._boxlite_backend, "manager", fake_manager)

        result = asyncio.run(
            executor.execute(
                {
                    "tool_name": "search_keyword",
                    "keyword": "^Hello[A-Z][a-z]+$",
                    "search_path": ".",
                    "use_regex": True,
                    "case_sensitive": True,
                },
                session_id="agent-box-real",
            )
        )

        text_result = str(result["result"])
        assert result["status"] == "success"
        assert "src/case_demo.txt:1: HelloWorld" in text_result
        assert "helloworld" not in text_result
    finally:
        shutil.rmtree(workspace_root, ignore_errors=True)
        store.close()


def test_boxlite_backend_read_file_honors_grep_and_jsonpath_modes(monkeypatch):
    executor, store = _make_executor_with_box_session()
    workspace_root = Path(store.get("agent-box-real").metadata["workspace_root"])
    try:
        shutil.rmtree(workspace_root, ignore_errors=True)
        (workspace_root / "src").mkdir(parents=True, exist_ok=True)
        (workspace_root / "src" / "demo.txt").write_text("Alpha\nBeta\nAlphaBeta\n", encoding="utf-8")
        (workspace_root / "src" / "payload.json").write_text('{"trace":{"id":"abc"},"items":[{"name":"one"}]}', encoding="utf-8")

        class _LocalPythonBoxLiteManager(_FakeBoxLiteManager):
            async def exec_in_box(self, *, box_name, workspace_host_root, command, args=None, env=None, working_dir=None, timeout_seconds=None, project_root=None):
                self.calls.append(
                    {
                        "box_name": box_name,
                        "workspace_host_root": workspace_host_root,
                        "command": command,
                        "args": list(args or []),
                        "env": dict(env or {}),
                        "working_dir": working_dir,
                        "project_root": project_root,
                    }
                )
                rewritten_args = [str(item).replace("/workspace", workspace_host_root.replace("\\", "/")) for item in (args or [])]
                proc = subprocess.run(
                    [sys.executable, *rewritten_args],
                    capture_output=True,
                    text=True,
                    cwd=workspace_host_root,
                    env={**os.environ, **dict(env or {})},
                    timeout=timeout_seconds or 30,
                )
                return {"exit_code": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr, "box_id": "box-1"}

        fake_manager = _LocalPythonBoxLiteManager()
        _patch_boxlite_available(monkeypatch, executor)
        monkeypatch.setattr(executor.backend_registry._boxlite_backend, "manager", fake_manager)

        grep_result = asyncio.run(
            executor.execute(
                {
                    "tool_name": "read_file",
                    "path": "src/demo.txt",
                    "mode": "grep",
                    "pattern": "^Alpha",
                    "use_regex": True,
                    "case_sensitive": True,
                },
                session_id="agent-box-real",
            )
        )
        json_result = asyncio.run(
            executor.execute(
                {
                    "tool_name": "read_file",
                    "path": "src/payload.json",
                    "mode": "jsonpath",
                    "jsonpath": "$.trace.id",
                },
                session_id="agent-box-real",
            )
        )

        grep_text = str(grep_result["result"])
        json_text = str(json_result["result"])
        assert grep_result["status"] == "success"
        assert "[mode] grep" in grep_text
        assert "   1: Alpha" in grep_text
        assert "   3: AlphaBeta" in grep_text
        assert json_result["status"] == "success"
        assert "[mode] jsonpath" in json_text
        assert "[1] abc" in json_text
    finally:
        shutil.rmtree(workspace_root, ignore_errors=True)
        store.close()


def test_boxlite_guest_helper_module_entrypoint_has_no_bootstrap_noise(tmp_path: Path) -> None:
    target = tmp_path / "demo.txt"
    target.write_text("hello\n", encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, "-m", "system.boxlite.guest_tools", "read_file", "--path", str(target)],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
        timeout=30,
    )

    assert proc.returncode == 0
    assert proc.stdout == "hello\n"
    assert "检测到配置文件编码" not in proc.stdout
