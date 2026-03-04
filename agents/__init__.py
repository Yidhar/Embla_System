"""Brain-layer public contracts (`agents` is canonical runtime namespace)."""

from agents.contract_runtime import (
    CoreExecutionContractInput,
    build_core_execution_contract_payload,
    build_core_execution_messages,
)
from agents.core_agent import CoreAgent, CoreAgentConfig
from agents.dev_agent import DevAgent, DevAgentConfig
from agents.expert_agent import ExpertAgent, ExpertAgentConfig
from agents.meta_agent import DispatchReceipt, Goal, MetaAgentRuntime, ReflectionResult, SubTask, TaskFeedback
from agents.pipeline import run_multi_agent_pipeline
from agents.prompt_engine import PromptAssembler
from agents.review_agent import ReviewAgent, ReviewAgentConfig, ReviewResult
from agents.router_engine import RouterDecision, RouterRequest, TaskRouterEngine
from agents.runtime.mini_loop import MiniLoopConfig
from agents.shell_agent import ShellAgent
from agents.tool_loop import convert_structured_tool_calls, get_agentic_tool_definitions, run_agentic_loop

__all__ = [
    "CoreExecutionContractInput",
    "build_core_execution_contract_payload",
    "build_core_execution_messages",
    "CoreAgent",
    "CoreAgentConfig",
    "ExpertAgent",
    "ExpertAgentConfig",
    "DevAgent",
    "DevAgentConfig",
    "MetaAgentRuntime",
    "Goal",
    "SubTask",
    "TaskFeedback",
    "ReflectionResult",
    "DispatchReceipt",
    "PromptAssembler",
    "MiniLoopConfig",
    "ReviewAgent",
    "ReviewAgentConfig",
    "ReviewResult",
    "TaskRouterEngine",
    "RouterRequest",
    "RouterDecision",
    "ShellAgent",
    "run_multi_agent_pipeline",
    "get_agentic_tool_definitions",
    "convert_structured_tool_calls",
    "run_agentic_loop",  # legacy — kept for backward compat
]
