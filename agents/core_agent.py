"""Core Agent — central orchestrator consuming RouterDecision.

Locked Values DNA. Decomposes goals into capability domains, respects
RouterDecision's tool_profile / prompt_profile / model_tier.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from agents.contract_runtime import CoreExecutionContractInput
from agents.meta_agent import Goal, MetaAgentRuntime, SubTask
from agents.prompt_engine import PromptAssembler
from agents.runtime.agent_session import AgentSessionStore
from agents.runtime.mailbox import AgentMailbox
from agents.runtime.parent_tools import handle_parent_tool_call
from agents.runtime.task_board import TaskBoardEngine

logger = logging.getLogger(__name__)


# ── Expert Domain Mapping ──────────────────────────────────────

EXPERT_DOMAINS = {
    "backend": ["python", "api", "server", "database", "sql", "后端", "接口", "数据库"],
    "frontend": ["vue", "react", "css", "html", "ui", "前端", "界面", "组件"],
    "ops": ["nginx", "docker", "k8s", "deploy", "运维", "部署", "监控"],
    "testing": ["test", "pytest", "测试", "验证", "质量"],
    "docs": ["doc", "readme", "文档", "注释", "说明"],
}

# Maps prompt_profile from RouterDecision → prompt template path
PROMPT_PROFILE_MAP = {
    "core_exec_ops": "agents/core_exec/core_exec_ops.md",
    "core_exec_dev": "agents/core_exec/core_exec_dev.md",
    "core_exec_general": "agents/core_exec/core_exec_base.md",
    "shell_readonly_research": "agents/shell/shell_readonly_research.md",
    "shell_readonly_general": "agents/shell/shell_readonly_general.md",
    "explicit_role_delegate": "agents/shell/explicit_role_delegate.md",
    "shell_general": "agents/core_exec/core_exec_base.md",
}
FAST_TRACK_BLOCKED_TOOLS = {
    "run_command",
    "exec_shell",
    "run_cmd",
    "os_bash",
    "python_repl",
    "write_config",
    "delete_file",
}
FAST_TRACK_ALLOWED_TOOLS = {
    "read_file",
    "write_file",
    "search_keyword",
    "list_files",
    "file_ast_skeleton",
    "file_ast_chunk_read",
    "git_status",
    "git_diff",
    "artifact_reader",
}
FAST_TRACK_PROTECTED_PREFIXES = (
    "core/security/",
    "system/dna/",
)
FAST_TRACK_PROTECTED_EXACT = {
    ".env",
    "config.json",
}
FAST_TRACK_MAX_FILES = 1
FAST_TRACK_MAX_CHANGED_LINES = 10
FAST_TRACK_HIGH_RISK_LEVELS = {"deploy", "secrets", "self_modify"}


@dataclass
class CoreAgentConfig:
    """Configuration for the Core Agent."""

    values_dna_path: str = "prompts/dna/core_values.md"
    prompts_root: str = "system/prompts"
    max_experts: int = 5
    expert_domains: Dict[str, List[str]] = field(default_factory=lambda: dict(EXPERT_DOMAINS))


class CoreAgent:
    """Core Agent orchestrates the main execution pipeline.

    Consumes RouterDecision from ShellAgent to determine:
        - tool_profile → which tools Experts/Devs can use
        - prompt_profile → which prompt template to load
        - selected_model_tier → which LLM tier for execution
        - delegation_intent → execution mode (core_execution, etc.)
    """

    def __init__(
        self,
        *,
        config: Optional[CoreAgentConfig] = None,
        store: Optional[AgentSessionStore] = None,
        mailbox: Optional[AgentMailbox] = None,
        task_board_engine: Optional[TaskBoardEngine] = None,
    ) -> None:
        self._config = config or CoreAgentConfig()
        self._store = store or AgentSessionStore(db_path=":memory:")
        self._mailbox = mailbox or AgentMailbox(db_path=":memory:")
        self._task_board = task_board_engine
        self._values_prompt: str = ""
        self._meta_runtime = MetaAgentRuntime()
        self._assembler = PromptAssembler(prompts_root=self._config.prompts_root)
        self._load_values()

    @property
    def values_prompt(self) -> str:
        return self._values_prompt

    @property
    def max_experts(self) -> int:
        try:
            return max(1, int(self._config.max_experts))
        except Exception:
            return 1

    def decompose_goal(self, dispatch: Dict[str, Any]) -> Dict[str, Any]:
        """Decompose a dispatched goal into expert assignments.

        Accepts the dispatch dict from ShellAgent.dispatch_to_core(),
        which includes RouterDecision fields.
        """
        goal_desc = dispatch.get("goal", "")
        router_decision = dispatch.get("router_decision", {})
        tool_profile = dispatch.get("tool_profile", [])
        prompt_profile = dispatch.get("prompt_profile", "")
        model_tier = dispatch.get("model_tier", "primary")
        delegation_intent = dispatch.get("delegation_intent", "core_execution")
        complexity_hint = self._normalize_complexity_hint(
            dispatch.get("complexity_hint", router_decision.get("complexity_hint", "standard"))
        )
        core_route = str(
            dispatch.get("core_route", router_decision.get("core_route", "standard"))
        ).strip() or "standard"

        goal = Goal(
            goal_id=f"g-{id(goal_desc) % 100000:05d}",
            description=goal_desc,
        )

        # Use existing heuristic decomposition
        subtasks = self._meta_runtime.decompose_goal(goal)

        # Map subtasks to expert domains, passing router context
        expert_assignments = self._map_to_experts(
            subtasks,
            router_tool_profile=tool_profile,
            prompt_profile=prompt_profile,
            model_tier=model_tier,
        )

        return {
            "goal_id": goal.goal_id,
            "original_goal": goal_desc,
            "delegation_intent": delegation_intent,
            "model_tier": model_tier,
            "prompt_profile": prompt_profile,
            "router_tool_profile": tool_profile,
            "complexity_hint": complexity_hint,
            "core_route": core_route,
            "target_repo": str(dispatch.get("target_repo") or "external").strip().lower() or "external",
            "router_decision": router_decision,
            "expert_assignments": expert_assignments,
            "subtask_count": len(subtasks),
        }

    def plan_execution_route(self, dispatch: Dict[str, Any]) -> Dict[str, Any]:
        """Select Core execution route: fast_track or standard.

        Fast-Track is enabled only when all hard constraints pass.
        """
        router_decision = dispatch.get("router_decision") if isinstance(dispatch.get("router_decision"), dict) else {}
        goal_text = str(dispatch.get("goal") or "").strip()
        risk_level = str(dispatch.get("risk_level") or router_decision.get("risk_level") or "").strip().lower()
        complexity_hint = self._normalize_complexity_hint(
            dispatch.get("complexity_hint", router_decision.get("complexity_hint", "standard"))
        )

        target_files = self._normalize_string_list(dispatch.get("target_files"))
        estimated_changed_lines = self._safe_non_negative_int(dispatch.get("estimated_changed_lines"))
        requested_tools = self._normalize_string_list(dispatch.get("requested_tools"))
        router_tools = self._normalize_string_list(dispatch.get("tool_profile"))

        reason_codes: List[str] = []
        if complexity_hint != "trivial":
            reason_codes.append("FAST_TRACK_HINT_NOT_TRIVIAL")
        if risk_level in FAST_TRACK_HIGH_RISK_LEVELS:
            reason_codes.append("FAST_TRACK_HIGH_RISK")
        if target_files and len(set(target_files)) > FAST_TRACK_MAX_FILES:
            reason_codes.append("FAST_TRACK_MULTI_FILE_SCOPE")
        if estimated_changed_lines > FAST_TRACK_MAX_CHANGED_LINES:
            reason_codes.append("FAST_TRACK_LINE_LIMIT_EXCEEDED")
        if any(self._is_protected_path(path) for path in target_files):
            reason_codes.append("FAST_TRACK_PROTECTED_PATH")
        if self._looks_like_config_change(goal_text):
            reason_codes.append("FAST_TRACK_CONFIG_CHANGE")
        if any(self._normalize_tool_name(tool) in FAST_TRACK_BLOCKED_TOOLS for tool in requested_tools):
            reason_codes.append("FAST_TRACK_BLOCKED_TOOL_REQUEST")

        fast_track_eligible = len(reason_codes) == 0
        selected_route = "fast_track" if fast_track_eligible else "standard"
        fast_track_tools = self._build_fast_track_tool_subset(router_tools)
        return {
            "route": selected_route,
            "complexity_hint": complexity_hint,
            "fast_track_eligible": bool(fast_track_eligible),
            "reason_codes": reason_codes,
            "max_files": int(FAST_TRACK_MAX_FILES),
            "max_changed_lines": int(FAST_TRACK_MAX_CHANGED_LINES),
            "protected_paths": list(FAST_TRACK_PROTECTED_PREFIXES) + sorted(FAST_TRACK_PROTECTED_EXACT),
            "blocked_tools": sorted(FAST_TRACK_BLOCKED_TOOLS),
            "tool_subset": fast_track_tools,
            "risk_level": risk_level,
        }

    def build_contract_input(self, dispatch: Dict[str, Any], *, session_id: str = "") -> CoreExecutionContractInput:
        """Build a CoreExecutionContractInput from dispatch context.

        This allows integration with the existing execution contract system.
        """
        return CoreExecutionContractInput(
            contract_stage="seed",
            session_id=session_id,
            goal=dispatch.get("goal", ""),
            scope_hint=dispatch.get("context_summary", ""),
            shell_context_summary=dispatch.get("context_summary", ""),
        )

    def spawn_experts(
        self,
        decomposition: Dict[str, Any],
        *,
        core_execution_session_id: str = "core",
        pipeline_id: str = "",
    ) -> List[Dict[str, Any]]:
        """Spawn Expert agents based on decomposition result."""
        results = []
        target_repo = str(decomposition.get("target_repo") or "external").strip().lower()
        for assignment in decomposition.get("expert_assignments", []):
            metadata: Dict[str, Any] = {}
            normalized_pipeline_id = str(pipeline_id or "").strip()
            if normalized_pipeline_id:
                metadata["pipeline_id"] = normalized_pipeline_id
            spawn_args: Dict[str, Any] = {
                "role": "expert",
                "task_description": assignment.get("scope", ""),
                "prompt_blocks": assignment.get("prompt_blocks", []),
                "tool_subset": assignment.get("tool_subset", []),
                "metadata": metadata,
            }
            if str(assignment.get("agent_type") or "").strip():
                spawn_args["agent_type"] = str(assignment.get("agent_type") or "").strip()
            if target_repo == "self":
                spawn_args["workspace_mode"] = "worktree"
            result = handle_parent_tool_call(
                "spawn_child_agent",
                spawn_args,
                parent_session_id=core_execution_session_id,
                store=self._store,
                mailbox=self._mailbox,
            )
            result["expert_type"] = assignment.get("expert_type", "general")
            result["scope"] = assignment.get("scope", "")
            result["model_tier"] = assignment.get("model_tier", "primary")
            results.append(result)
        return results

    def collect_reports(self, core_execution_session_id: str = "core", *, pipeline_id: str = "") -> List[Dict[str, Any]]:
        """Collect completion reports from all Expert children."""
        children = self._store.list_children(core_execution_session_id)
        normalized_pipeline_id = str(pipeline_id or "").strip()
        if normalized_pipeline_id:
            children = [
                child
                for child in children
                if str(child.metadata.get("pipeline_id") or "").strip() == normalized_pipeline_id
            ]
        reports = []
        for child in children:
            status = child.to_status_summary()
            msgs = self._mailbox.read(core_execution_session_id)
            child_msgs = [m for m in msgs if m.from_id == child.session_id]
            status["reports"] = [m.content for m in child_msgs]
            reports.append(status)
        return reports

    def build_system_prompt(self, prompt_profile: str = "") -> str:
        """Build the complete system prompt for the Core agent using PromptAssembler.

        Uses prompt_profile from RouterDecision to load the right template.
        """
        blocks: List[str] = []

        # Load prompt template based on RouterDecision.prompt_profile
        if prompt_profile:
            template_rel = PROMPT_PROFILE_MAP.get(prompt_profile, "")
            if template_rel:
                template_path = Path(self._config.prompts_root) / template_rel
                if template_path.exists():
                    blocks.append(template_rel)
                else:
                    logger.warning(
                        "Core prompt profile template missing: profile=%s path=%s",
                        prompt_profile,
                        template_path,
                    )

        core_duties = (
            "\n## 核心职责\n"
            "1. 将用户目标分解为能力域（backend/frontend/ops/testing/docs）\n"
            "2. 为每个能力域创建 Expert Agent\n"
            "3. 监控 Expert 进度，收集报告\n"
            "4. 汇总结果返回给 Shell\n"
        )
        try:
            body = self._assembler.assemble(
                blocks=blocks if blocks else None,
                extra_sections=[core_duties],
            )
            if self._values_prompt.strip():
                return "\n\n".join([self._values_prompt.strip(), body]).strip()
            return body
        except Exception:
            # Fallback: use loaded values prompt
            parts: List[str] = []
            if self._values_prompt:
                parts.append(self._values_prompt)
            parts.append(core_duties)
            return "\n".join(parts)

    # ── Private ────────────────────────────────────────────────

    def _map_to_experts(
        self,
        subtasks: List[SubTask],
        *,
        router_tool_profile: List[str],
        prompt_profile: str,
        model_tier: str,
    ) -> List[Dict[str, Any]]:
        """Map subtasks to expert domain assignments.

        Merges domain-specific defaults with RouterDecision's tool_profile.
        """
        domain_tasks: Dict[str, List[str]] = {}

        for task in subtasks:
            domain = self._infer_domain(task.description)
            if domain not in domain_tasks:
                domain_tasks[domain] = []
            domain_tasks[domain].append(task.description)

        assignments = []
        for domain, tasks in domain_tasks.items():
            scope = "\n".join(f"- {t}" for t in tasks)
            # Merge: domain-specific tools + router-selected tools
            domain_tools = self._domain_tools(domain)
            merged_tools = list(dict.fromkeys(domain_tools + router_tool_profile))

            assignments.append({
                "expert_type": domain,
                "scope": f"[{domain.upper()}]\n{scope}",
                "prompt_blocks": [f"roles/{domain}_expert.md"],
                "tool_subset": merged_tools,
                "model_tier": model_tier,
                "prompt_profile": prompt_profile,
            })
        return assignments

    def _infer_domain(self, description: str) -> str:
        """Infer expert domain from task description."""
        desc_lower = description.lower()
        for domain, keywords in self._config.expert_domains.items():
            if any(kw in desc_lower for kw in keywords):
                return domain
        return "backend"

    def _domain_tools(self, domain: str) -> List[str]:
        """Return default tool subset for a domain."""
        base = ["read_file", "write_file", "search_file"]
        domain_specific = {
            "backend": ["file_ast", "run_tests"],
            "frontend": ["file_ast"],
            "ops": ["os_bash", "sleep_and_watch"],
            "testing": ["run_tests", "file_ast"],
            "docs": [],
        }
        return base + domain_specific.get(domain, [])

    def _load_values(self) -> None:
        """Load Values DNA from file (immutable)."""
        path = Path(self._config.values_dna_path)
        if path.exists():
            self._values_prompt = path.read_text(encoding="utf-8")
            logger.info("Loaded Core Values DNA from %s", path)
        else:
            self._values_prompt = ""
            logger.warning("Core Values DNA not found at %s", path)

    @staticmethod
    def _normalize_string_list(value: Any) -> List[str]:
        if not isinstance(value, list):
            return []
        rows: List[str] = []
        for item in value:
            text = str(item or "").strip()
            if text:
                rows.append(text)
        return rows

    @staticmethod
    def _safe_non_negative_int(value: Any) -> int:
        try:
            return max(0, int(value))
        except Exception:
            return 0

    @staticmethod
    def _normalize_tool_name(raw: str) -> str:
        text = str(raw or "").strip().lower()
        aliases = {
            "os_bash": "run_cmd",
            "command": "run_cmd",
            "cmd": "run_cmd",
            "search": "search_keyword",
            "grep": "search_keyword",
            "file_ast": "file_ast_skeleton",
        }
        return aliases.get(text, text)

    @staticmethod
    def _normalize_complexity_hint(raw: Any) -> str:
        text = str(raw or "").strip().lower()
        mapping = {
            "trivial": "trivial",
            "low": "trivial",
            "simple": "trivial",
            "small": "trivial",
            "standard": "standard",
            "normal": "standard",
            "medium": "standard",
            "high": "complex",
            "complex": "complex",
            "epic": "complex",
        }
        return mapping.get(text, "standard")

    def _build_fast_track_tool_subset(self, router_tools: List[str]) -> List[str]:
        normalized_router = [self._normalize_tool_name(tool) for tool in router_tools]
        subset: List[str] = []
        for tool in normalized_router:
            if tool in FAST_TRACK_ALLOWED_TOOLS and tool not in subset:
                subset.append(tool)
        for tool in sorted(FAST_TRACK_ALLOWED_TOOLS):
            if tool not in subset:
                subset.append(tool)
        return subset

    @staticmethod
    def _looks_like_config_change(goal: str) -> bool:
        text = str(goal or "").strip().lower()
        markers = (
            ".env",
            "config.json",
            "write_config",
            "delete_file",
            "配置",
            "config",
            "setting",
            "settings",
        )
        return any(marker in text for marker in markers)

    @staticmethod
    def _is_protected_path(path: str) -> bool:
        normalized = str(path or "").strip().replace("\\", "/").lstrip("./").lower()
        if not normalized:
            return False
        if normalized in FAST_TRACK_PROTECTED_EXACT:
            return True
        return any(normalized.startswith(prefix) for prefix in FAST_TRACK_PROTECTED_PREFIXES)


__all__ = ["CoreAgent", "CoreAgentConfig"]
