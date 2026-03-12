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

from agents.prompt_engine import PromptAssembler, get_system_prompts_root
from agents.router_engine import RouterDecision, RouterRequest, TaskRouterEngine
from agents.shell_tools import get_shell_tool_definitions, handle_shell_tool, is_shell_tool_supported

logger = logging.getLogger(__name__)


# ── Shell Tool Definitions ─────────────────────────────────────

SHELL_READONLY_TOOLS = [
    "memory_read",
    "memory_list",
    "memory_grep",
    "memory_search",
    "get_system_status",
    "list_tasks",
    "search_web",
]
HIGH_RISK_LEVELS = {"deploy", "secrets", "self_modify"}
COMPLEXITY_HINT_VALUES = {"trivial", "standard", "complex"}
COMPLEXITY_HINT_FROM_COMPLEXITY = {
    "low": "trivial",
    "trivial": "trivial",
    "small": "trivial",
    "medium": "standard",
    "high": "standard",
    "normal": "standard",
    "epic": "complex",
    "complex": "complex",
}


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
                "intent_type": {
                    "type": "string",
                    "enum": ["development", "ops", "analysis"],
                    "description": "Execution intent classification for Core routing.",
                },
                "target_repo": {
                    "type": "string",
                    "enum": ["self", "external"],
                    "description": "Whether the task targets framework self-maintenance or external workspace.",
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
                "complexity_hint": {
                    "type": "string",
                    "enum": ["trivial", "standard", "complex"],
                    "description": (
                        "Core execution route hint. "
                        "Use trivial for small single-file edits, standard for normal tasks, "
                        "complex for cross-domain or multi-agent tasks."
                    ),
                },
                "target_files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of expected target files for this task.",
                },
                "estimated_changed_lines": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "Optional estimate of changed lines.",
                },
                "requested_tools": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional tools expected to be used during execution.",
                },
            },
            "required": ["goal"],
        },
    }


