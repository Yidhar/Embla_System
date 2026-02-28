"""Brain-layer router engine under `agents/` namespace.

This module is intentionally independent from `autonomous.router_engine` to
avoid alias/wrapper drift. It keeps deterministic routing behavior while
upgrading request/decision contracts to Pydantic models.
"""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_hash(payload: Dict[str, Any]) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


HIGH_RISK_LEVELS = {"write_repo", "deploy", "secrets", "self_modify"}
TASK_TYPE_RULES = [
    ("ops", ("nginx", "k8s", "kubernetes", "docker", "cpu", "memory", "磁盘", "告警", "故障", "恢复")),
    ("development", ("api", "code", "refactor", "bug", "test", "代码", "修复", "patch", "模块")),
    ("research", ("research", "investigate", "analysis", "文档", "调研", "评估")),
]
ROLE_TO_TOOLS = {
    "sys_admin": ["os_bash", "sleep_and_watch", "read_file", "artifact_reader"],
    "developer": ["file_ast", "workspace_txn_apply", "read_file", "artifact_reader"],
    "researcher": ["read_file", "artifact_reader", "search"],
}


class RouterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    estimated_complexity: str = "medium"
    requested_role: str = ""
    risk_level: str = "read_only"
    budget_remaining: Optional[int] = Field(default=None, ge=0)
    trace_id: str = ""
    session_id: str = ""

    @field_validator(
        "task_id",
        "description",
        "estimated_complexity",
        "requested_role",
        "risk_level",
        "trace_id",
        "session_id",
        mode="before",
    )
    @classmethod
    def _strip_text(cls, value: Any) -> str:
        return str(value or "").strip()


class RouterDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: str
    created_at: str
    task_id: str
    trace_id: str
    session_id: str
    task_type: str
    selected_role: str
    selected_model_tier: str
    tool_profile: List[str]
    prompt_profile: str
    injection_mode: str
    delegation_intent: str
    risk_level: str
    budget_remaining: Optional[int] = None
    reasoning: List[str]
    replay_fingerprint: str
    workflow_entry_state: str
    controlled_execution_plan: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


