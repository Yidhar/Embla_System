"""MCP manager with in-process and mcporter-backed external dispatch."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from mcpserver.mcp_registry import MANIFEST_CACHE, MCP_REGISTRY
from system.config import logger


_TOOL_CALL_INTERNAL_KEYS = {"agentType", "service_name", "tool_name", "_tool_call_id"}


class MCPManager:
    """Route MCP calls to local agents first, then external mcporter services."""

    def __init__(self) -> None:
        self._initialized = False
        env_config_path = os.getenv("MCPORTER_CONFIG_PATH", "").strip()
        if env_config_path:
            self._mcporter_config_path = Path(env_config_path).expanduser()
        else:
            self._mcporter_config_path = Path.home() / ".mcporter" / "config.json"
        self._service_aliases: Dict[str, List[str]] = {
            "codex-cli": ["codex-cli", "codex-mcp"],
            "codex-mcp": ["codex-mcp", "codex-cli"],
        }

    async def unified_call(self, service_name: str, tool_call: Dict[str, Any]) -> str:
        """Unified MCP call entrypoint."""
        normalized_service = str(service_name or "").strip()
        if not normalized_service:
            return self._json_error("service_name is required")

        local_agent = MCP_REGISTRY.get(normalized_service)
        if local_agent is not None:
            try:
                return await local_agent.handle_handoff(tool_call)
            except Exception as exc:
                logger.error("[MCPManager] local call failed: service=%s error=%s", normalized_service, exc)
                return self._json_error(f"call failed: {exc}")

        external_result = await self._call_external_mcporter_service(normalized_service, tool_call)
        if external_result is not None:
            return external_result
        return self._json_error(f"service not found: {normalized_service}")

    def get_available_services(self) -> List[str]:
        """Return all currently available service names."""
        services = list(MCP_REGISTRY.keys())
        external = [name for name in self._load_external_services().keys() if name not in MCP_REGISTRY]
        services.extend(external)
        return services

    def get_available_services_filtered(self) -> Dict[str, Any]:
        """Return service metadata for local and external services."""
        result: Dict[str, Any] = {}
        for name in MCP_REGISTRY:
            manifest = MANIFEST_CACHE.get(name, {})
            result[name] = {
                "displayName": manifest.get("displayName", name),
                "description": manifest.get("description", ""),
                "tools": manifest.get("capabilities", {}).get("invocationCommands", []),
                "source": "builtin",
            }

        for name, cfg in self._load_external_services().items():
            if name in result:
                continue
            cmd = str(cfg.get("command", "")).strip()
            args = cfg.get("args", [])
            args_text = " ".join(str(x) for x in args if x is not None)
            result[name] = {
                "displayName": name,
                "description": f"{cmd} {args_text}".strip(),
                "tools": [],
                "source": "mcporter",
            }
        return result

    def format_available_services(self) -> str:
        """Format available services for prompt injection."""
        lines: List[str] = []

        for name, manifest in MANIFEST_CACHE.items():
            display_name = manifest.get("displayName", name)
            desc = manifest.get("description", "")
            tools = manifest.get("capabilities", {}).get("invocationCommands", [])
            lines.append(f"- 服务名(service_name): {name}")
            lines.append(f"  显示名: {display_name}")
            lines.append(f"  描述: {desc}")
            for tool in tools:
                cmd = tool.get("command", "")
                tool_desc = str(tool.get("description", "")).split("\n")[0]
                example = tool.get("example", "")
                lines.append(f"  工具: {cmd} - {tool_desc}")
                if example:
                    lines.append(f"  示例: {example}")
            lines.append("")

        external_services = self._load_external_services()
        for name, cfg in external_services.items():
            if name in MANIFEST_CACHE:
                continue
            cmd = str(cfg.get("command", "")).strip()
            args = cfg.get("args", [])
            args_text = " ".join(str(x) for x in args if x is not None)
            lines.append(f"- 服务名(service_name): {name}")
            lines.append(f"  显示名: {name}")
            lines.append("  描述: 外部 mcporter 服务")
            lines.append(f"  启动命令: {cmd} {args_text}".strip())
            lines.append("  工具: 运行时通过 `mcporter list --schema` 发现")
            lines.append("")
        return "\n".join(lines)

    async def cleanup(self) -> None:
        """Cleanup hook."""
        return None

    async def _call_external_mcporter_service(self, service_name: str, tool_call: Dict[str, Any]) -> str | None:
        """Call an external MCP service configured in ~/.mcporter/config.json."""
        tool_name = str(tool_call.get("tool_name", "")).strip()
        if not tool_name:
            return self._json_error("tool_name is required for external MCP service")

        external_services = self._load_external_services()
        if not external_services:
            return None

        resolved_service = self._resolve_external_service_name(service_name, external_services)
        if not resolved_service:
            return None

        command_prefix = self._resolve_mcporter_prefix()
        if not command_prefix:
            return self._json_error("mcporter not available (install via npm or keep npx in PATH)")

        payload = self._build_external_args(tool_call, tool_name=tool_name)
        selector = f"{resolved_service}.{tool_name}"
        cmd = [
            *command_prefix,
            "call",
            "--config",
            str(self._mcporter_config_path),
            selector,
            "--output",
            "text",
            "--args",
            json.dumps(payload, ensure_ascii=False),
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()
        except FileNotFoundError:
            return self._json_error("mcporter command not found")
        except Exception as exc:
            logger.error("[MCPManager] external call failed before execution: service=%s error=%s", service_name, exc)
            return self._json_error(f"external call failed: {exc}")

        output_text = stdout.decode("utf-8", errors="replace").strip()
        error_text = stderr.decode("utf-8", errors="replace").strip()
        if process.returncode != 0:
            detail = error_text or output_text or f"exit_code={process.returncode}"
            return self._json_error(
                f"external call failed: {detail}",
                service_name=service_name,
                resolved_service_name=resolved_service,
                tool_name=tool_name,
            )

        return json.dumps(
            {
                "status": "ok",
                "service_name": service_name,
                "resolved_service_name": resolved_service,
                "tool_name": tool_name,
                "result": output_text,
                "stderr": error_text,
            },
            ensure_ascii=False,
        )

    def _build_external_args(self, tool_call: Dict[str, Any], *, tool_name: str) -> Dict[str, Any]:
        payload = {k: v for k, v in tool_call.items() if k not in _TOOL_CALL_INTERNAL_KEYS}
        if tool_name == "ask-codex":
            prompt = payload.get("prompt")
            message = payload.get("message")
            if (prompt is None or prompt == "") and isinstance(message, str) and message.strip():
                payload["prompt"] = message
            payload.pop("message", None)
        return payload

    def _resolve_external_service_name(self, service_name: str, services: Dict[str, Any]) -> str | None:
        if service_name in services:
            return service_name

        lowered_lookup = {name.lower(): name for name in services.keys()}
        by_lower = lowered_lookup.get(service_name.lower())
        if by_lower:
            return by_lower

        for alias in self._service_aliases.get(service_name, []):
            if alias in services:
                return alias
            alias_by_lower = lowered_lookup.get(alias.lower())
            if alias_by_lower:
                return alias_by_lower
        return None

    def _load_external_services(self) -> Dict[str, Any]:
        path = self._mcporter_config_path
        if not path.exists():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        servers = raw.get("mcpServers", {})
        return servers if isinstance(servers, dict) else {}

    @staticmethod
    def _resolve_mcporter_prefix() -> List[str]:
        if shutil.which("mcporter"):
            return ["mcporter"]
        npx_cmd = shutil.which("npx") or shutil.which("npx.cmd")
        if npx_cmd:
            return [npx_cmd, "-y", "mcporter@latest"]
        return []

    @staticmethod
    def _json_error(message: str, **kwargs: Any) -> str:
        payload = {"status": "error", "message": message}
        payload.update(kwargs)
        return json.dumps(payload, ensure_ascii=False)


_MCP_MANAGER: Optional[MCPManager] = None


def get_mcp_manager() -> MCPManager:
    global _MCP_MANAGER
    if _MCP_MANAGER is None:
        _MCP_MANAGER = MCPManager()
    return _MCP_MANAGER
