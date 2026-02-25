#!/usr/bin/env python3
"""WS24-005 plugin isolation chaos suite."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping

from mcpserver.mcp_registry import (
    MCP_REGISTRY,
    REJECTED_PLUGIN_MANIFESTS,
    clear_registry,
    scan_and_register_mcp_agents,
)
from mcpserver.plugin_manifest_policy import compute_manifest_signature
from mcpserver.plugin_worker import get_plugin_worker_runtime_metrics, reset_plugin_worker_runtime_metrics


def _write_manifest(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def _write_plugin_module(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


def _sign_manifest(payload: Mapping[str, Any], *, key_id: str, secret: str) -> Dict[str, Any]:
    manifest = dict(payload)
    manifest["signature"] = {
        "algorithm": "hmac-sha256",
        "key_id": key_id,
        "value": compute_manifest_signature(manifest, secret=secret),
    }
    return manifest


def _set_env(mapping: Mapping[str, str]) -> Dict[str, str | None]:
    previous: Dict[str, str | None] = {}
    for key, value in mapping.items():
        previous[key] = os.environ.get(key)
        os.environ[key] = str(value)
    return previous


def _restore_env(previous: Mapping[str, str | None]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _default_env_for_case(*, plugin_root: Path, allowlist: List[str], scopes: List[str]) -> Dict[str, str]:
    return {
        "NAGA_PLUGIN_MANIFEST_DIRS": str(plugin_root),
        "NAGA_PLUGIN_ALLOWLIST": ",".join(allowlist),
        "NAGA_PLUGIN_SIGNING_KEYS": json.dumps({"chaos-key": "chaos-secret"}, ensure_ascii=False),
        "NAGA_PLUGIN_ALLOWED_SCOPES": ",".join(scopes),
    }


def _make_case_root(base_dir: Path) -> Path:
    root = base_dir / f"plugin_isolation_chaos_ws24_005_{uuid.uuid4().hex[:12]}"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _run_unsigned_manifest_case(case_root: Path) -> Dict[str, Any]:
    clear_registry()
    reset_plugin_worker_runtime_metrics()
    plugin_root = case_root / "unsigned_manifest"
    _write_plugin_module(
        plugin_root / "unsigned_plugin.py",
        """
class UnsignedPluginAgent:
    async def handle_handoff(self, task):
        return {"status": "ok"}
""",
    )
    _write_manifest(
        plugin_root / "agent-manifest.json",
        {
            "name": "chaos_unsigned_plugin",
            "displayName": "Chaos Unsigned Plugin",
            "agentType": "mcp_plugin",
            "entryPoint": {"module": "unsigned_plugin", "class": "UnsignedPluginAgent"},
            "isolation": {"mode": "process"},
            "policy": {"scopes": ["read_workspace"]},
            "capabilities": {"invocationCommands": [{"command": "chaos_unsigned"}]},
        },
    )
    env_backup = _set_env(
        _default_env_for_case(
            plugin_root=plugin_root,
            allowlist=["chaos_unsigned_plugin"],
            scopes=["read_workspace", "tool_invoke"],
        )
    )
    try:
        registered = scan_and_register_mcp_agents(mcp_dir=str(case_root / "empty_mcp_root"))
    finally:
        _restore_env(env_backup)

    rejected = dict(REJECTED_PLUGIN_MANIFESTS.get("chaos_unsigned_plugin") or {})
    reason = str(rejected.get("reason") or "")
    passed = ("chaos_unsigned_plugin" not in registered) and ("signature" in reason)
    return {
        "case_id": "C1",
        "name": "unsigned_manifest_rejected",
        "passed": passed,
        "reasons": [] if passed else ["unsigned_manifest_not_rejected"],
        "audit": {
            "registered_services": list(registered),
            "rejected_reason": reason,
        },
    }


def _run_forbidden_scope_case(case_root: Path) -> Dict[str, Any]:
    clear_registry()
    reset_plugin_worker_runtime_metrics()
    plugin_root = case_root / "forbidden_scope"
    _write_plugin_module(
        plugin_root / "scope_plugin.py",
        """
class ForbiddenScopePluginAgent:
    async def handle_handoff(self, task):
        return {"status": "ok"}