@dataclass
class ShellAgentConfig:
    """Configuration for the Shell Agent."""

    persona_dna_path: str = str(get_system_prompts_root() / "dna" / "shell_persona.md")
    prompts_root: str = str(get_system_prompts_root())
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
        self._assembler = PromptAssembler(prompts_root=self._config.prompts_root)
        self._load_persona()

    @property
    def persona_prompt(self) -> str:
        return self._persona_prompt

    @property
    def tool_names(self) -> List[str]:
        return list(self._config.readonly_tools) + ["dispatch_to_core"]

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """Get all tool definitions for the Shell agent.

        Returns canonical read-only tool schemas + dispatch_to_core routing tool.
        """
        return get_shell_tool_definitions() + [get_dispatch_to_core_definition()]

    def execute_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        *,
        session_id: str = "",
    ) -> Dict[str, Any]:
        """Execute a Shell tool call.

        Routes read-only tools to handle_shell_tool(),
        dispatch_to_core to the routing pipeline.
        """
        if tool_name == "dispatch_to_core":
            return self.dispatch_to_core(arguments, session_id=session_id)

        if tool_name in self._config.readonly_tools or is_shell_tool_supported(tool_name):
            return handle_shell_tool(tool_name, arguments)

        return {"error": f"Unknown tool: {tool_name}", "status": "error"}

    def route(
        self,
        message: str,
        *,
        session_id: str = "",
        risk_level: str = "",
        complexity: str = "medium",
        complexity_hint: str = "",
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
            complexity_hint=self._normalize_complexity_hint(
                complexity_hint,
                fallback_complexity=complexity,
            ),
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
        intent_type = str(arguments.get("intent_type", "") or "").strip().lower()
        if intent_type not in {"development", "ops", "analysis"}:
            intent_type = "analysis" if str(risk_level or "").strip().lower() == "read_only" else "development"
        target_repo = str(arguments.get("target_repo", "") or "").strip().lower()
        if target_repo not in {"self", "external"}:
            target_repo = "external"
        complexity_hint = self._infer_dispatch_complexity_hint(arguments, goal=goal, risk_level=risk_level)
        decision = self.route(
            goal,
            session_id=session_id,
            risk_level=risk_level,
            complexity=self._complexity_level_from_hint(complexity_hint),
            complexity_hint=complexity_hint,
        )
        target_files_raw = arguments.get("target_files")
        target_files: List[str] = []
        if isinstance(target_files_raw, list):
            for item in target_files_raw:
                text = str(item or "").strip()
                if text:
                    target_files.append(text)
        estimated_changed_lines = arguments.get("estimated_changed_lines")
        try:
            estimated_changed_lines_int = max(0, int(estimated_changed_lines))
        except Exception:
            estimated_changed_lines_int = 0
        requested_tools_raw = arguments.get("requested_tools")
        requested_tools: List[str] = []
        if isinstance(requested_tools_raw, list):
            for item in requested_tools_raw:
                text = str(item or "").strip()
                if text:
                    requested_tools.append(text)

        return {
            "dispatched": True,
            "goal": goal,
            "intent_type": intent_type,
            "target_repo": target_repo,
            "context_summary": arguments.get("context_summary", ""),
            "relevant_memories": arguments.get("relevant_memories", []),
            "priority": arguments.get("priority", "normal"),
            "complexity_hint": complexity_hint,
            "target_files": target_files,
            "estimated_changed_lines": estimated_changed_lines_int,
            "requested_tools": requested_tools,
            "fast_track_candidate": bool(getattr(decision, "core_route", "") == "fast_track"),
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
        try:
            body = self._assembler.assemble(
                blocks=[
                    "agents/shell/blocks/shell_behavior_readonly_tools.md",
                    "agents/shell/blocks/shell_behavior_dispatch_to_core.md",
                    "agents/shell/blocks/shell_behavior_no_writes.md",
                ],
            )
            parts = [self._persona_prompt.strip(), body.strip()]
            return "\n\n".join(part for part in parts if part).strip()
        except Exception:
            return self._persona_prompt.strip()

    def _load_persona(self) -> None:
        """Load persona DNA from file (immutable, never modified at runtime)."""
        path = Path(self._config.persona_dna_path)
        if path.exists():
            self._persona_prompt = path.read_text(encoding="utf-8")
            logger.info("Loaded Shell persona DNA from %s", path)
        else:
            self._persona_prompt = ""
            logger.warning("Shell persona DNA not found at %s — using empty persona", path)

    @staticmethod
    def _normalize_complexity_hint(raw_hint: str, *, fallback_complexity: str = "") -> str:
        normalized = str(raw_hint or "").strip().lower()
        if normalized in COMPLEXITY_HINT_VALUES:
            return normalized

        fallback = str(fallback_complexity or "").strip().lower()
        mapped = COMPLEXITY_HINT_FROM_COMPLEXITY.get(fallback, "standard")
        if mapped in COMPLEXITY_HINT_VALUES:
            return mapped
        return "standard"

    @staticmethod
    def _complexity_level_from_hint(hint: str) -> str:
        normalized = str(hint or "").strip().lower()
        if normalized == "trivial":
            return "low"
        if normalized == "complex":
            return "epic"
        return "high"

    def _infer_dispatch_complexity_hint(self, arguments: Dict[str, Any], *, goal: str, risk_level: str) -> str:
        explicit_hint = arguments.get("complexity_hint")
        if isinstance(explicit_hint, str):
            normalized = self._normalize_complexity_hint(explicit_hint)
            if normalized in COMPLEXITY_HINT_VALUES:
                return normalized

        normalized_risk = str(risk_level or "").strip().lower()
        if normalized_risk in HIGH_RISK_LEVELS:
            return "complex"

        target_files_raw = arguments.get("target_files")
        target_files: List[str] = []
        if isinstance(target_files_raw, list):
            for item in target_files_raw:
                text = str(item or "").strip()
                if text:
                    target_files.append(text)
        estimated_changed_lines = arguments.get("estimated_changed_lines")
        try:
            changed_lines = max(0, int(estimated_changed_lines))
        except Exception:
            changed_lines = 0
        if target_files and len(set(target_files)) == 1 and 0 < changed_lines <= 10:
            return "trivial"
        if target_files and len(set(target_files)) > 1:
            return "complex"
        if changed_lines > 10:
            return "complex"

        goal_text = str(goal or "").strip().lower()
        trivial_markers = (
            "typo",
            "拼写",
            "单行",
            "single line",
            "小修",
            "small fix",
            "formatting",
            "格式",
        )
        complex_markers = (
            "跨模块",
            "cross module",
            "multi file",
            "多文件",
            "重构",
            "architecture",
            "migrate",
            "并行",
        )
        if any(marker in goal_text for marker in complex_markers):
            return "complex"
        if len(goal_text) <= 120 and any(marker in goal_text for marker in trivial_markers):
            return "trivial"
        return "standard"


__all__ = ["ShellAgent", "ShellAgentConfig"]
