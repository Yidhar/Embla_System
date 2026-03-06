#!/usr/bin/env python3
"""Run WS28-023 smoke to validate isolated worker on a real MCP manifest."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator

from mcpserver.mcp_registry import (
    MANIFEST_CACHE,
    MCP_REGISTRY,
    clear_registry,
    get_service_statistics,
    scan_and_register_mcp_agents,
)
from mcpserver.plugin_manifest_policy import compute_manifest_signature
from mcpserver.plugin_worker import (
    PluginWorkerProxy,
    get_plugin_worker_runtime_metrics,
    reset_plugin_worker_runtime_metrics,
)


TASK_ID = "NGA-WS28-023"
SCENARIO = "plugin_worker_real_mcp_smoke"
REPORT_SCHEMA_VERSION = "ws28_023_plugin_worker_real_mcp_smoke.v1"
DEFAULT_AGENT_MANIFEST = Path("mcpserver/agent_weather_time/agent-manifest.json")
DEFAULT_OUTPUT = Path("scratch/reports/ws28_plugin_worker_real_mcp_smoke_ws28_023.json")
DEFAULT_SIGNING_KEY_ID = "ws28_023_smoke_key"
DEFAULT_SIGNING_SECRET = "ws28_023_smoke_secret"
DEFAULT_INVOKE_PAYLOAD = {
    "tool_name": "time",
    "city": "INVALID_CITY INVALID_CITY",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_unix(path: Path) -> str:
    return str(path).replace("\\", "/")


def _resolve_path(repo_root: Path, candidate: Path) -> Path:
    return candidate if candidate.is_absolute() else repo_root / candidate


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_json(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("manifest payload must be object")
    return payload


def _sanitize_plugin_name(value: str) -> str:
    raw = str(value or "").strip().lower()
    normalized = re.sub(r"[^a-z0-9_.-]+", "_", raw).strip("._-")
    if not normalized:
        normalized = "ws28_023_real_mcp_plugin"
    if not normalized[0].isalnum():
        normalized = f"p{normalized}"
    return normalized[:64]


def _parse_invoke_payload(text: str) -> Dict[str, Any]:
    normalized = str(text or "").strip()
    if not normalized:
        return dict(DEFAULT_INVOKE_PAYLOAD)
    parsed = json.loads(normalized)
    if not isinstance(parsed, dict):
        raise ValueError("invoke payload must be json object")
    return parsed


def _parse_worker_json_output(raw: str) -> Dict[str, Any]:
    text = str(raw or "").strip()
    if not text:
        return {}
    candidates = [text]
    first_brace = text.find("{")
    if first_brace >= 0:
        candidates.append(text[first_brace:])
    for line in reversed(text.splitlines()):
        normalized = line.strip()
        if normalized.startswith("{") and normalized.endswith("}"):
            candidates.append(normalized)
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except Exception:
            continue
        if isinstance(parsed, dict):
            return parsed
    return {}


def _build_signed_plugin_manifest(
    *,
    source_manifest: Dict[str, Any],
    plugin_name: str,
    signing_key_id: str,
    signing_secret: str,
    invocation_command: str,
) -> Dict[str, Any]:
    entry_point = source_manifest.get("entryPoint")
    if not isinstance(entry_point, dict):
        raise ValueError("source manifest missing entryPoint")
    module_name = str(entry_point.get("module") or "").strip()
    class_name = str(entry_point.get("class") or "").strip()
    if not module_name or not class_name:
        raise ValueError("source manifest missing entryPoint module/class")

    manifest: Dict[str, Any] = {
        "name": plugin_name,
        "displayName": f"WS28-023 Real MCP Smoke ({source_manifest.get('displayName') or plugin_name})",
        "version": "0.1.0",
        "description": "WS28-023 real MCP isolated worker smoke manifest",
        "author": "Embla System",
        "agentType": "mcp_plugin",
        "entryPoint": {
            "module": module_name,
            "class": class_name,
        },
        "capabilities": {
            "invocationCommands": [
                {
                    "command": invocation_command,
                    "description": "ws28_023 real mcp smoke command",
                    "example": "{\"tool_name\":\"time\"}",
                }
            ]
        },
        "isolation": {
            "mode": "process",
            "timeout_seconds": 20,
            "max_payload_bytes": 131072,
            "max_output_bytes": 262144,
            "max_memory_mb": 256,
            "cpu_time_seconds": 20,
            "max_failure_streak": 3,
            "cooldown_seconds": 10,
            "stale_reap_grace_seconds": 90,
        },
        "policy": {"scopes": ["read_workspace", "tool_invoke"]},
    }
    signature = compute_manifest_signature(manifest, secret=signing_secret)
    manifest["signature"] = {
        "algorithm": "hmac-sha256",
        "key_id": signing_key_id,
        "value": signature,
    }
    return manifest


@contextmanager
def _temporary_env(overrides: Dict[str, str]) -> Iterator[None]:
    snapshots: Dict[str, str | None] = {key: os.environ.get(key) for key in overrides}
    try:
        for key, value in overrides.items():
            os.environ[key] = str(value)
        yield
    finally:
        for key, old in snapshots.items():
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old


def _is_plugin_worker_failure(payload: Dict[str, Any]) -> bool:
    status = str(payload.get("status") or "").strip().lower()
    route = str(payload.get("route") or "").strip().lower()
    message = str(payload.get("message") or "").strip().lower()
    if status == "error" and route == "plugin_worker":
        return True
    failure_hints = (
        "plugin worker",
        "plugin bootstrap failed",
        "plugin call failed",
        "output budget exceeded",
    )
    return any(token in message for token in failure_hints)


def run_ws28_plugin_worker_real_mcp_smoke_ws28_023(
    *,
    repo_root: Path,
    source_agent_manifest: Path = DEFAULT_AGENT_MANIFEST,
    output_file: Path = DEFAULT_OUTPUT,
    invoke_payload: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    root = repo_root.resolve()
    source_manifest_path = _resolve_path(root, source_agent_manifest)
    output_path = _resolve_path(root, output_file)
    case_root = root / "scratch" / "runtime" / "ws28_023_plugin_worker_real_mcp_smoke" / uuid.uuid4().hex[:12]
    plugin_root = case_root / "workspace" / "tools" / "plugins" / "ws28_023_real_mcp_plugin"
    plugin_manifest_path = plugin_root / "agent-manifest.json"
    empty_mcp_root = case_root / "empty_mcp_root"
    invoke = dict(invoke_payload or DEFAULT_INVOKE_PAYLOAD)

    checks = {
        "source_manifest_exists": source_manifest_path.exists(),
        "source_manifest_parsed": False,
        "entrypoint_present": False,
        "plugin_manifest_written": False,
        "service_registered": False,
        "runtime_mode_isolated_worker": False,
        "service_is_plugin_worker_proxy": False,
        "isolated_worker_counter_positive": False,
        "invocation_json_parseable": False,
        "invocation_not_worker_failure": False,
        "runtime_metric_calls_recorded": False,
    }

    registered_services: list[str] = []
    registry_stats: Dict[str, Any] = {}
    invocation_raw = ""
    invocation_result: Dict[str, Any] = {}
    runtime_metrics: Dict[str, Any] = {}
    worker_service_name = ""
    error_text = ""

    if checks["source_manifest_exists"]:
        try:
            source_manifest = _read_json(source_manifest_path)
            checks["source_manifest_parsed"] = True
            entry_point = source_manifest.get("entryPoint")
            if isinstance(entry_point, dict):
                module_name = str(entry_point.get("module") or "").strip()
                class_name = str(entry_point.get("class") or "").strip()
                checks["entrypoint_present"] = bool(module_name and class_name)
            source_name = str(source_manifest.get("name") or "real_mcp").strip()
            worker_service_name = _sanitize_plugin_name(f"ws28_023_real_{source_name}")
            invocation_command = _sanitize_plugin_name(str(invoke.get("tool_name") or "ws28_real_smoke"))
            plugin_manifest = _build_signed_plugin_manifest(
                source_manifest=source_manifest,
                plugin_name=worker_service_name,
                signing_key_id=DEFAULT_SIGNING_KEY_ID,
                signing_secret=DEFAULT_SIGNING_SECRET,
                invocation_command=invocation_command,
            )
            plugin_root.mkdir(parents=True, exist_ok=True)
            plugin_manifest_path.write_text(
                json.dumps(plugin_manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            checks["plugin_manifest_written"] = True
            empty_mcp_root.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            error_text = f"prepare_failed:{exc}"
    else:
        error_text = "source_manifest_missing"

    if checks["plugin_manifest_written"]:
        env_overrides = {
            "EMBLA_PLUGIN_ALLOWLIST": worker_service_name,
            "EMBLA_PLUGIN_SIGNING_KEYS": json.dumps({DEFAULT_SIGNING_KEY_ID: DEFAULT_SIGNING_SECRET}, ensure_ascii=False),
            "EMBLA_PLUGIN_ALLOWED_SCOPES": "read_workspace,tool_invoke",
            "EMBLA_PLUGIN_MANIFEST_DIRS": str(plugin_root.resolve()),
        }
        try:
            clear_registry()
            reset_plugin_worker_runtime_metrics()
            with _temporary_env(env_overrides):
                registered_services = scan_and_register_mcp_agents(mcp_dir=str(empty_mcp_root))
                service = MCP_REGISTRY.get(worker_service_name)
                manifest_record = MANIFEST_CACHE.get(worker_service_name) if isinstance(MANIFEST_CACHE.get(worker_service_name), dict) else {}
                checks["service_registered"] = worker_service_name in registered_services and service is not None
                checks["runtime_mode_isolated_worker"] = (
                    str(manifest_record.get("_runtime_mode") or "").strip().lower() == "isolated_worker"
                )
                checks["service_is_plugin_worker_proxy"] = isinstance(service, PluginWorkerProxy)
                registry_stats = get_service_statistics()
                checks["isolated_worker_counter_positive"] = int(registry_stats.get("isolated_worker_services") or 0) >= 1
                if service is not None:
                    invocation_raw = asyncio.run(service.handle_handoff(invoke))
                    parsed = _parse_worker_json_output(invocation_raw)
                    if parsed:
                        invocation_result = parsed
                        checks["invocation_json_parseable"] = True
                        checks["invocation_not_worker_failure"] = not _is_plugin_worker_failure(parsed)
                runtime_metrics = get_plugin_worker_runtime_metrics()
                service_metrics = (
                    runtime_metrics.get("services", {}).get(worker_service_name, {})
                    if isinstance(runtime_metrics.get("services"), dict)
                    else {}
                )
                checks["runtime_metric_calls_recorded"] = int(service_metrics.get("calls_total") or 0) >= 1
        except Exception as exc:
            error_text = f"smoke_failed:{exc}"
        finally:
            clear_registry()
            reset_plugin_worker_runtime_metrics()

    passed = all(bool(value) for value in checks.values())
    report: Dict[str, Any] = {
        "task_id": TASK_ID,
        "scenario": SCENARIO,
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "repo_root": _to_unix(root),
        "source_manifest": _to_unix(source_manifest_path),
        "worker_service_name": worker_service_name,
        "passed": passed,
        "checks": checks,
        "registered_services": registered_services,
        "registry_stats": registry_stats,
        "invocation_payload": invoke,
        "invocation_result": invocation_result,
        "invocation_raw_preview": str(invocation_raw)[:1200],
        "runtime_metrics": runtime_metrics,
        "plugin_manifest_path": _to_unix(plugin_manifest_path),
    }
    if error_text:
        report["error"] = error_text

    _write_json(output_path, report)
    report["output_file"] = _to_unix(output_path)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run WS28-023 plugin worker real MCP smoke")
    parser.add_argument("--repo-root", type=Path, default=Path("."), help="Repository root path")
    parser.add_argument(
        "--agent-manifest",
        type=Path,
        default=DEFAULT_AGENT_MANIFEST,
        help="Real MCP source manifest path (default: weather_time)",
    )
    parser.add_argument(
        "--invoke-payload",
        type=str,
        default=json.dumps(DEFAULT_INVOKE_PAYLOAD, ensure_ascii=False),
        help="JSON payload passed to handle_handoff",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output report path")
    parser.add_argument("--strict", action="store_true", help="Return non-zero when checks fail")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    invoke_payload = _parse_invoke_payload(args.invoke_payload)
    report = run_ws28_plugin_worker_real_mcp_smoke_ws28_023(
        repo_root=args.repo_root,
        source_agent_manifest=args.agent_manifest,
        output_file=args.output,
        invoke_payload=invoke_payload,
    )
    print(
        json.dumps(
            {
                "passed": bool(report.get("passed")),
                "checks": report.get("checks", {}),
                "output": report.get("output_file"),
            },
            ensure_ascii=False,
        )
    )
    if args.strict and not bool(report.get("passed")):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