""",
    )
    manifest = _sign_manifest(
        {
            "name": "chaos_forbidden_scope_plugin",
            "displayName": "Chaos Forbidden Scope Plugin",
            "agentType": "mcp_plugin",
            "entryPoint": {"module": "scope_plugin", "class": "ForbiddenScopePluginAgent"},
            "isolation": {"mode": "process"},
            "policy": {"scopes": ["host_process"]},
            "capabilities": {"invocationCommands": [{"command": "chaos_forbidden_scope"}]},
        },
        key_id="chaos-key",
        secret="chaos-secret",
    )
    _write_manifest(plugin_root / "agent-manifest.json", manifest)
    env_backup = _set_env(
        _default_env_for_case(
            plugin_root=plugin_root,
            allowlist=["chaos_forbidden_scope_plugin"],
            scopes=["read_workspace", "tool_invoke"],
        )
    )
    try:
        registered = scan_and_register_mcp_agents(mcp_dir=str(case_root / "empty_mcp_root"))
    finally:
        _restore_env(env_backup)

    rejected = dict(REJECTED_PLUGIN_MANIFESTS.get("chaos_forbidden_scope_plugin") or {})
    reason = str(rejected.get("reason") or "")
    passed = ("chaos_forbidden_scope_plugin" not in registered) and ("forbidden_scope" in reason)
    return {
        "case_id": "C2",
        "name": "forbidden_scope_rejected",
        "passed": passed,
        "reasons": [] if passed else ["forbidden_scope_not_rejected"],
        "audit": {
            "registered_services": list(registered),
            "rejected_reason": reason,
        },
    }


def _run_payload_budget_case(case_root: Path) -> Dict[str, Any]:
    clear_registry()
    reset_plugin_worker_runtime_metrics()
    plugin_root = case_root / "payload_budget"
    _write_plugin_module(
        plugin_root / "payload_plugin.py",
        """
import json

class PayloadPluginAgent:
    async def handle_handoff(self, task):
        return json.dumps({"status": "ok", "message": "payload accepted"}, ensure_ascii=False)
""",
    )
    manifest = _sign_manifest(
        {
            "name": "chaos_payload_budget_plugin",
            "displayName": "Chaos Payload Budget Plugin",
            "agentType": "mcp_plugin",
            "entryPoint": {"module": "payload_plugin", "class": "PayloadPluginAgent"},
            "isolation": {"mode": "process", "max_payload_bytes": 80},
            "policy": {"scopes": ["read_workspace"]},
            "capabilities": {"invocationCommands": [{"command": "chaos_payload"}]},
        },
        key_id="chaos-key",
        secret="chaos-secret",
    )
    _write_manifest(plugin_root / "agent-manifest.json", manifest)
    env_backup = _set_env(
        _default_env_for_case(
            plugin_root=plugin_root,
            allowlist=["chaos_payload_budget_plugin"],
            scopes=["read_workspace", "tool_invoke"],
        )
    )
    try:
        registered = scan_and_register_mcp_agents(mcp_dir=str(case_root / "empty_mcp_root"))
        proxy = MCP_REGISTRY.get("chaos_payload_budget_plugin")
        if proxy is None:
            return {
                "case_id": "C3",
                "name": "payload_budget_guard",
                "passed": False,
                "reasons": ["payload_budget_plugin_not_registered"],
                "audit": {"registered_services": list(registered)},
            }
        raw = asyncio.run(proxy.handle_handoff({"tool_name": "chaos_payload", "blob": "X" * 10_000}))
        payload = json.loads(raw)
        metrics = get_plugin_worker_runtime_metrics()
    finally:
        _restore_env(env_backup)

    service_metrics = dict(metrics.get("services", {}).get("chaos_payload_budget_plugin") or {})
    passed = (
        payload.get("status") == "error"
        and "payload budget exceeded" in str(payload.get("message", "")).lower()
        and int(service_metrics.get("payload_reject_total") or 0) >= 1
    )
    return {
        "case_id": "C3",
        "name": "payload_budget_guard",
        "passed": passed,
        "reasons": [] if passed else ["payload_budget_guard_failed"],
        "audit": {
            "tool_result": payload,
            "service_metrics": service_metrics,
        },
    }


def _run_timeout_circuit_case(case_root: Path) -> Dict[str, Any]:
    clear_registry()
    reset_plugin_worker_runtime_metrics()
    plugin_root = case_root / "timeout_circuit"
    _write_plugin_module(
        plugin_root / "timeout_plugin.py",
        """
import asyncio
import json

class TimeoutPluginAgent:
    async def handle_handoff(self, task):
        await asyncio.sleep(float(task.get("sleep_seconds") or 2.0))
        return json.dumps({"status": "ok", "message": "done"}, ensure_ascii=False)
