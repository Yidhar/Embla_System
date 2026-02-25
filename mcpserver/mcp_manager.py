"""MCP manager with in-process and mcporter-backed external dispatch."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from mcpserver.mcp_registry import MANIFEST_CACHE, MCP_REGISTRY, auto_register_mcp
from system.config import logger


_TOOL_CALL_INTERNAL_KEYS = {
    "agentType",
    "service_name",
    "tool_name",
    "_tool_call_id",
    "mcp_tool_timeout_ms",
    "mcpToolTimeoutMs",
}
_CODEX_MCP_SERVICES = {"codex-cli", "codex-mcp"}
_CODEX_MCP_TOOLS = {"ask-codex", "brainstorm", "help", "ping"}
_DEFAULT_MCP_TOOL_TIMEOUT_MS = 36_000_000


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
        self._ensure_registry_initialized()
        normalized_call = self._normalize_tool_call(tool_call)
        normalized_service = self._resolve_requested_service(service_name, normalized_call)
        tool_name = str(normalized_call.get("tool_name", "")).strip()
        call_id = str(normalized_call.get("_tool_call_id") or f"mcp_{uuid.uuid4().hex[:8]}")
        started = time.monotonic()

        logger.info(
            "[MCPManager] call start id=%s service=%s tool=%s payload_keys=%s",
            call_id,
            normalized_service or "<missing>",
            tool_name or "<missing>",
            sorted(normalized_call.keys()),
        )

        if not normalized_service:
            return self._json_error("service_name is required", tool_name=tool_name, call_id=call_id)

        local_agent = MCP_REGISTRY.get(normalized_service)
        if local_agent is not None:
            try:
                local_result = await local_agent.handle_handoff(normalized_call)
                self._log_call_finish(
                    call_id=call_id,
                    service_name=normalized_service,
                    tool_name=tool_name,
                    route="local",
                    started=started,
                    raw_result=local_result,
                    ok=True,
                )
                return local_result
            except Exception as exc:
                logger.warning(
                    "[MCPManager] local call failed id=%s service=%s tool=%s error=%s",
                    call_id,
                    normalized_service,
                    tool_name,
                    exc,
                )
                if not self._is_codex_route(normalized_service, tool_name):
                    self._log_call_finish(
                        call_id=call_id,
                        service_name=normalized_service,
                        tool_name=tool_name,
                        route="local",
                        started=started,
                        raw_result=f"call failed: {exc}",
                        ok=False,
                    )
                    return self._json_error(
                        f"call failed: {exc}",
                        service_name=normalized_service,
                        tool_name=tool_name,
                        call_id=call_id,
                    )
                logger.info(
                    "[MCPManager] codex local route failed, degrade to mcporter id=%s service=%s tool=%s",
                    call_id,
                    normalized_service,
                    tool_name,
                )

        external_result = await self._call_external_mcporter_service(normalized_service, normalized_call)
        if external_result is not None:
            status, preview = self._extract_status_and_preview(external_result)
            self._log_call_finish(
                call_id=call_id,
                service_name=normalized_service,
                tool_name=tool_name,
                route="mcporter",
                started=started,
                raw_result=preview,
                ok=status != "error",
            )
            return external_result

        not_found_payload = self._build_not_found_payload(normalized_service, tool_name)
        self._log_call_finish(
            call_id=call_id,
            service_name=normalized_service,
            tool_name=tool_name,
            route="none",
            started=started,
            raw_result="service not found",
            ok=False,
        )
        return self._json_error(f"service not found: {normalized_service}", **not_found_payload, call_id=call_id)

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
            runtime_mode = str(manifest.get("_runtime_mode") or "inprocess")
            payload = {
                "displayName": manifest.get("displayName", name),
                "description": manifest.get("description", ""),
                "tools": manifest.get("capabilities", {}).get("invocationCommands", []),
                "source": "plugin_worker" if runtime_mode == "isolated_worker" else "builtin",
                "runtime_mode": runtime_mode,
            }
            if runtime_mode == "isolated_worker":
                payload["worker_limits"] = dict(manifest.get("_worker_limits") or {})
                payload["trust_policy"] = dict(manifest.get("_trust_policy") or {})
            result[name] = payload

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
            runtime_mode = str(manifest.get("_runtime_mode") or "inprocess")
            lines.append(f"- 服务名(service_name): {name}")
            lines.append(f"  显示名: {display_name}")
            lines.append(f"  描述: {desc}")
            if runtime_mode == "isolated_worker":
                lines.append("  运行模式: isolated_worker")
                trust = manifest.get("_trust_policy") or {}
                key_id = str(trust.get("signature_key_id") or "").strip()
                if key_id:
                    lines.append(f"  信任链: signed+allowlist (key_id={key_id})")
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

    def _ensure_registry_initialized(self) -> None:
        if self._initialized:
            return
        try:
            auto_register_mcp()
        except Exception as exc:
            logger.warning("[MCPManager] auto_register_mcp failed: %s", exc)
        finally:
            self._initialized = True

    @staticmethod
    def _resolve_requested_service(service_name: str, tool_call: Dict[str, Any]) -> str:
        normalized_service = str(service_name or tool_call.get("service_name") or "").strip()
        if normalized_service:
            return normalized_service
        tool_name = str(tool_call.get("tool_name", "")).strip()
        if tool_name in _CODEX_MCP_TOOLS:
            return "codex-cli"
        return ""

    def _normalize_tool_call(self, tool_call: Dict[str, Any]) -> Dict[str, Any]:
        normalized = dict(tool_call or {})
        nested_args = normalized.get("arguments")
        if isinstance(nested_args, dict):
            for key, value in nested_args.items():
                normalized.setdefault(key, value)

        tool_name = str(normalized.get("tool_name", "")).strip()
        if tool_name == "ask-codex":
            prompt = normalized.get("prompt")
            message = normalized.get("message")

            if (prompt is None or prompt == "") and isinstance(message, str) and message.strip():
                normalized["prompt"] = message
                prompt = message

            if (prompt is None or prompt == "") and isinstance(nested_args, dict):
                nested_prompt = nested_args.get("prompt")
                nested_message = nested_args.get("message")
                if isinstance(nested_prompt, str) and nested_prompt.strip():
                    normalized["prompt"] = nested_prompt
                elif isinstance(nested_message, str) and nested_message.strip():
                    normalized["prompt"] = nested_message

            normalized.pop("message", None)
            if isinstance(normalized.get("arguments"), dict):
                normalized["arguments"].pop("message", None)
                if "prompt" in normalized and "prompt" not in normalized["arguments"]:
                    normalized["arguments"]["prompt"] = normalized["prompt"]

            normalized.setdefault("sandboxMode", "workspace-write")
            normalized.setdefault("approvalPolicy", "on-failure")

        return normalized

    @staticmethod
    def _is_codex_route(service_name: str, tool_name: str) -> bool:
        return service_name in _CODEX_MCP_SERVICES or tool_name in _CODEX_MCP_TOOLS

    async def _call_external_mcporter_service(self, service_name: str, tool_call: Dict[str, Any]) -> str | None:
        """Call an external MCP service configured in ~/.mcporter/config.json."""
        tool_name = str(tool_call.get("tool_name", "")).strip()
        if not tool_name:
            return self._json_error("tool_name is required for external MCP service")

        external_services = self._load_external_services()
        if not external_services:
            return None

        resolved_service = self._resolve_external_service_name(service_name, tool_name, external_services)
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
        process_env = self._build_external_env(
            service_name=service_name,
            resolved_service=resolved_service,
            tool_name=tool_name,
            tool_call=tool_call,
        )

        logger.info(
            "[MCPManager] external call start service=%s resolved_service=%s tool=%s cmd=%s",
            service_name,
            resolved_service,
            tool_name,
            cmd,
        )

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=process_env,
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
                exit_code=process.returncode,
            )

        return json.dumps(
            {
                "status": "ok",
                "service_name": service_name,
                "resolved_service_name": resolved_service,
                "tool_name": tool_name,
                "result": output_text,
                "stderr": error_text,
                "route": "mcporter",
            },
            ensure_ascii=False,
        )

    def _build_external_args(self, tool_call: Dict[str, Any], *, tool_name: str) -> Dict[str, Any]:
        payload = {k: v for k, v in tool_call.items() if k not in _TOOL_CALL_INTERNAL_KEYS}

        # Support both flattened args and MCP-style nested `arguments`.
        nested_args = payload.get("arguments")
        if isinstance(nested_args, dict):
            payload.pop("arguments", None)
            for key, value in nested_args.items():
                if key not in payload:
                    payload[key] = value

        if tool_name == "ask-codex":
            prompt = payload.get("prompt")
            message = payload.get("message")
            if (prompt is None or prompt == "") and isinstance(message, str) and message.strip():
                payload["prompt"] = message
            payload.pop("message", None)
            payload.setdefault("sandboxMode", "workspace-write")
            payload.setdefault("approvalPolicy", "on-failure")
        return payload

    def _resolve_external_service_name(
        self,
        service_name: str,
        tool_name: str,
        services: Dict[str, Any],
    ) -> str | None:
        requested = str(service_name or "").strip()
        lowered_lookup = {name.lower(): name for name in services.keys()}

        if self._is_codex_route(requested, tool_name):
            # Prefer codex-cli if present; codex-mcp remains fallback alias.
            preferred = lowered_lookup.get("codex-cli")
            if preferred:
                return preferred

        if requested in services:
            return requested

        by_lower = lowered_lookup.get(requested.lower())
        if by_lower:
            return by_lower

        for alias in self._service_aliases.get(requested, []):
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

    def _build_external_env(
        self,
        *,
        service_name: str,
        resolved_service: str,
        tool_name: str,
        tool_call: Dict[str, Any],
    ) -> Dict[str, str] | None:
        if not self._is_codex_route(service_name, tool_name) and not self._is_codex_route(resolved_service, tool_name):
            return None

        env = os.environ.copy()
        env["MCP_TOOL_TIMEOUT"] = self._resolve_codex_timeout_ms(tool_call, env)
        return env

    @staticmethod
    def _resolve_codex_timeout_ms(tool_call: Dict[str, Any], env: Dict[str, str]) -> str:
        for key in ("mcp_tool_timeout_ms", "mcpToolTimeoutMs"):
            normalized = MCPManager._normalize_timeout_ms(tool_call.get(key))
            if normalized:
                return normalized

        normalized_env = MCPManager._normalize_timeout_ms(env.get("MCP_TOOL_TIMEOUT"))
        if normalized_env:
            return normalized_env

        return str(_DEFAULT_MCP_TOOL_TIMEOUT_MS)

    @staticmethod
    def _normalize_timeout_ms(value: Any) -> str:
        if value is None:
            return ""
        try:
            parsed = int(str(value).strip())
        except (TypeError, ValueError):
            return ""
        if parsed <= 0:
            return ""
        return str(parsed)

    @staticmethod
    def _resolve_mcporter_prefix() -> List[str]:
        if shutil.which("mcporter"):
            return ["mcporter"]
        npx_cmd = shutil.which("npx") or shutil.which("npx.cmd")
        if npx_cmd:
            return [npx_cmd, "-y", "mcporter@latest"]
        return []

    def _build_not_found_payload(self, service_name: str, tool_name: str) -> Dict[str, Any]:
        return {
            "service_name": service_name,
            "tool_name": tool_name,
            "local_services": sorted(list(MCP_REGISTRY.keys())),
            "external_services": sorted(list(self._load_external_services().keys())),
            "aliases": self._service_aliases.get(service_name, []),
        }

    @staticmethod
    def _extract_status_and_preview(raw_result: str) -> Tuple[str, str]:
        status = "ok"
        preview = raw_result
        if not isinstance(raw_result, str):
            return status, str(raw_result)
        try:
            parsed = json.loads(raw_result)
            if isinstance(parsed, dict):
                status = str(parsed.get("status", status))
                if "message" in parsed:
                    preview = str(parsed.get("message", ""))
                elif "result" in parsed:
                    preview = str(parsed.get("result", ""))
        except Exception:
            preview = raw_result
        return status, MCPManager._shorten(preview)

    def _log_call_finish(
        self,
        *,
        call_id: str,
        service_name: str,
        tool_name: str,
        route: str,
        started: float,
        raw_result: Any,
        ok: bool,
    ) -> None:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        preview = self._shorten(raw_result)
        if ok:
            logger.info(
                "[MCPManager] call done id=%s service=%s tool=%s route=%s elapsed_ms=%s result=%s",
                call_id,
                service_name,
                tool_name,
                route,
                elapsed_ms,
                preview,
            )
        else:
            logger.warning(
                "[MCPManager] call failed id=%s service=%s tool=%s route=%s elapsed_ms=%s error=%s",
                call_id,
                service_name,
                tool_name,
                route,
                elapsed_ms,
                preview,
            )

    @staticmethod
    def _shorten(value: Any, limit: int = 400) -> str:
        text = str(value)
        if len(text) <= limit:
            return text
        return text[:limit] + "..."

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
