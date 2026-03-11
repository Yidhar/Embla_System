from __future__ import annotations

from typing import Any, Dict

from system.execution_backend.base import ExecutionBackend
from system.git_worktree_sandbox import apply_workspace_path_overrides


class NativeExecutionBackend(ExecutionBackend):
    name = "native"
    service_name = "native"

    def prepare_call(self, tool_name: str, call: Dict[str, Any], *, context, native_tool_executor) -> Dict[str, Any]:
        safe_call = dict(call) if isinstance(call, dict) else {}
        if context.workspace_host_root:
            safe_call = apply_workspace_path_overrides(tool_name, safe_call, context.workspace_host_root)
            safe_call.setdefault("_session_workspace_root", str(context.workspace_host_root))
        safe_call.setdefault("_execution_backend", self.name)
        safe_call.setdefault("_execution_root", str(context.execution_root or context.workspace_host_root or native_tool_executor.project_root))
        return safe_call

    async def execute_tool(self, tool_name: str, call: Dict[str, Any], *, context, native_tool_executor) -> str:
        del context
        return await native_tool_executor._execute_native_tool(tool_name, call)
