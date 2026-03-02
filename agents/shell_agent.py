"""Shell Agent — user-facing interaction layer.

Locked persona DNA. Read-only tools + routing via TaskRouterEngine.
The Shell can read everything but writes nothing.
Wraps the existing deterministic router to produce RouterDecision.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from agents.prompt_engine import PromptAssembler
from agents.router_engine import RouterDecision, RouterRequest, TaskRouterEngine

logger = logging.getLogger(__name__)


# ── Shell Tool Definitions ─────────────────────────────────────

SHELL_READONLY_TOOLS = [
    "read_file",
    "get_system_status",
    "search_memory",
    "list_tasks",
    "search_web",
]


def get_dispatch_to_core_definition() -> Dict[str, Any]:
    """Tool definition for routing complex tasks to Core."""
    return {
        "name": "dispatch_to_core",
        "description": (
            "Route a task to the Core agent for execution. "
            "Use this when the user's request requires code changes, deployments, "
            "analysis, or any operation that goes beyond simple information retrieval."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "goal": {
                    "type": "string",
                    "description": "Clear description of what needs to be accomplished.",
                },
                "context_summary": {
                    "type": "string",
                    "description": "Relevant context gathered from conversation and memory.",
                },
                "relevant_memories": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Memory references relevant to the task.",
                },
                "priority": {
                    "type": "string",
                    "enum": ["low", "normal", "high"],
                    "description": "Task priority.",
                },
            },
            "required": ["goal"],
        },
    }


@dataclass
class ShellAgentConfig:
    """Configuration for the Shell Agent."""

    persona_dna_path: str = "prompts/dna/shell_persona.md"
    readonly_tools: List[str] = field(default_factory=lambda: list(SHELL_READONLY_TOOLS))
    router_decision_log: Optional[str] = None  # path to JSONL log


class ShellAgent:
    """The Shell Agent sits between the user and the Core.

    Responsibilities:
        - Maintain locked persona (from DNA file)
        - Provide read-only tool access for information gathering
        - Route complex tasks to Core via TaskRouterEngine
        - Pass RouterDecision downstream (tool_profile, model_tier, prompt_profile)
    """

    def __init__(self, config: Optional[ShellAgentConfig] = None) -> None:
        self._config = config or ShellAgentConfig()
        self._persona_prompt: str = ""
        log_path = Path(self._config.router_decision_log) if self._config.router_decision_log else None
        self._router = TaskRouterEngine(decision_log=log_path)
        self._assembler = PromptAssembler()
        self._load_persona()

    @property
    def persona_prompt(self) -> str:
        return self._persona_prompt

    @property
    def tool_names(self) -> List[str]:
        return list(self._config.readonly_tools) + ["dispatch_to_core"]

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """Get all tool definitions for the Shell agent."""
        return [get_dispatch_to_core_definition()]

    def route(
        self,
        message: str,
        *,
        session_id: str = "",
        risk_level: str = "",
        complexity: str = "medium",
        requested_role: str = "",
    ) -> RouterDecision:
        """Route a user message through TaskRouterEngine.

        This is the deterministic routing step — produces a RouterDecision
        with delegation_intent, tool_profile, prompt_profile, model_tier.
        """
        request = RouterRequest(
            task_id=f"chat_{int(time.time() * 1000)}",
            description=message,
            estimated_complexity=complexity,
            requested_role=requested_role,
            risk_level=risk_level or "read_only",
            trace_id=f"shell_{uuid.uuid4().hex[:12]}",
            session_id=session_id,
        )
        return self._router.route(request)

    def dispatch_to_core(
        self,
        arguments: Dict[str, Any],
        *,
        session_id: str = "",
        risk_level: str = "write_repo",
    ) -> Dict[str, Any]:
        """Process a dispatch_to_core tool call via TaskRouterEngine.

        Returns a structured dict containing the RouterDecision
        that CoreAgent can consume.
        """
        goal = arguments.get("goal", "")
        decision = self.route(
            goal,
            session_id=session_id,
            risk_level=risk_level,
            complexity="high",
        )

        return {
            "dispatched": True,
            "goal": goal,
            "context_summary": arguments.get("context_summary", ""),
            "relevant_memories": arguments.get("relevant_memories", []),
            "priority": arguments.get("priority", "normal"),
            # RouterDecision fields for downstream agents
            "router_decision": decision.to_dict(),
            "delegation_intent": decision.delegation_intent,
            "tool_profile": list(decision.tool_profile),
            "prompt_profile": decision.prompt_profile,
            "model_tier": decision.selected_model_tier,
            "selected_role": decision.selected_role,
            "injection_mode": decision.injection_mode,
        }

    def should_dispatch(self, decision: RouterDecision) -> bool:
        """Determine whether Shell should dispatch to Core or respond directly.

        Returns True if the request requires Core execution (code changes,
        deployments, analysis, etc.). Returns False if Shell can handle
        it directly (chat, status queries, file reading).
        """
        intent = str(decision.delegation_intent or "").strip().lower()
        return intent in {"core_execution", "explicit_role_delegate"}

    def build_system_prompt(self) -> str:
        """Build the complete system prompt for the Shell agent using PromptAssembler."""
        behavior_rules = (
            "\n## 行为准则\n"
            "- 你可以使用只读工具获取信息：read_file, get_system_status, search_memory, list_tasks, search_web\n"
            "- 有任何需要执行的任务，使用 dispatch_to_core 工具转交给 Core Agent\n"
            "- 你**绝对不能**修改任何文件或系统状态\n"
        )
        try:
            return self._assembler.assemble(
                dna="shell_persona",
                extra_sections=[behavior_rules],
            )
        except Exception:
            # Fallback: use loaded persona if assembler fails
            parts: List[str] = []
            if self._persona_prompt:
                parts.append(self._persona_prompt)
            parts.append(behavior_rules)
            return "\n".join(parts)

    def _load_persona(self) -> None:
        """Load persona DNA from file (immutable, never modified at runtime)."""
        path = Path(self._config.persona_dna_path)
        if path.exists():
            self._persona_prompt = path.read_text(encoding="utf-8")
            logger.info("Loaded Shell persona DNA from %s", path)
        else:
            self._persona_prompt = ""
            logger.warning("Shell persona DNA not found at %s — using empty persona", path)


__all__ = ["ShellAgent", "ShellAgentConfig"]