class TaskRouterEngine:
    """Deterministic task router with replayable fingerprints."""

    def __init__(
        self,
        *,
        decision_log: Path | None = None,
        fixed_role_fallback: str = "developer",
    ) -> None:
        self.decision_log = decision_log
        if self.decision_log is not None:
            self.decision_log.parent.mkdir(parents=True, exist_ok=True)
        self.fixed_role_fallback = str(fixed_role_fallback or "developer").strip() or "developer"
        self._lock = threading.Lock()

    def route(self, request: RouterRequest) -> RouterDecision:
        task_type = self._infer_task_type(request.description)
        role, role_reason = self._select_role(request=request, task_type=task_type)
        model_tier, model_reason = self._select_model_tier(request=request, task_type=task_type)
        delegation_intent, delegation_reason = self._select_delegation_intent(request=request, task_type=task_type)
        prompt_profile, prompt_profile_reason = self._select_prompt_profile(
            task_type=task_type,
            selected_role=role,
            delegation_intent=delegation_intent,
        )
        injection_mode, injection_mode_reason = self._select_injection_mode(request=request, task_type=task_type)
        tool_profile = list(ROLE_TO_TOOLS.get(role, ROLE_TO_TOOLS[self.fixed_role_fallback]))
        reasons = [role_reason, model_reason, delegation_reason, prompt_profile_reason, injection_mode_reason]

        fingerprint_payload = {
            "task_type": task_type,
            "selected_role": role,
            "selected_model_tier": model_tier,
            "tool_profile": tool_profile,
            "prompt_profile": prompt_profile,
            "injection_mode": injection_mode,
            "delegation_intent": delegation_intent,
            "risk_level": request.risk_level,
            "budget_remaining": request.budget_remaining,
            "description": request.description,
            "estimated_complexity": request.estimated_complexity,
        }
        replay_fingerprint = _stable_hash(fingerprint_payload)
        controlled_execution_plan = self._build_controlled_execution_plan(
            request=request,
            task_type=task_type,
            selected_role=role,
            selected_model_tier=model_tier,
            tool_profile=tool_profile,
            prompt_profile=prompt_profile,
            injection_mode=injection_mode,
            delegation_intent=delegation_intent,
        )
        decision = RouterDecision(
            decision_id=f"route_{uuid.uuid4().hex[:12]}",
            created_at=_utc_iso(),
            task_id=request.task_id,
            trace_id=request.trace_id,
            session_id=request.session_id,
            task_type=task_type,
            selected_role=role,
            selected_model_tier=model_tier,
            tool_profile=tool_profile,
            prompt_profile=prompt_profile,
            injection_mode=injection_mode,
            delegation_intent=delegation_intent,
            risk_level=request.risk_level,
            budget_remaining=request.budget_remaining,
            reasoning=reasons,
            replay_fingerprint=replay_fingerprint,
            workflow_entry_state=str(controlled_execution_plan.get("entry_state") or "planned"),
            controlled_execution_plan=controlled_execution_plan,
        )
        self._append_log(request=request, decision=decision)
        return decision

    def replay(self, request: RouterRequest, expected_fingerprint: str) -> bool:
        decision = self.route(request)
        return decision.replay_fingerprint == str(expected_fingerprint or "")

    def _append_log(self, *, request: RouterRequest, decision: RouterDecision) -> None:
        if self.decision_log is None:
            return
        row = {
            "ts": _utc_iso(),
            "request": request.model_dump(),
            "decision": decision.model_dump(),
        }
        line = json.dumps(row, ensure_ascii=False)
        with self._lock:
            with self.decision_log.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")

    @staticmethod
    def _build_controlled_execution_plan(
        *,
        request: RouterRequest,
        task_type: str,
        selected_role: str,
        selected_model_tier: str,
        tool_profile: List[str],
        prompt_profile: str,
        injection_mode: str,
        delegation_intent: str,
    ) -> Dict[str, Any]:
        risk = str(request.risk_level or "").strip().lower()
        requires_human_approval = risk in HIGH_RISK_LEVELS or str(selected_role).strip().lower() == "sys_admin"
        return {
            "schema_version": "ws28_router_workflow_engine.v1",
            "entry_state": "planned",
            "states": [
                "planned",
                "delegating",
                "executing",
                "verifying",
                "completed",
                "blocked",
                "failed",
            ],
            "terminal_states": ["completed", "failed"],
            "transitions": [
                {"from": "planned", "to": "delegating", "guard": "route_decision_committed"},
                {
                    "from": "delegating",
                    "to": "executing",
                    "guard": "delegate_intent_allows_execution and policy_firewall_ready",
                },
                {"from": "executing", "to": "verifying", "guard": "tool_calls_finished"},
                {"from": "verifying", "to": "completed", "guard": "submit_result_confirmed"},
                {"from": "verifying", "to": "blocked", "guard": "guardrail_rejected"},
                {"from": "executing", "to": "failed", "guard": "execution_error_unrecoverable"},
                {"from": "blocked", "to": "delegating", "guard": "operator_override_or_retry_window"},
            ],
            "route_contract": {
                "task_type": task_type,
                "selected_role": selected_role,
                "selected_model_tier": selected_model_tier,
                "tool_profile": list(tool_profile),
                "prompt_profile": prompt_profile,
                "injection_mode": injection_mode,
                "delegation_intent": delegation_intent,
            },
            "guardrails": {
                "requires_human_approval": requires_human_approval,
                "risk_level": str(request.risk_level or ""),
                "budget_remaining": request.budget_remaining,
                "max_delegate_turns": 3,
            },
        }

    @staticmethod
    def _infer_task_type(description: str) -> str:
        text = str(description or "").lower()
        for task_type, tokens in TASK_TYPE_RULES:
            if any(token in text for token in tokens):
                return task_type
        return "general"

    def _select_role(self, *, request: RouterRequest, task_type: str) -> tuple[str, str]:
        requested = str(request.requested_role or "").strip()
        if requested:
            return requested, f"role from request: {requested}"
        if str(request.risk_level or "").lower() in HIGH_RISK_LEVELS:
            return "sys_admin", f"high risk level {request.risk_level} => sys_admin"
        if task_type == "ops":
            return "sys_admin", "task type ops => sys_admin"
        if task_type == "development":
            return "developer", "task type development => developer"
        if task_type == "research":
            return "researcher", "task type research => researcher"
        return self.fixed_role_fallback, f"default fallback role => {self.fixed_role_fallback}"

    @staticmethod
    def _select_model_tier(*, request: RouterRequest, task_type: str) -> tuple[str, str]:
        risk = str(request.risk_level or "").lower()
        complexity = str(request.estimated_complexity or "").lower()
        budget = request.budget_remaining

        if risk in HIGH_RISK_LEVELS:
            return "primary", f"risk level {risk} => primary tier"
        if complexity in {"high", "epic"}:
            if budget is not None and budget < 6000:
                return "secondary", f"high complexity with constrained budget {budget} => secondary tier"
            return "primary", "high complexity => primary tier"
        if budget is not None:
            if budget < 2000:
                return "local", f"low budget {budget} => local tier"
            if budget < 8000:
                return "secondary", f"medium budget {budget} => secondary tier"
            return "primary", f"sufficient budget {budget} => primary tier"
        if task_type == "research":
            return "secondary", "research task default => secondary tier"
        return "primary", "default => primary tier"

    @staticmethod
    def _select_delegation_intent(*, request: RouterRequest, task_type: str) -> tuple[str, str]:
        risk = str(request.risk_level or "").lower()
        requested_role = str(request.requested_role or "").strip()
        if requested_role:
            return "explicit_role_delegate", f"requested_role={requested_role} => explicit_role_delegate"
        if risk in HIGH_RISK_LEVELS:
            return "core_execution", f"risk={risk} => core_execution"
        if risk in {"read_only", "readonly", "low"}:
            return "read_only_exploration", f"risk={risk} => read_only_exploration"
        if task_type in {"ops", "development"}:
            return "core_execution", f"task_type={task_type} => core_execution"
        if task_type == "research":
            return "read_only_exploration", "research task => read_only_exploration"
        return "general_assistance", "default => general_assistance"

    @staticmethod
    def _select_prompt_profile(
        *,
        task_type: str,
        selected_role: str,
        delegation_intent: str,
    ) -> tuple[str, str]:
        role = str(selected_role or "").strip().lower()
        intent = str(delegation_intent or "").strip().lower()
        if intent == "core_execution":
            if role == "sys_admin":
                return "core_exec_ops", "core_execution + sys_admin => core_exec_ops"
            if role == "developer":
                return "core_exec_dev", "core_execution + developer => core_exec_dev"
            return "core_exec_general", "core_execution + non-standard role => core_exec_general"
        if intent == "read_only_exploration":
            if role == "researcher" or task_type == "research":
                return "outer_readonly_research", "read_only_exploration + research => outer_readonly_research"
            return "outer_readonly_general", "read_only_exploration => outer_readonly_general"
        if intent == "explicit_role_delegate":
            return "explicit_role_delegate", "explicit_role_delegate => explicit_role_delegate"
        return "outer_general", "default => outer_general"

    @staticmethod
    def _select_injection_mode(*, request: RouterRequest, task_type: str) -> tuple[str, str]:
        risk = str(request.risk_level or "").lower()
        description = str(request.description or "").lower()
        recovery_markers = ("recover", "rollback", "repair", "incident", "恢复", "回滚", "修复", "故障")
        if any(marker in description for marker in recovery_markers):
            return "recovery", "description has recovery markers => recovery mode"
        if risk in HIGH_RISK_LEVELS:
            return "hardened", f"risk level {risk} => hardened mode"
        if risk in {"read_only", "readonly", "low"}:
            return "minimal", f"risk={risk} => minimal mode"
        if task_type in {"development", "ops"}:
            return "standard_exec", f"task_type={task_type} => standard_exec"
        return "standard", "default => standard"


__all__ = ["TaskRouterEngine", "RouterRequest", "RouterDecision"]
