"""Brain-layer execution-contract builder and message packer.

This module centralizes the core-execution contract construction that was
previously embedded in `apiserver.api_server`.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator

DEFAULT_FOLLOWUP_MARKERS = (
    "continue",
    "go on",
    "继续",
    "接着",
    "然后",
)


def trim_contract_text(value: Any, *, limit: int = 240) -> str:
    text = " ".join(str(value or "").strip().split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


class CoreExecutionContractInput(BaseModel):
    """Structured seed contract passed into core_execution loop."""

    model_config = ConfigDict(extra="forbid")

    contract_stage: str = "seed"
    session_id: str = ""
    goal: str = Field(min_length=1)
    scope_hint: str = ""
    acceptance_hint: str = "输出可验证的执行证据（含结果与报告路径），必要时附失败根因与下一步。"
    shell_context_summary: str = ""
    recent_user_history: List[str] = Field(default_factory=list)
    recent_assistant_history: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)
    evidence_path_hint: str = "scratch/reports/"

    @field_validator(
        "contract_stage",
        "session_id",
        "goal",
        "scope_hint",
        "acceptance_hint",
        "shell_context_summary",
        "evidence_path_hint",
        mode="before",
    )
    @classmethod
    def _strip_text(cls, value: Any) -> str:
        return str(value or "").strip()


def build_core_execution_contract_payload(
    *,
    session_id: str,
    current_message: str,
    recent_messages: Sequence[Dict[str, Any]] | None,
    followup_markers: Sequence[str] | None = None,
) -> Dict[str, Any]:
    """Build structured contract payload for core execution."""

    latest_user_history: List[str] = []
    latest_assistant_history: List[str] = []
    for item in reversed(list(recent_messages or [])):
        role = str(item.get("role") or "").strip().lower()
        content = trim_contract_text(item.get("content", ""))
        if not content:
            continue
        if role == "user" and len(latest_user_history) < 3:
            latest_user_history.append(content)
        elif role == "assistant" and len(latest_assistant_history) < 2:
            latest_assistant_history.append(content)
        if len(latest_user_history) >= 3 and len(latest_assistant_history) >= 2:
            break

    latest_user_history.reverse()
    latest_assistant_history.reverse()

    goal = trim_contract_text(current_message, limit=320)
    scope_hint = latest_user_history[-1] if latest_user_history else goal
    assumptions: List[str] = []
    markers = tuple(str(item).strip().lower() for item in (followup_markers or DEFAULT_FOLLOWUP_MARKERS))
    if not latest_user_history:
        assumptions.append("历史上下文为空，按当前请求建立新执行契约。")
    lowered_goal = goal.lower()
    if len(goal) <= 24 and any(marker and marker in lowered_goal for marker in markers):
        assumptions.append("用户输入可能是续写指令，需结合 recent_user_history 推断目标。")

    shell_context_summary = ""
    if latest_user_history:
        shell_context_summary = " → ".join(latest_user_history[-2:])
    if latest_assistant_history:
        last_assistant = latest_assistant_history[-1]
        if shell_context_summary:
            shell_context_summary += f" [assistant: {last_assistant[:120]}]"
        else:
            shell_context_summary = f"[assistant: {last_assistant[:120]}]"

    payload = CoreExecutionContractInput(
        contract_stage="seed",
        session_id=str(session_id or ""),
        goal=goal,
        scope_hint=scope_hint,
        shell_context_summary=shell_context_summary,
        recent_user_history=latest_user_history,
        recent_assistant_history=latest_assistant_history,
        assumptions=assumptions,
        evidence_path_hint="scratch/reports/",
    )
    return payload.model_dump()


def build_core_execution_messages(
    *,
    session_id: str,
    current_message: str,
    core_system_prompt: Optional[str] = None,
    system_prompt: Optional[str] = None,
    recent_messages: Sequence[Dict[str, Any]] | None = None,
    followup_markers: Sequence[str] | None = None,
) -> List[Dict[str, Any]]:
    """Build 3-message core execution packet for core_execution.

    Message shape:
    1) system: core system prompt
    2) system: `[ExecutionContractInput]` + compact JSON payload
    3) user: current user message
    """

    resolved_system_prompt = trim_contract_text(core_system_prompt or system_prompt)
    if not resolved_system_prompt:
        raise ValueError("core_system_prompt/system_prompt 不能为空")

    contract_payload = build_core_execution_contract_payload(
        session_id=session_id,
        current_message=current_message,
        recent_messages=list(recent_messages or []),
        followup_markers=followup_markers,
    )
    contract_text = "[ExecutionContractInput]\n" + json.dumps(contract_payload, ensure_ascii=False, sort_keys=True)
    return [
        {"role": "system", "content": resolved_system_prompt},
        {"role": "system", "content": contract_text},
        {"role": "user", "content": current_message},
    ]


__all__ = [
    "CoreExecutionContractInput",
    "build_core_execution_contract_payload",
    "build_core_execution_messages",
    "trim_contract_text",
]
