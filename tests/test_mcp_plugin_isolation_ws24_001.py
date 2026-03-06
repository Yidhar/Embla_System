from __future__ import annotations

import asyncio
import json
import shutil
import sys
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import mcpserver.plugin_worker as plugin_worker_module
from mcpserver.mcp_manager import MCPManager
from mcpserver.mcp_registry import (
    ISOLATED_WORKER_REGISTRY,
    MCP_REGISTRY,
    REJECTED_PLUGIN_MANIFESTS,
    clear_registry,
    scan_and_register_mcp_agents,
)
from mcpserver.plugin_manifest_policy import compute_manifest_signature
from mcpserver.plugin_worker import (
    PluginWorkerProxy,
    PluginWorkerSpec,
    get_plugin_worker_runtime_metrics,
    reset_plugin_worker_runtime_metrics,
)


def _make_case_root(prefix: str) -> Path:
    root = Path("scratch") / prefix / uuid.uuid4().hex[:12]
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_case_root(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


def _write_manifest(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _sign_manifest(payload: dict, *, key_id: str, secret: str) -> dict:
    signed = dict(payload)
    signed["signature"] = {
        "algorithm": "hmac-sha256",
        "key_id": key_id,
        "value": compute_manifest_signature(signed, secret=secret),
    }
    return signed


def _set_plugin_trust_env(monkeypatch, *, allowlist: list[str], key_id: str, secret: str, scopes: list[str]) -> None:
    monkeypatch.setenv("EMBLA_PLUGIN_ALLOWLIST", ",".join(allowlist))
    monkeypatch.setenv("EMBLA_PLUGIN_SIGNING_KEYS", json.dumps({key_id: secret}, ensure_ascii=False))
    monkeypatch.setenv("EMBLA_PLUGIN_ALLOWED_SCOPES", ",".join(scopes))


def test_scan_registers_plugin_manifest_as_isolated_worker(monkeypatch) -> None:
    case_root = _make_case_root("test_mcp_plugin_isolation_ws24_001")
    clear_registry()
    reset_plugin_worker_runtime_metrics()
    try:
        plugin_root = case_root / "workspace" / "tools" / "plugins" / "echo_plugin"
        plugin_root.mkdir(parents=True, exist_ok=True)
        (plugin_root / "echo_plugin.py").write_text(
            """
import json

class EchoPluginAgent:
    async def handle_handoff(self, task):
        return json.dumps(
            {
                "status": "ok",
                "route": "isolated_plugin",
                "tool_name": str(task.get("tool_name") or ""),
                "message": str(task.get("message") or ""),
            },
            ensure_ascii=False,
        )
""".strip(),
            encoding="utf-8",
        )
        raw_manifest = {
            "name": "isolated_echo_plugin",
            "displayName": "Isolated Echo Plugin",
            "agentType": "mcp_plugin",
            "entryPoint": {
                "module": "echo_plugin",
                "class": "EchoPluginAgent",
            },
            "isolation": {
                "mode": "process",
                "timeout_seconds": 10,
            },
            "policy": {"scopes": ["read_workspace"]},
            "capabilities": {"invocationCommands": [{"command": "echo"}]},
        }
        _write_manifest(
            plugin_root / "agent-manifest.json",
            _sign_manifest(raw_manifest, key_id="ut-key", secret="ut-secret"),
        )

        _set_plugin_trust_env(
            monkeypatch,
            allowlist=["isolated_echo_plugin"],
            key_id="ut-key",
            secret="ut-secret",
            scopes=["read_workspace", "tool_invoke"],
        )
        monkeypatch.setenv("EMBLA_PLUGIN_MANIFEST_DIRS", str(plugin_root))
        registered = scan_and_register_mcp_agents(mcp_dir=str(case_root / "empty_mcp_root"))

        assert "isolated_echo_plugin" in registered
        assert "isolated_echo_plugin" in MCP_REGISTRY
        assert "isolated_echo_plugin" in ISOLATED_WORKER_REGISTRY
        instance = MCP_REGISTRY["isolated_echo_plugin"]
        assert isinstance(instance, PluginWorkerProxy)

        raw = asyncio.run(instance.handle_handoff({"tool_name": "echo", "message": "hello"}))
        payload = json.loads(raw)
        assert payload["status"] == "ok"
        assert payload["route"] == "isolated_plugin"
        assert payload["message"] == "hello"
    finally:
        clear_registry()
        reset_plugin_worker_runtime_metrics()
        _cleanup_case_root(case_root)


def test_scan_keeps_builtin_manifest_inprocess(monkeypatch) -> None:
    case_root = _make_case_root("test_mcp_plugin_isolation_ws24_001")
    clear_registry()
    try:
        builtin_root = case_root / "builtin_mcp"
        builtin_root.mkdir(parents=True, exist_ok=True)
        (builtin_root / "builtin_agent.py").write_text(
            """
import json

class BuiltinAgent:
    async def handle_handoff(self, task):
        return json.dumps({"status": "ok", "route": "builtin", "tool_name": task.get("tool_name", "")}, ensure_ascii=False)
""".strip(),
            encoding="utf-8",
        )
        _write_manifest(
            builtin_root / "agent-manifest.json",
            {
                "name": "builtin_inprocess_service",
                "displayName": "Builtin Inprocess Service",
                "agentType": "mcp",
                "entryPoint": {
                    "module": "builtin_agent",
                    "class": "BuiltinAgent",
                },
                "capabilities": {"invocationCommands": [{"command": "ping_builtin"}]},
            },
        )

        monkeypatch.setenv("EMBLA_PLUGIN_MANIFEST_DIRS", str(case_root / "missing_plugins"))
        sys.path.insert(0, str(builtin_root))
        try:
            registered = scan_and_register_mcp_agents(mcp_dir=str(builtin_root))
        finally:
            if str(builtin_root) in sys.path:
                sys.path.remove(str(builtin_root))

        assert "builtin_inprocess_service" in registered
        assert "builtin_inprocess_service" in MCP_REGISTRY
        assert "builtin_inprocess_service" not in ISOLATED_WORKER_REGISTRY
        assert not isinstance(MCP_REGISTRY["builtin_inprocess_service"], PluginWorkerProxy)

        manager = MCPManager()
        filtered = manager.get_available_services_filtered()
        assert filtered["builtin_inprocess_service"]["source"] == "builtin"
    finally:
        clear_registry()
        _cleanup_case_root(case_root)


def test_manager_marks_isolated_worker_source(monkeypatch) -> None:
    case_root = _make_case_root("test_mcp_plugin_isolation_ws24_001")
    clear_registry()
    try:
        plugin_root = case_root / "workspace" / "tools" / "plugins" / "simple_plugin"
        plugin_root.mkdir(parents=True, exist_ok=True)
        (plugin_root / "simple_plugin.py").write_text(
            """
import json

class SimplePluginAgent:
    async def handle_handoff(self, task):
        return json.dumps({"status": "ok", "tool_name": task.get("tool_name", "")}, ensure_ascii=False)
""".strip(),
            encoding="utf-8",
        )
        raw_manifest = {
            "name": "simple_isolated_plugin",
            "displayName": "Simple Isolated Plugin",
            "agentType": "mcp",
            "entryPoint": {
                "module": "simple_plugin",
                "class": "SimplePluginAgent",
            },
            "isolation": {"mode": "process"},
            "policy": {"scopes": ["read_workspace"]},
            "capabilities": {"invocationCommands": [{"command": "simple_ping"}]},
        }
        _write_manifest(
            plugin_root / "agent-manifest.json",
            _sign_manifest(raw_manifest, key_id="ut-key", secret="ut-secret"),
        )

        _set_plugin_trust_env(
            monkeypatch,
            allowlist=["simple_isolated_plugin"],
            key_id="ut-key",
            secret="ut-secret",
            scopes=["read_workspace"],
        )
        monkeypatch.setenv("EMBLA_PLUGIN_MANIFEST_DIRS", str(plugin_root))
        scan_and_register_mcp_agents(mcp_dir=str(case_root / "empty_mcp_root"))
        manager = MCPManager()
        filtered = manager.get_available_services_filtered()
        assert filtered["simple_isolated_plugin"]["source"] == "plugin_worker"
        assert filtered["simple_isolated_plugin"]["runtime_mode"] == "isolated_worker"
        assert filtered["simple_isolated_plugin"]["trust_policy"]["signature_verified"] is True
    finally:
        clear_registry()
        _cleanup_case_root(case_root)


def test_scan_rejects_unsigned_plugin_manifest_ws24_002(monkeypatch) -> None:
    case_root = _make_case_root("test_mcp_plugin_isolation_ws24_001")
    clear_registry()
    try:
        plugin_root = case_root / "workspace" / "tools" / "plugins" / "unsigned_plugin"
        plugin_root.mkdir(parents=True, exist_ok=True)
        (plugin_root / "unsigned_plugin.py").write_text(
            """
class UnsignedPlugin:
    async def handle_handoff(self, task):
        return {"status": "ok"}
""".strip(),
            encoding="utf-8",
        )
        _write_manifest(
            plugin_root / "agent-manifest.json",
            {
                "name": "unsigned_plugin",
                "displayName": "Unsigned Plugin",
                "agentType": "mcp_plugin",
                "entryPoint": {"module": "unsigned_plugin", "class": "UnsignedPlugin"},
                "isolation": {"mode": "process"},
                "policy": {"scopes": ["read_workspace"]},
                "capabilities": {"invocationCommands": [{"command": "unsigned_call"}]},
            },
        )

        _set_plugin_trust_env(
            monkeypatch,
            allowlist=["unsigned_plugin"],
            key_id="ut-key",
            secret="ut-secret",
            scopes=["read_workspace"],
        )
        monkeypatch.setenv("EMBLA_PLUGIN_MANIFEST_DIRS", str(plugin_root))

        registered = scan_and_register_mcp_agents(mcp_dir=str(case_root / "empty_mcp_root"))
        assert "unsigned_plugin" not in registered
        assert "unsigned_plugin" not in MCP_REGISTRY
        assert "unsigned_plugin" in REJECTED_PLUGIN_MANIFESTS
        assert "signature" in str(REJECTED_PLUGIN_MANIFESTS["unsigned_plugin"]["reason"])
    finally:
        clear_registry()
        _cleanup_case_root(case_root)


def test_scan_rejects_scope_not_allowlisted_ws24_002(monkeypatch) -> None:
    case_root = _make_case_root("test_mcp_plugin_isolation_ws24_001")
    clear_registry()
    try:
        plugin_root = case_root / "workspace" / "tools" / "plugins" / "bad_scope_plugin"
        plugin_root.mkdir(parents=True, exist_ok=True)
        (plugin_root / "bad_scope_plugin.py").write_text(
            """
class BadScopePlugin:
    async def handle_handoff(self, task):
        return {"status": "ok"}
""".strip(),
            encoding="utf-8",
        )
        manifest = {
            "name": "bad_scope_plugin",
            "displayName": "Bad Scope Plugin",
            "agentType": "mcp_plugin",
            "entryPoint": {"module": "bad_scope_plugin", "class": "BadScopePlugin"},
            "isolation": {"mode": "process"},
            "policy": {"scopes": ["host_process"]},
            "capabilities": {"invocationCommands": [{"command": "bad_scope"}]},
        }
        _write_manifest(
            plugin_root / "agent-manifest.json",
            _sign_manifest(manifest, key_id="ut-key", secret="ut-secret"),
        )
        _set_plugin_trust_env(
            monkeypatch,
            allowlist=["bad_scope_plugin"],
            key_id="ut-key",
            secret="ut-secret",
            scopes=["read_workspace", "tool_invoke"],
        )
        monkeypatch.setenv("EMBLA_PLUGIN_MANIFEST_DIRS", str(plugin_root))

        registered = scan_and_register_mcp_agents(mcp_dir=str(case_root / "empty_mcp_root"))
        assert "bad_scope_plugin" not in registered
        assert "bad_scope_plugin" in REJECTED_PLUGIN_MANIFESTS
        assert "forbidden_scope" in str(REJECTED_PLUGIN_MANIFESTS["bad_scope_plugin"]["reason"])
    finally:
        clear_registry()
        _cleanup_case_root(case_root)


def test_plugin_worker_timeout_and_circuit_ws24_003(monkeypatch) -> None:
    case_root = _make_case_root("test_mcp_plugin_isolation_ws24_001")
    clear_registry()
    reset_plugin_worker_runtime_metrics()
    try:
        plugin_root = case_root / "workspace" / "tools" / "plugins" / "slow_plugin"
        plugin_root.mkdir(parents=True, exist_ok=True)
        (plugin_root / "slow_plugin.py").write_text(
            """
import asyncio
import json

class SlowPluginAgent:
    async def handle_handoff(self, task):
        await asyncio.sleep(float(task.get("sleep_seconds") or 2.0))
        return json.dumps({"status": "ok", "tool_name": "slow_call"}, ensure_ascii=False)
""".strip(),
            encoding="utf-8",
        )
        manifest = {
            "name": "slow_isolated_plugin",
            "displayName": "Slow Isolated Plugin",
            "agentType": "mcp_plugin",
            "entryPoint": {"module": "slow_plugin", "class": "SlowPluginAgent"},
            "isolation": {
                "mode": "process",
                "timeout_seconds": 1,
                "max_failure_streak": 2,
                "cooldown_seconds": 120,
            },
            "policy": {"scopes": ["read_workspace"]},
            "capabilities": {"invocationCommands": [{"command": "slow_call"}]},
        }
        _write_manifest(
            plugin_root / "agent-manifest.json",
            _sign_manifest(manifest, key_id="ut-key", secret="ut-secret"),
        )
        _set_plugin_trust_env(
            monkeypatch,
            allowlist=["slow_isolated_plugin"],
            key_id="ut-key",
            secret="ut-secret",
            scopes=["read_workspace", "tool_invoke"],
        )
        monkeypatch.setenv("EMBLA_PLUGIN_MANIFEST_DIRS", str(plugin_root))
        scan_and_register_mcp_agents(mcp_dir=str(case_root / "empty_mcp_root"))

        proxy = MCP_REGISTRY["slow_isolated_plugin"]
        assert isinstance(proxy, PluginWorkerProxy)

        first = json.loads(asyncio.run(proxy.handle_handoff({"tool_name": "slow_call", "sleep_seconds": 2.0})))
        second = json.loads(asyncio.run(proxy.handle_handoff({"tool_name": "slow_call", "sleep_seconds": 2.0})))
        third = json.loads(asyncio.run(proxy.handle_handoff({"tool_name": "slow_call", "sleep_seconds": 0.0})))

        assert first["status"] == "error"
        assert "timeout" in str(first.get("message", "")).lower()
        assert second["status"] == "error"
        assert "timeout" in str(second.get("message", "")).lower()
        assert third["status"] == "error"
        assert "circuit open" in str(third.get("message", "")).lower()

        metrics = get_plugin_worker_runtime_metrics()["services"]["slow_isolated_plugin"]
        assert int(metrics["timeout_total"]) >= 2
        assert int(metrics["circuit_open_total"]) >= 1
    finally:
        clear_registry()
        reset_plugin_worker_runtime_metrics()
        _cleanup_case_root(case_root)


def test_plugin_worker_output_budget_rejected_ws24_003(monkeypatch) -> None:
    case_root = _make_case_root("test_mcp_plugin_isolation_ws24_001")
    clear_registry()
    try:
        plugin_root = case_root / "workspace" / "tools" / "plugins" / "output_plugin"
        plugin_root.mkdir(parents=True, exist_ok=True)
        (plugin_root / "output_plugin.py").write_text(
            """
class OutputPluginAgent:
    async def handle_handoff(self, task):
        return "X" * int(task.get("size") or 0)
""".strip(),
            encoding="utf-8",
        )
        manifest = {
            "name": "output_budget_plugin",
            "displayName": "Output Budget Plugin",
            "agentType": "mcp_plugin",
            "entryPoint": {"module": "output_plugin", "class": "OutputPluginAgent"},
            "isolation": {
                "mode": "process",
                "max_output_bytes": 4096,
            },
            "policy": {"scopes": ["read_workspace"]},
            "capabilities": {"invocationCommands": [{"command": "oversize"}]},
        }
        _write_manifest(
            plugin_root / "agent-manifest.json",
            _sign_manifest(manifest, key_id="ut-key", secret="ut-secret"),
        )
        _set_plugin_trust_env(
            monkeypatch,
            allowlist=["output_budget_plugin"],
            key_id="ut-key",
            secret="ut-secret",
            scopes=["read_workspace"],
        )
        monkeypatch.setenv("EMBLA_PLUGIN_MANIFEST_DIRS", str(plugin_root))
        scan_and_register_mcp_agents(mcp_dir=str(case_root / "empty_mcp_root"))

        proxy = MCP_REGISTRY["output_budget_plugin"]
        payload = json.loads(asyncio.run(proxy.handle_handoff({"tool_name": "oversize", "size": 10_000})))
        assert payload["status"] == "error"
        assert "output budget exceeded" in str(payload.get("message", "")).lower()
    finally:
        clear_registry()
        _cleanup_case_root(case_root)


def test_plugin_worker_reaps_stale_jobs_ws24_004(monkeypatch) -> None:
    case_root = _make_case_root("test_mcp_plugin_isolation_ws24_001")
    reset_plugin_worker_runtime_metrics()
    try:
        plugin_root = case_root / "plugin_runtime"
        plugin_root.mkdir(parents=True, exist_ok=True)
        (plugin_root / "fast_plugin.py").write_text(
            """
import json

class FastPluginAgent:
    async def handle_handoff(self, task):
        return json.dumps({"status": "ok", "message": "done"}, ensure_ascii=False)
""".strip(),
            encoding="utf-8",
        )

        class _FakeRegistry:
            def __init__(self) -> None:
                self.killed: list[tuple[str, str]] = []
                self.started: list[dict] = []
                self.ended: list[dict] = []

            def list_running(self):
                return [
                    SimpleNamespace(
                        job_root_id="job_stale_1",
                        command="python -m mcpserver.plugin_worker_runtime --module stale",
                        started_at=time.time() - 9_999,
                    )
                ]

            def kill_job(self, job_root_id: str, *, reason: str = "") -> bool:
                self.killed.append((job_root_id, reason))
                return True

            def register_start(self, *, call_id, command, root_pid, fencing_epoch):
                self.started.append(
                    {
                        "call_id": call_id,
                        "command": command,
                        "root_pid": root_pid,
                        "fencing_epoch": fencing_epoch,
                    }
                )
                return "job_active"

            def register_end(self, job_root_id, *, return_code, status, reason):
                self.ended.append(
                    {
                        "job_root_id": job_root_id,
                        "return_code": return_code,
                        "status": status,
                        "reason": reason,
                    }
                )

            def reap_orphaned_running_jobs(self, *, reason, max_epoch=None):
                return 0

        fake_registry = _FakeRegistry()
        monkeypatch.setattr(plugin_worker_module, "get_process_lineage_registry", lambda: fake_registry)

        proxy = PluginWorkerProxy(
            PluginWorkerSpec(
                service_name="fast_plugin_worker",
                module_name="fast_plugin",
                class_name="FastPluginAgent",
                timeout_seconds=5,
                stale_reap_grace_seconds=1,
                pythonpath_entries=[str(plugin_root)],
            )
        )

        payload = json.loads(asyncio.run(proxy.handle_handoff({"tool_name": "fast"})))
        assert payload["status"] == "ok"
        assert any(job_id == "job_stale_1" for job_id, _ in fake_registry.killed)
        assert len(fake_registry.started) == 1
        assert len(fake_registry.ended) == 1
    finally:
        reset_plugin_worker_runtime_metrics()
        _cleanup_case_root(case_root)