""",
    )
    manifest = _sign_manifest(
        {
            "name": "chaos_timeout_plugin",
            "displayName": "Chaos Timeout Plugin",
            "agentType": "mcp_plugin",
            "entryPoint": {"module": "timeout_plugin", "class": "TimeoutPluginAgent"},
            "isolation": {
                "mode": "process",
                "timeout_seconds": 1,
                "max_failure_streak": 1,
                "cooldown_seconds": 30,
            },
            "policy": {"scopes": ["read_workspace"]},
            "capabilities": {"invocationCommands": [{"command": "chaos_timeout"}]},
        },
        key_id="chaos-key",
        secret="chaos-secret",
    )
    _write_manifest(plugin_root / "agent-manifest.json", manifest)
    env_backup = _set_env(
        _default_env_for_case(
            plugin_root=plugin_root,
            allowlist=["chaos_timeout_plugin"],
            scopes=["read_workspace", "tool_invoke"],
        )
    )
    try:
        registered = scan_and_register_mcp_agents(mcp_dir=str(case_root / "empty_mcp_root"))
        proxy = MCP_REGISTRY.get("chaos_timeout_plugin")
        if proxy is None:
            return {
                "case_id": "C4",
                "name": "timeout_and_circuit",
                "passed": False,
                "reasons": ["timeout_plugin_not_registered"],
                "audit": {"registered_services": list(registered)},
            }
        first = json.loads(asyncio.run(proxy.handle_handoff({"tool_name": "chaos_timeout", "sleep_seconds": 2.0})))
        second = json.loads(asyncio.run(proxy.handle_handoff({"tool_name": "chaos_timeout", "sleep_seconds": 0.1})))
        metrics = get_plugin_worker_runtime_metrics()
    finally:
        _restore_env(env_backup)

    service_metrics = dict(metrics.get("services", {}).get("chaos_timeout_plugin") or {})
    passed = (
        first.get("status") == "error"
        and "timeout" in str(first.get("message", "")).lower()
        and second.get("status") == "error"
        and "circuit open" in str(second.get("message", "")).lower()
        and int(service_metrics.get("timeout_total") or 0) >= 1
        and int(service_metrics.get("circuit_open_total") or 0) >= 1
    )
    return {
        "case_id": "C4",
        "name": "timeout_and_circuit",
        "passed": passed,
        "reasons": [] if passed else ["timeout_or_circuit_guard_failed"],
        "audit": {
            "first_result": first,
            "second_result": second,
            "service_metrics": service_metrics,
        },
    }


def run_plugin_isolation_chaos_suite_ws24_005(
    *,
    output_file: Path,
    keep_temp: bool = False,
    scratch_root: Path = Path("scratch/runtime"),
) -> Dict[str, Any]:
    started_at = time.time()
    case_root = _make_case_root(scratch_root)
    case_results: List[Dict[str, Any]] = []
    rejected_snapshot: Dict[str, Any] = {}
    clear_registry()
    reset_plugin_worker_runtime_metrics()

    try:
        case_results.append(_run_unsigned_manifest_case(case_root))
        case_results.append(_run_forbidden_scope_case(case_root))
        case_results.append(_run_payload_budget_case(case_root))
        case_results.append(_run_timeout_circuit_case(case_root))
        rejected_snapshot = dict(REJECTED_PLUGIN_MANIFESTS)
    finally:
        clear_registry()
        reset_plugin_worker_runtime_metrics()
        if not keep_temp:
            shutil.rmtree(case_root, ignore_errors=True)

    failed_cases = [str(item.get("case_id") or "") for item in case_results if not bool(item.get("passed"))]
    passed = len(failed_cases) == 0
    report = {
        "task_id": "NGA-WS24-005",
        "scenario": "plugin_isolation_chaos_suite",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(time.time() - started_at, 4),
        "passed": passed,
        "failed_cases": failed_cases,
        "case_root": str(case_root).replace("\\", "/"),
        "case_results": case_results,
        "audit": {
            "rejected_plugin_manifests": rejected_snapshot,
        },
    }
    target = output_file
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run WS24-005 plugin isolation chaos suite")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("scratch/reports/plugin_isolation_chaos_ws24_005.json"),
        help="Output report path",
    )
    parser.add_argument("--keep-temp", action="store_true", help="Keep temporary runtime folders for debugging")
    parser.add_argument(
        "--scratch-root",
        type=Path,
        default=Path("scratch/runtime"),
        help="Scratch runtime root",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_plugin_isolation_chaos_suite_ws24_005(
        output_file=args.output,
        keep_temp=bool(args.keep_temp),
        scratch_root=args.scratch_root,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if bool(report.get("passed")) else 2


if __name__ == "__main__":
    raise SystemExit(main())
