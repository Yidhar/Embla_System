"""Dev Agent — task executor with independent LLM session.

Spawned by an Expert Agent to execute specific tasks.
Runs a mini tool-loop with a subset of tools and auto-injected experience.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from agents.prompt_engine import PromptAssembler, get_system_prompts_root
from agents.runtime.agent_session import AgentSessionStore
from agents.runtime.mailbox import AgentMailbox

logger = logging.getLogger(__name__)


@dataclass
class DevAgentConfig:
    """Configuration for a Dev Agent instance."""

    prompt_blocks: List[str] = field(default_factory=list)
    tool_subset: List[str] = field(default_factory=list)
    memory_hints: List[str] = field(default_factory=list)
    prompts_root: str = "system/prompts"


class DevAgent:
    """Dev Agent: the hands that write code.

    Responsibilities:
        - Execute assigned task with an independent LLM session
        - Use only allowed tools (parent-defined subset)
        - Check parent messages periodically
        - Update task status as work progresses
        - Report completion/error/blocked to parent
        - Write back experience to Layer 1 memory
    """

    def __init__(
        self,
        *,
        config: Optional[DevAgentConfig] = None,
        session_id: str = "",
        store: Optional[AgentSessionStore] = None,
        mailbox: Optional[AgentMailbox] = None,
    ) -> None:
        self._config = config or DevAgentConfig()
        self._session_id = session_id
        self._store = store
        self._mailbox = mailbox
        self._assembler = PromptAssembler(prompts_root=self._config.prompts_root)
        self._runtime_assembler = PromptAssembler(prompts_root=str(get_system_prompts_root()))

    def build_system_prompt(self) -> str:
        """Assemble system prompt from atomic blocks + memory hints using PromptAssembler."""
        try:
            parts: List[str] = []
            if self._config.prompt_blocks:
                custom_prompt = self._assembler.assemble(blocks=list(self._config.prompt_blocks))
                if custom_prompt.strip():
                    parts.append(custom_prompt.strip())
            runtime_prompt = self._runtime_assembler.assemble(
                blocks=[
                    "agents/dev/dev_agent_behavior.md",
                    "agents/dev/dev_agent_self_verification.md",
                ],
            )
            if runtime_prompt.strip():
                parts.append(runtime_prompt.strip())
            if self._config.memory_hints:
                memory_prompt = self._assembler.assemble(memory_hints=list(self._config.memory_hints))
                if memory_prompt.strip():
                    parts.append(memory_prompt.strip())
            return "\n\n".join(parts).strip()
        except Exception:
            parts: List[str] = []
            for block_path in self._config.prompt_blocks:
                full_path = Path(self._config.prompts_root) / block_path
                if full_path.exists():
                    parts.append(full_path.read_text(encoding="utf-8"))
            for block_path in (
                "agents/dev/dev_agent_behavior.md",
                "agents/dev/dev_agent_self_verification.md",
            ):
                full_path = get_system_prompts_root() / block_path
                if full_path.exists():
                    parts.append(full_path.read_text(encoding="utf-8"))
            if self._config.memory_hints:
                parts.append("\n## 相关经验\n")
                for hint in self._config.memory_hints:
                    parts.append(f"- 参考: `{hint}`")
            return "\n".join(parts)

    def build_experience_md(
        self,
        *,
        task_id: str,
        task_title: str,
        outcome: str,
        problem: str = "",
        solution: str = "",
        files_changed: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
    ) -> str:
        """Generate an experience MD file for Layer 1 memory write-back."""
        tag_str = " ".join(f"#{t}" for t in (tags or []))
        files_str = "\n".join(f"- `{f}`" for f in (files_changed or []))

        return (
            f"# 经验：{task_title}\n\n"
            f"tags: {tag_str}\n"
            f"task: {task_id}\n"
            f"outcome: {outcome}\n\n"
            f"## 问题\n{problem}\n\n"
            f"## 解决方案\n{solution}\n\n"
            f"## 变更文件\n{files_str}\n"
        )


__all__ = ["DevAgent", "DevAgentConfig"]
