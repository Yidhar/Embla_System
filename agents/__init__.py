"""Brain-layer public contracts (`agents` is canonical runtime namespace)."""

from __future__ import annotations

from importlib import import_module
from typing import Any, Dict, Tuple

_ATTR_EXPORTS: Dict[str, Tuple[str, str]] = {
    "CoreExecutionContractInput": ("agents.contract_runtime", "CoreExecutionContractInput"),
    "build_core_execution_contract_payload": ("agents.contract_runtime", "build_core_execution_contract_payload"),
    "build_core_execution_messages": ("agents.contract_runtime", "build_core_execution_messages"),
    "CoreAgent": ("agents.core_agent", "CoreAgent"),
    "CoreAgentConfig": ("agents.core_agent", "CoreAgentConfig"),
    "ExpertAgent": ("agents.expert_agent", "ExpertAgent"),
    "ExpertAgentConfig": ("agents.expert_agent", "ExpertAgentConfig"),
    "DevAgent": ("agents.dev_agent", "DevAgent"),
    "DevAgentConfig": ("agents.dev_agent", "DevAgentConfig"),
    "MetaAgentRuntime": ("agents.meta_agent", "MetaAgentRuntime"),
    "Goal": ("agents.meta_agent", "Goal"),
    "SubTask": ("agents.meta_agent", "SubTask"),
    "TaskFeedback": ("agents.meta_agent", "TaskFeedback"),
    "ReflectionResult": ("agents.meta_agent", "ReflectionResult"),
    "DispatchReceipt": ("agents.meta_agent", "DispatchReceipt"),
    "PromptAssembler": ("agents.prompt_engine", "PromptAssembler"),
    "MiniLoopConfig": ("agents.runtime.mini_loop", "MiniLoopConfig"),
    "ReviewAgent": ("agents.review_agent", "ReviewAgent"),
    "ReviewAgentConfig": ("agents.review_agent", "ReviewAgentConfig"),
    "ReviewResult": ("agents.review_agent", "ReviewResult"),
    "TaskRouterEngine": ("agents.router_engine", "TaskRouterEngine"),
    "RouterRequest": ("agents.router_engine", "RouterRequest"),
    "RouterDecision": ("agents.router_engine", "RouterDecision"),
    "ShellAgent": ("agents.shell_agent", "ShellAgent"),
    "run_multi_agent_pipeline": ("agents.pipeline", "run_multi_agent_pipeline"),
    "get_agentic_tool_definitions": ("agents.tool_loop", "get_agentic_tool_definitions"),
    "convert_structured_tool_calls": ("agents.tool_loop", "convert_structured_tool_calls"),
    "run_agentic_loop": ("agents.tool_loop", "run_agentic_loop"),
}

_MODULE_EXPORTS = {
    "pipeline": "agents.pipeline",
}

__all__ = list(_ATTR_EXPORTS.keys())


def __getattr__(name: str) -> Any:
    module_name = _MODULE_EXPORTS.get(name)
    if module_name:
        module = import_module(module_name)
        globals()[name] = module
        return module

    target = _ATTR_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name = target
    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__) | set(_MODULE_EXPORTS))
