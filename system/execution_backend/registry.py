from __future__ import annotations

from typing import Any, Dict

from system.boxlite.manager import probe_boxlite_runtime_readiness
from system.execution_backend.base import ExecutionBackend, ExecutionBackendUnavailableError
from system.execution_backend.boxlite_backend import BoxLiteExecutionBackend
from system.execution_backend.native_backend import NativeExecutionBackend
from system.sandbox_context import normalize_execution_backend


class _UnavailableExecutionBackend(ExecutionBackend):
    def __init__(self, *, name: str, reason: str) -> None:
        self.name = name
        self.service_name = name
        self._reason = str(reason or f"{name} runtime unavailable")

    def prepare_call(self, tool_name: str, call: Dict[str, Any], *, context, native_tool_executor) -> Dict[str, Any]:
        del tool_name, context, native_tool_executor
        return dict(call) if isinstance(call, dict) else {}

    async def execute_tool(self, tool_name: str, call: Dict[str, Any], *, context, native_tool_executor) -> str:
        del tool_name, call, context, native_tool_executor
        raise ExecutionBackendUnavailableError(self._reason)


class ExecutionBackendRegistry:
    def __init__(self) -> None:
        self._native_backend = NativeExecutionBackend()
        self._boxlite_backend = BoxLiteExecutionBackend()

    def resolve(self, context) -> ExecutionBackend:
        backend_name = normalize_execution_backend(getattr(context, "execution_backend", "native"))
        if backend_name == "boxlite":
            status = probe_boxlite_runtime_readiness(
                project_root=getattr(context, "project_root", ""),
                profile_name=str(getattr(context, "execution_profile", "default") or "default").strip() or "default",
            )
            if not bool(getattr(status, "available", False)):
                reason = str(getattr(status, "reason", "") or "boxlite runtime unavailable")
                return _UnavailableExecutionBackend(name="boxlite", reason=reason)
            return self._boxlite_backend
        return self._native_backend
