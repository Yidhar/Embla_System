from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Dict

if TYPE_CHECKING:
    from apiserver.native_tools import NativeToolExecutor
    from system.sandbox_context import SandboxContext


class ExecutionBackendError(RuntimeError):
    pass


class ExecutionBackendUnavailableError(ExecutionBackendError):
    pass


class ExecutionBackend(ABC):
    name = "base"
    service_name = "native"

    def prepare_call(
        self,
        tool_name: str,
        call: Dict[str, Any],
        *,
        context: "SandboxContext",
        native_tool_executor: "NativeToolExecutor",
    ) -> Dict[str, Any]:
        return dict(call) if isinstance(call, dict) else {}

    @abstractmethod
    async def execute_tool(
        self,
        tool_name: str,
        call: Dict[str, Any],
        *,
        context: "SandboxContext",
        native_tool_executor: "NativeToolExecutor",
    ) -> str:
        raise NotImplementedError
