from __future__ import annotations

from typing import Any, Dict

from system.execution_backend.base import ExecutionBackend
from system.execution_backend.runtime_policy import resolve_os_sandbox_runtime_policy
from system.git_worktree_sandbox import apply_workspace_path_overrides


class OsSandboxExecutionBackend(ExecutionBackend):
    name = "os_sandbox"
    service_name = "native"

    _OFFLINE_ENV = {
        "HTTP_PROXY": "",
        "HTTPS_PROXY": "",
        "ALL_PROXY": "",
        "NO_PROXY": "*",
        "http_proxy": "",
        "https_proxy": "",
        "all_proxy": "",
        "no_proxy": "*",
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "UV_OFFLINE": "1",
        "CARGO_NET_OFFLINE": "true",
    }

    @staticmethod
    def _clamp_timeout(raw_value: Any, *, default_seconds: int, max_seconds: int) -> int:
        try:
            resolved = int(raw_value) if raw_value is not None else int(default_seconds)
        except Exception:
            resolved = int(default_seconds)
        return max(1, min(int(max_seconds), resolved))

    def prepare_call(self, tool_name: str, call: Dict[str, Any], *, context, native_tool_executor) -> Dict[str, Any]:
        safe_call = dict(call) if isinstance(call, dict) else {}
        workspace_root = str(context.workspace_host_root or context.project_root or native_tool_executor.project_root).strip()
        policy = resolve_os_sandbox_runtime_policy(getattr(context, "execution_profile", "default"))
        if workspace_root:
            safe_call = apply_workspace_path_overrides(
                tool_name,
                safe_call,
                workspace_root,
                strict_absolute=True,
            )
            safe_call.setdefault("_session_workspace_root", workspace_root)
        safe_call.setdefault("_execution_backend", self.name)
        safe_call.setdefault("_execution_root", workspace_root or str(context.execution_root or native_tool_executor.project_root))
        safe_call.setdefault("_sandbox_policy", str(getattr(context, "sandbox_policy", "") or policy.profile_name))
        safe_call.setdefault("_network_policy", str(getattr(context, "network_policy", "") or ("enabled" if policy.network_enabled else "disabled")))
        safe_call.setdefault("_resource_profile", str(getattr(context, "resource_profile", "") or policy.resource_profile))

        if tool_name == "run_cmd":
            safe_call["timeout_seconds"] = self._clamp_timeout(
                safe_call.get("timeout_seconds"),
                default_seconds=policy.default_command_timeout_seconds,
                max_seconds=policy.max_command_timeout_seconds,
            )
            safe_call["_sandbox_network_enabled"] = bool(policy.network_enabled)
            safe_call["_sandbox_enforce_network_guard"] = bool(policy.enforce_network_guard)
            if not policy.network_enabled and policy.inject_offline_env:
                env = safe_call.get("_execution_env")
                env_map = dict(env) if isinstance(env, dict) else {}
                for key, value in self._OFFLINE_ENV.items():
                    env_map.setdefault(key, value)
                safe_call["_execution_env"] = env_map
        elif tool_name == "python_repl":
            safe_call["timeout_seconds"] = self._clamp_timeout(
                safe_call.get("timeout_seconds"),
                default_seconds=policy.default_python_timeout_seconds,
                max_seconds=policy.max_python_timeout_seconds,
            )
        elif tool_name == "sleep_and_watch":
            safe_call["timeout_seconds"] = self._clamp_timeout(
                safe_call.get("timeout_seconds"),
                default_seconds=policy.default_watch_timeout_seconds,
                max_seconds=policy.max_watch_timeout_seconds,
            )
        return safe_call

    async def execute_tool(self, tool_name: str, call: Dict[str, Any], *, context, native_tool_executor) -> str:
        del context
        return await native_tool_executor._execute_native_tool(tool_name, call)
