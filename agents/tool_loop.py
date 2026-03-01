#!/usr/bin/env python3
"""
Agentic Tool Loop 核心引擎
实现单LLM agentic loop：模型在对话中发起工具调用，接收结果，再继续推理，直到不再需要工具。
"""

import asyncio
import hashlib
import json
import logging
import re
import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Dict, List, Optional, Set, Tuple

from core.security.budget_guard import BudgetGuardController
from agents.memory.episodic_memory import archive_tool_results_for_session, build_reinjection_context
from agents.memory.semantic_graph import update_semantic_graph_from_records
from system.config import get_config
from system.coding_intent import contains_direct_coding_signal, extract_latest_user_message
from system.gc_budget_guard import GCBudgetGuard, GCBudgetGuardConfig
from system.gc_memory_card import build_gc_memory_index_card
from system.gc_reader_bridge import build_gc_reader_followup_plan
from core.security import LeaseHandle, get_global_mutex_manager
from system.loop_cost_guard import LoopCostGuard, LoopCostThresholds
from system.router_arbiter import MAX_DELEGATE_TURNS, evaluate_workspace_conflict_retry
from system.tool_contract import ToolCallEnvelope
from core.supervisor.watchdog_daemon import WatchdogDaemon, WatchdogThresholds
from apiserver.native_tools import get_native_tool_executor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 循环策略与运行态
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AgenticLoopPolicy:
    """Agentic loop 编排策略（配置驱动）。"""

    max_rounds: int
    enable_summary_round: bool
    max_consecutive_tool_failures: int
    max_consecutive_validation_failures: int
    max_consecutive_no_tool_rounds: int
    # Deprecated: natural-language no-tool feedback injection has been retired.
    inject_no_tool_feedback: bool
    tool_result_preview_chars: int
    emit_workflow_stage_events: bool
    max_parallel_tool_calls: int
    retry_failed_tool_calls: bool
    max_tool_retries: int
    retry_backoff_seconds: float
    gc_budget_guard_enabled: bool
    gc_budget_repeat_threshold: int
    gc_budget_window_size: int


@dataclass
class AgenticLoopRuntimeState:
    """Agentic loop 运行态统计。"""

    round_num: int = 0
    total_tool_calls: int = 0
    total_tool_success: int = 0
    total_tool_errors: int = 0
    consecutive_tool_failures: int = 0
    consecutive_validation_failures: int = 0
    consecutive_no_tool_rounds: int = 0
    gc_guard_repeat_count: int = 0
    gc_guard_error_total: int = 0
    gc_guard_success_total: int = 0
    gc_guard_hit_total: int = 0
    agent_state: Dict[str, Any] = field(default_factory=lambda: {"task_completed": False})
    submit_result_called: bool = False
    submit_result_round: int = 0
    stop_reason: str = ""


@dataclass(frozen=True)
class ToolContractRolloutRuntime:
    """工具契约灰度运行态（由配置解析得到）。"""

    mode: str = "new_stack_only"
    decommission_legacy_gate: bool = True
    emit_observability_metadata: bool = True

    @property
    def legacy_contract_enabled(self) -> bool:
        if self.decommission_legacy_gate:
            return False
        return self.mode in {"legacy_only", "dual_stack"}

    @property
    def new_contract_enabled(self) -> bool:
        return self.mode in {"dual_stack", "new_stack_only"}

    def snapshot(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "legacy_contract_enabled": self.legacy_contract_enabled,
            "new_contract_enabled": self.new_contract_enabled,
            "decommission_legacy_gate": bool(self.decommission_legacy_gate),
            "emit_observability_metadata": bool(self.emit_observability_metadata),
        }


@dataclass
class ParallelContractGateDecision:
    """Parallel contract gate decision payload for one planning round."""

    actionable_calls: List[Dict[str, Any]]
    messages: List[str]
    force_serial: bool = False
    readonly_downgraded: bool = False
    dropped_mutating_calls: int = 0
    validation_errors: List[str] | None = None
    reason: str = ""


_TOOL_CONTRACT_ROLLOUT_MODES = {"legacy_only", "dual_stack", "new_stack_only"}
_TOOL_CONTRACT_MODE_ALIASES = {
    "legacy": "new_stack_only",
    "legacy_stack": "new_stack_only",
    "old_stack": "new_stack_only",
    "dual": "new_stack_only",
    "compat": "new_stack_only",
    "both": "new_stack_only",
    "new": "new_stack_only",
    "new_stack": "new_stack_only",
    "v2_only": "new_stack_only",
}
_TOOL_RESULT_NONE_MARKERS = {"", "(none)", "none", "null", "nil", "n/a", "undefined"}
_TOOL_RESULT_TAG_LINE_RE = re.compile(r"^\[([A-Za-z0-9_]+)\](?:\s*(.*))?$")
_BUDGET_GUARD_CONTROLLER: Optional[BudgetGuardController] = None


def _get_budget_guard_controller() -> BudgetGuardController:
    global _BUDGET_GUARD_CONTROLLER
    if _BUDGET_GUARD_CONTROLLER is None:
        _BUDGET_GUARD_CONTROLLER = BudgetGuardController()
    return _BUDGET_GUARD_CONTROLLER


def _clamp_int(value: Any, default: int, min_value: int, max_value: int) -> int:
    try:
        num = int(value)
    except Exception:
        return default
    return max(min_value, min(max_value, num))


def _resolve_agentic_loop_policy(max_rounds_override: Optional[int]) -> AgenticLoopPolicy:
    cfg = get_config()
    handoff_cfg = getattr(cfg, "handoff", None)
    loop_cfg = getattr(cfg, "agentic_loop", None)

    fallback_rounds = 500
    if handoff_cfg is not None:
        fallback_rounds = _clamp_int(getattr(handoff_cfg, "max_loop_stream", 500), 500, 1, 5000)

    configured_rounds = fallback_rounds
    if loop_cfg is not None:
        configured_rounds = _clamp_int(getattr(loop_cfg, "max_rounds_stream", fallback_rounds), fallback_rounds, 1, 5000)

    if max_rounds_override is not None and int(max_rounds_override) > 0:
        max_rounds = _clamp_int(max_rounds_override, configured_rounds, 1, 5000)
    else:
        max_rounds = configured_rounds

    if loop_cfg is None:
        return AgenticLoopPolicy(
            max_rounds=max_rounds,
            enable_summary_round=False,
            max_consecutive_tool_failures=2,
            max_consecutive_validation_failures=2,
            max_consecutive_no_tool_rounds=2,
            inject_no_tool_feedback=False,
            tool_result_preview_chars=500,
            emit_workflow_stage_events=True,
            max_parallel_tool_calls=8,
            retry_failed_tool_calls=True,
            max_tool_retries=1,
            retry_backoff_seconds=0.8,
            gc_budget_guard_enabled=True,
            gc_budget_repeat_threshold=3,
            gc_budget_window_size=6,
        )

    return AgenticLoopPolicy(
        max_rounds=max_rounds,
        enable_summary_round=bool(getattr(loop_cfg, "enable_summary_round", False)),
        max_consecutive_tool_failures=_clamp_int(
            getattr(loop_cfg, "max_consecutive_tool_failures", 2), 2, 1, 20
        ),
        max_consecutive_validation_failures=_clamp_int(
            getattr(loop_cfg, "max_consecutive_validation_failures", 2), 2, 1, 20
        ),
        max_consecutive_no_tool_rounds=_clamp_int(
            getattr(loop_cfg, "max_consecutive_no_tool_rounds", 2), 2, 1, 20
        ),
        inject_no_tool_feedback=False,
        tool_result_preview_chars=_clamp_int(
            getattr(loop_cfg, "tool_result_preview_chars", 500), 500, 120, 20000
        ),
        emit_workflow_stage_events=bool(getattr(loop_cfg, "emit_workflow_stage_events", True)),
        max_parallel_tool_calls=_clamp_int(getattr(loop_cfg, "max_parallel_tool_calls", 8), 8, 1, 64),
        retry_failed_tool_calls=bool(getattr(loop_cfg, "retry_failed_tool_calls", True)),
        max_tool_retries=_clamp_int(getattr(loop_cfg, "max_tool_retries", 1), 1, 0, 5),
        retry_backoff_seconds=float(getattr(loop_cfg, "retry_backoff_seconds", 0.8)),
        gc_budget_guard_enabled=bool(getattr(loop_cfg, "gc_budget_guard_enabled", True)),
        gc_budget_repeat_threshold=_clamp_int(getattr(loop_cfg, "gc_budget_repeat_threshold", 3), 3, 2, 10),
        gc_budget_window_size=_clamp_int(getattr(loop_cfg, "gc_budget_window_size", 6), 6, 2, 30),
    )


def _build_agentic_loop_watchdog() -> Optional[WatchdogDaemon]:
    cfg = get_config()
    loop_cfg = getattr(cfg, "agentic_loop", None)
    enabled = bool(getattr(loop_cfg, "watchdog_guard_enabled", True)) if loop_cfg is not None else True
    if not enabled:
        return None

    warn_only = bool(getattr(loop_cfg, "watchdog_warn_only", True)) if loop_cfg is not None else True
    consecutive_error_limit = _clamp_int(
        getattr(loop_cfg, "watchdog_consecutive_error_limit", 5) if loop_cfg is not None else 5,
        5,
        1,
        200,
    )
    tool_call_limit_per_minute = _clamp_int(
        getattr(loop_cfg, "watchdog_tool_call_limit_per_minute", 10) if loop_cfg is not None else 10,
        10,
        1,
        2000,
    )
    loop_window_seconds = _clamp_int(
        getattr(loop_cfg, "watchdog_loop_window_seconds", 60) if loop_cfg is not None else 60,
        60,
        1,
        3600,
    )
    task_cost_limit = float(
        getattr(loop_cfg, "watchdog_task_cost_limit", 5.0) if loop_cfg is not None else 5.0
    )
    daily_cost_limit = float(
        getattr(loop_cfg, "watchdog_daily_cost_limit", 50.0) if loop_cfg is not None else 50.0
    )
    loop_cost_guard = LoopCostGuard(
        thresholds=LoopCostThresholds(
            consecutive_error_limit=consecutive_error_limit,
            tool_call_limit_per_minute=tool_call_limit_per_minute,
            task_cost_limit=max(0.0, task_cost_limit),
            daily_cost_limit=max(0.0, daily_cost_limit),
            loop_window_seconds=loop_window_seconds,
        )
    )
    return WatchdogDaemon(
        thresholds=WatchdogThresholds(),
        warn_only=warn_only,
        loop_cost_guard=loop_cost_guard,
    )


def _extract_tool_call_cost(result: Dict[str, Any]) -> float:
    for key in ("call_cost", "tool_call_cost", "cost", "estimated_cost"):
        value = result.get(key)
        try:
            amount = float(value)
        except (TypeError, ValueError):
            continue
        if amount >= 0:
            return amount

    usage = result.get("usage")
    if isinstance(usage, dict):
        for key in ("total_cost", "estimated_cost"):
            value = usage.get(key)
            try:
                amount = float(value)
            except (TypeError, ValueError):
                continue
            if amount >= 0:
                return amount
    return 0.0


def _build_watchdog_guardrail_payload(
    *,
    signal: Dict[str, Any],
    source: str,
    round_num: int,
) -> Dict[str, Any]:
    payload = {
        "guard_type": "watchdog_loop_guard",
        "source": source,
        "round": int(round_num),
    }
    payload.update(signal)
    return payload


def _resolve_watchdog_stop_reason(signal: Dict[str, Any]) -> str:
    reason = str(signal.get("reason") or signal.get("reason_code") or "").strip().lower()
    if reason:
        normalized = reason.replace(" ", "_").replace("-", "_")
        return f"watchdog_{normalized}"
    return "watchdog_guard_hit"


def _should_stop_on_watchdog_signal(signal: Dict[str, Any]) -> bool:
    action = str(signal.get("action") or "").strip().lower()
    level = str(signal.get("level") or "").strip().lower()
    if action in {"kill_agent_loop", "terminate_task_budget_exceeded", "pause_dispatch_and_escalate"}:
        return True
    if level == "critical" and action not in {"", "alert_only", "throttle_new_workloads"}:
        return True
    return False


def _normalize_tool_contract_rollout_mode(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    normalized = _TOOL_CONTRACT_MODE_ALIASES.get(normalized, normalized)
    if normalized in {"legacy_only", "dual_stack"}:
        return "new_stack_only"
    if normalized in _TOOL_CONTRACT_ROLLOUT_MODES:
        return normalized
    return "new_stack_only"


def _resolve_tool_contract_rollout_runtime() -> ToolContractRolloutRuntime:
    cfg = get_config()
    rollout_cfg = getattr(cfg, "tool_contract_rollout", None)
    if rollout_cfg is None:
        return ToolContractRolloutRuntime()

    mode = _normalize_tool_contract_rollout_mode(getattr(rollout_cfg, "mode", "new_stack_only"))
    decommission_gate = bool(getattr(rollout_cfg, "decommission_legacy_gate", True))
    emit_metadata = bool(getattr(rollout_cfg, "emit_observability_metadata", True))
    return ToolContractRolloutRuntime(
        mode=mode,
        decommission_legacy_gate=decommission_gate,
        emit_observability_metadata=emit_metadata,
    )


def _coalesce_result_text(result: Dict[str, Any]) -> str:
    candidates = [
        result.get("result"),
        result.get("narrative_summary"),
        result.get("display_preview"),
    ]
    for value in candidates:
        if value is None:
            continue
        text = str(value)
        if text:
            return text
    return ""


def _clean_optional_ref(value: Any) -> str:
    text = str(value if value is not None else "").strip()
    if not text:
        return ""
    if text.lower() in _TOOL_RESULT_NONE_MARKERS:
        return ""
    return text


def _parse_tagged_tool_result_sections(result_text: str) -> Dict[str, str]:
    sections: Dict[str, str] = {}
    current_tag: Optional[str] = None
    current_lines: List[str] = []
    for line in str(result_text or "").splitlines():
        stripped = line.strip()
        matched = _TOOL_RESULT_TAG_LINE_RE.match(stripped)
        if matched:
            if current_tag is not None:
                sections[current_tag] = "\n".join(current_lines).strip()
            current_tag = str(matched.group(1) or "").strip().lower()
            inline = str(matched.group(2) or "").strip()
            current_lines = [inline] if inline else []
            continue
        if current_tag is not None:
            current_lines.append(line.rstrip())
    if current_tag is not None:
        sections[current_tag] = "\n".join(current_lines).strip()
    return sections


def _normalize_fetch_hints_value(value: Any) -> List[str]:
    if value is None:
        return []
    raw_items: List[str]
    if isinstance(value, list):
        raw_items = [str(item or "").strip() for item in value]
    else:
        text = str(value or "").strip()
        if not text:
            raw_items = []
        else:
            raw_items = [segment.strip() for segment in text.split(",")]

    hints: List[str] = []
    seen = set()
    for item in raw_items:
        if not item:
            continue
        if item.lower() in _TOOL_RESULT_NONE_MARKERS:
            continue
        if item in seen:
            continue
        seen.add(item)
        hints.append(item)
    return hints


def _extract_result_text_preview(result_payload: Any) -> str:
    if isinstance(result_payload, str):
        text = result_payload
        try:
            parsed = json.loads(text)
        except Exception:
            return text
        if isinstance(parsed, dict):
            for key in ("narrative_summary", "display_preview", "message", "result"):
                value = parsed.get(key)
                candidate = str(value if value is not None else "").strip()
                if candidate:
                    return candidate
        return text
    if isinstance(result_payload, dict):
        for key in ("narrative_summary", "display_preview", "message", "result"):
            value = result_payload.get(key)
            text = str(value if value is not None else "").strip()
            if text:
                return text
        try:
            return json.dumps(result_payload, ensure_ascii=False)
        except Exception:
            return str(result_payload)
    if result_payload is None:
        return ""
    return str(result_payload)


def _upgrade_tool_result_contract_payload(result: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(result or {})
    result_payload = normalized.get("result")
    has_legacy_payload = "result" in normalized
    result_preview = _extract_result_text_preview(result_payload)
    tagged = _parse_tagged_tool_result_sections(result_preview)
    parsed_result_payload: Dict[str, Any] = {}
    if isinstance(result_payload, dict):
        parsed_result_payload = result_payload
    elif isinstance(result_payload, str):
        try:
            maybe = json.loads(result_payload)
            if isinstance(maybe, dict):
                parsed_result_payload = maybe
        except Exception:
            parsed_result_payload = {}

    # Prefer explicit new-contract fields; fallback to tagged blocks or legacy result text.
    narrative_summary = str(
        normalized.get("narrative_summary")
        or parsed_result_payload.get("narrative_summary")
        or parsed_result_payload.get("display_preview")
        or parsed_result_payload.get("message")
        or parsed_result_payload.get("result")
        or tagged.get("narrative_summary")
        or tagged.get("display_preview")
        or result_preview
        or ""
    ).strip()
    display_preview = str(
        normalized.get("display_preview")
        or parsed_result_payload.get("display_preview")
        or parsed_result_payload.get("narrative_summary")
        or tagged.get("display_preview")
        or narrative_summary
        or ""
    ).strip()

    # Some MCP/local tool paths may legally return empty/None payloads.
    # In new-stack-only mode this should still be upgraded into new-contract fields
    # instead of being treated as legacy-only output.
    if has_legacy_payload and not narrative_summary and not display_preview:
        status = str(normalized.get("status") or "").strip().lower()
        service_name = str(normalized.get("service_name") or "").strip()
        tool_name = str(normalized.get("tool_name") or "").strip()
        status_text = "tool call returned empty payload"
        if status == "success":
            status_text = "tool call completed without output payload"
        elif status == "error":
            status_text = "tool call failed without error detail"
        scope = " / ".join(part for part in (service_name, tool_name) if part)
        narrative_summary = f"{status_text} ({scope})" if scope else status_text
        display_preview = narrative_summary

    if narrative_summary:
        normalized.setdefault("narrative_summary", narrative_summary)
    if display_preview:
        normalized.setdefault("display_preview", display_preview)

    forensic_ref = _clean_optional_ref(
        normalized.get("forensic_artifact_ref")
        or normalized.get("raw_result_ref")
        or parsed_result_payload.get("forensic_artifact_ref")
        or parsed_result_payload.get("raw_result_ref")
        or tagged.get("forensic_artifact_ref")
        or tagged.get("raw_result_ref")
    )
    if forensic_ref:
        normalized.setdefault("forensic_artifact_ref", forensic_ref)
        normalized.setdefault("raw_result_ref", forensic_ref)

    if "fetch_hints" not in normalized:
        hints = _normalize_fetch_hints_value(
            parsed_result_payload.get("fetch_hints") or tagged.get("fetch_hints")
        )
        if hints:
            normalized["fetch_hints"] = hints

    if "critical_evidence" not in normalized:
        critical_raw = parsed_result_payload.get("critical_evidence") or tagged.get("critical_evidence")
        critical_value: Dict[str, Any] = {}
        if isinstance(critical_raw, dict):
            critical_value = dict(critical_raw)
        elif isinstance(critical_raw, str):
            text = critical_raw.strip()
            if text and text.lower() not in _TOOL_RESULT_NONE_MARKERS:
                try:
                    parsed = json.loads(text)
                    if isinstance(parsed, dict):
                        critical_value = parsed
                except Exception:
                    critical_value = {"summary": text}
        if critical_value:
            normalized["critical_evidence"] = critical_value

    return normalized


def _has_new_contract_payload(result: Dict[str, Any]) -> bool:
    return any(
        bool(str(result.get(key) or "").strip())
        for key in ("narrative_summary", "display_preview", "forensic_artifact_ref", "raw_result_ref", "critical_evidence")
    )


def _truncate_preview_text(text: Any, *, limit: int) -> str:
    normalized = str(text if text is not None else "")
    return normalized[:limit] + "..." if len(normalized) > limit else normalized


def _build_frontend_preview(
    *,
    text: Any,
    limit: int,
    artifact_ref: str,
) -> Tuple[str, bool]:
    normalized = str(text if text is not None else "")
    if len(normalized) <= limit:
        return normalized, False
    if artifact_ref:
        prefix = normalized[: min(limit, 320)]
        return f"{prefix} ... [truncated, use artifact_reader on {artifact_ref}]", True
    return normalized[:limit] + "...", True


def _build_contract_observability_metadata(
    results: List[Dict[str, Any]],
    *,
    rollout: ToolContractRolloutRuntime,
) -> Dict[str, Any]:
    metadata: Dict[str, Any] = {"snapshot": rollout.snapshot()}
    if not rollout.emit_observability_metadata:
        return metadata

    stats = {
        "result_count": len(results),
        "legacy_payload_count": 0,
        "new_payload_count": 0,
        "legacy_blocked_count": 0,
    }
    for result in results:
        meta = result.get("_contract_rollout")
        if isinstance(meta, dict):
            if bool(meta.get("used_legacy")):
                stats["legacy_payload_count"] += 1
            if bool(meta.get("used_new")):
                stats["new_payload_count"] += 1
            if bool(meta.get("legacy_blocked")):
                stats["legacy_blocked_count"] += 1
            continue

        if "result" in result:
            stats["legacy_payload_count"] += 1
        if _has_new_contract_payload(result):
            stats["new_payload_count"] += 1

    metadata["stats"] = stats
    return metadata


def _normalize_receipt_next_steps(raw_value: Any) -> List[str]:
    if raw_value is None:
        return []
    if isinstance(raw_value, str):
        text = raw_value.strip()
        return [text] if text else []
    if not isinstance(raw_value, list):
        return []
    normalized: List[str] = []
    for item in raw_value:
        text = str(item or "").strip()
        if text:
            normalized.append(text)
    return normalized


def _build_default_receipt_next_steps(
    *,
    status: str,
    risk_level: str,
    artifact_ref: str,
    error_code: str,
) -> List[str]:
    suggestions: List[str] = []
    normalized_status = status.lower()
    normalized_risk = risk_level.lower()

    if normalized_status == "error":
        if error_code == _RISK_ERR_APPROVAL_REQUIRED:
            return ["request_human_approval_then_retry"]
        if error_code == _RISK_ERR_POLICY_BLOCKED:
            return ["select_lower_risk_alternative", "request_policy_exception_if_justified"]
        suggestions.append("inspect_error_and_retry")
        if artifact_ref:
            suggestions.append("read_artifact_with_artifact_reader")
        if error_code == _SCHEMA_ERR_LEGACY_DECOMMISSIONED:
            suggestions.append("switch_to_new_contract_payload")
        return suggestions

    if artifact_ref:
        suggestions.append("follow_up_with_artifact_reader_if_needed")
    if normalized_risk in {"write_repo", "deploy", "secrets", "self_modify"}:
        suggestions.append("run_post_change_verification")
    else:
        suggestions.append("continue_next_planned_step")
    return suggestions


def _build_tool_receipt(call: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
    context = call.get("_context_metadata")
    if not isinstance(context, dict):
        context = {}

    trace_id = str(call.get("_trace_id") or call.get("trace_id") or context.get("trace_id") or "").strip()
    idempotency_key = str(call.get("idempotency_key") or context.get("idempotency_key") or "").strip()
    risk_level = str(call.get("_risk_level") or call.get("risk_level") or context.get("risk_level") or "read_only").strip()
    execution_scope = str(
        call.get("_execution_scope") or call.get("execution_scope") or context.get("execution_scope") or "local"
    ).strip()
    requires_global_mutex = bool(
        call.get("_requires_global_mutex")
        if "_requires_global_mutex" in call
        else (call.get("requires_global_mutex") or context.get("requires_global_mutex"))
    )

    estimated_token_cost = _clamp_int(
        call.get("estimated_token_cost", context.get("estimated_token_cost", 0)),
        0,
        0,
        100_000_000,
    )
    budget_remaining_raw = call.get("budget_remaining", context.get("budget_remaining"))
    budget_remaining: Optional[int] = None
    if budget_remaining_raw is not None:
        try:
            budget_remaining = int(budget_remaining_raw)
        except Exception:
            budget_remaining = None

    artifact_ref = str(result.get("forensic_artifact_ref") or result.get("raw_result_ref") or "").strip()
    status = str(result.get("status", "unknown")).strip().lower()
    error_code = str(result.get("error_code") or "").strip()
    approval_required = bool(
        call.get("_approval_required")
        if "_approval_required" in call
        else (call.get("approval_required") or context.get("approval_required"))
    )
    approval_policy = str(
        call.get("_approval_policy")
        or call.get("approvalPolicy")
        or call.get("approval_policy")
        or context.get("approval_policy")
        or ""
    ).strip()
    approval_granted = bool(call.get("approval_granted") or call.get("approved") or call.get("_approval_granted"))

    next_steps = _normalize_receipt_next_steps(result.get("next_steps"))
    if not next_steps:
        next_steps = _build_default_receipt_next_steps(
            status=status,
            risk_level=risk_level,
            artifact_ref=artifact_ref,
            error_code=error_code,
        )

    risk_items: List[str] = []
    if status == "error":
        risk_items.append("tool_execution_failed")
    if risk_level in {"write_repo", "deploy", "secrets", "self_modify"}:
        risk_items.append(f"high_risk_action:{risk_level}")
    if error_code == _SCHEMA_ERR_LEGACY_DECOMMISSIONED:
        risk_items.append("legacy_contract_decommission_gate")
    if error_code == _RISK_ERR_APPROVAL_REQUIRED:
        risk_items.append("approval_required_gate")
    if error_code == _RISK_ERR_POLICY_BLOCKED:
        risk_items.append("risk_policy_block_gate")
    if requires_global_mutex:
        risk_items.append("global_mutex_required")
    if approval_required:
        risk_items.append(f"approval_hook:{approval_policy or 'unspecified'}")

    return {
        "version": "ws10-004-v1",
        "call_type": str(call.get("agentType") or "unknown"),
        "service_name": str(result.get("service_name") or call.get("service_name") or "unknown"),
        "tool_name": str(result.get("tool_name") or call.get("tool_name") or "unknown"),
        "trace_id": trace_id,
        "idempotency_key": idempotency_key,
        "risk_level": risk_level,
        "execution_scope": execution_scope,
        "requires_global_mutex": requires_global_mutex,
        "approval": {
            "required": approval_required,
            "policy": approval_policy or None,
            "granted": approval_granted,
        },
        "budget": {
            "estimated_token_cost": estimated_token_cost,
            "budget_remaining": budget_remaining,
        },
        "result": {
            "status": status,
            "error_code": error_code or None,
            "has_artifact": bool(artifact_ref),
            "forensic_artifact_ref": artifact_ref or None,
        },
        "risk_items": risk_items,
        "next_steps": next_steps,
    }


def _attach_tool_receipt(call: Dict[str, Any], result: Dict[str, Any]) -> None:
    if not isinstance(result, dict):
        return
    if not isinstance(call, dict):
        call = {}
    result["tool_receipt"] = _build_tool_receipt(call, result)


def _normalize_approval_policy(raw_value: Any) -> str:
    value = str(raw_value or "").strip().lower()
    if not value:
        return ""
    aliases = {
        "on_request": "on-request",
        "onrequest": "on-request",
        "manual_approval": "manual",
        "required_approval": "required",
        "auto": "on-failure",
    }
    return aliases.get(value, value)


def _is_truthy_flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "y", "on"}


def _resolve_call_risk_level(call: Dict[str, Any]) -> str:
    return str(call.get("_risk_level") or call.get("risk_level") or "read_only").strip().lower() or "read_only"


def _evaluate_risk_gate(call: Dict[str, Any]) -> Dict[str, Any]:
    risk_level = _resolve_call_risk_level(call)
    if risk_level not in _HIGH_RISK_LEVELS:
        call["_approval_required"] = False
        normalized_policy = _normalize_approval_policy(
            call.get("_approval_policy") or call.get("approvalPolicy") or call.get("approval_policy")
        )
        if normalized_policy:
            call["_approval_policy"] = normalized_policy
            call.setdefault("approvalPolicy", normalized_policy)
        return {
            "allowed": True,
            "risk_level": risk_level,
            "requires_approval": False,
            "approval_policy": normalized_policy,
            "approval_granted": _is_truthy_flag(call.get("approval_granted") or call.get("approved")),
        }

    normalized_policy = _normalize_approval_policy(
        call.get("_approval_policy") or call.get("approvalPolicy") or call.get("approval_policy")
    )
    if not normalized_policy:
        normalized_policy = _RISK_DEFAULT_APPROVAL_POLICY.get(risk_level, "on-request")
    call["_approval_required"] = True
    call["_approval_policy"] = normalized_policy
    call.setdefault("approvalPolicy", normalized_policy)
    approval_granted = _is_truthy_flag(call.get("approval_granted") or call.get("approved") or call.get("_approval_granted"))

    if normalized_policy in _RISK_POLICY_BLOCKLIST:
        return {
            "allowed": False,
            "risk_level": risk_level,
            "requires_approval": True,
            "approval_policy": normalized_policy,
            "approval_granted": approval_granted,
            "error_code": _RISK_ERR_POLICY_BLOCKED,
            "reason": f"risk gate blocked: {risk_level} call has approval_policy={normalized_policy}",
        }

    if risk_level in {"secrets", "self_modify"} and not approval_granted:
        return {
            "allowed": False,
            "risk_level": risk_level,
            "requires_approval": True,
            "approval_policy": normalized_policy,
            "approval_granted": False,
            "error_code": _RISK_ERR_APPROVAL_REQUIRED,
            "reason": f"risk gate requires explicit human approval for {risk_level}",
        }

    if normalized_policy in _RISK_POLICY_STRICT_APPROVAL and not approval_granted:
        return {
            "allowed": False,
            "risk_level": risk_level,
            "requires_approval": True,
            "approval_policy": normalized_policy,
            "approval_granted": False,
            "error_code": _RISK_ERR_APPROVAL_REQUIRED,
            "reason": f"risk gate requires explicit approval when approval_policy={normalized_policy}",
        }

    return {
        "allowed": True,
        "risk_level": risk_level,
        "requires_approval": True,
        "approval_policy": normalized_policy,
        "approval_granted": approval_granted,
    }


def _is_retryable_tool_failure(call: Dict[str, Any], result: Dict[str, Any]) -> bool:
    if bool(call.get("no_retry", False)):
        return False

    err_text = _coalesce_result_text(result)
    non_retry_markers = [
        "需要登录",
        "缺少",
        "不支持",
        "参数",
        "安全限制",
        "Blocked",
        "blocked",
        "unauthorized",
        "forbidden",
    ]
    return not any(marker in err_text for marker in non_retry_markers)


def _summarize_results_for_frontend(
    results: List[Dict[str, Any]],
    preview_chars: int,
    *,
    rollout: Optional[ToolContractRolloutRuntime] = None,
) -> List[Dict[str, Any]]:
    rollout_runtime = rollout or _resolve_tool_contract_rollout_runtime()
    summaries: List[Dict[str, Any]] = []
    limit = _clamp_int(preview_chars, 500, 120, 20000)
    for r in results:
        summary = {
            "service_name": r.get("service_name", "unknown"),
            "tool_name": r.get("tool_name", ""),
            "status": r.get("status", "unknown"),
        }
        result_text = _coalesce_result_text(r)
        artifact_ref = str(r.get("forensic_artifact_ref") or r.get("raw_result_ref") or "").strip()
        preview_text = r.get("display_preview", r.get("narrative_summary", result_text))
        preview_value, preview_truncated = _build_frontend_preview(
            text=preview_text,
            limit=limit,
            artifact_ref=artifact_ref,
        )
        summary["preview"] = preview_value
        if preview_truncated:
            summary["preview_truncated"] = True
        if rollout_runtime.legacy_contract_enabled:
            result_value, result_truncated = _build_frontend_preview(
                text=result_text,
                limit=limit,
                artifact_ref=artifact_ref,
            )
            summary["result"] = result_value
            if result_truncated:
                summary["result_truncated"] = True
        if rollout_runtime.new_contract_enabled:
            narrative_text = r.get("narrative_summary", r.get("display_preview", result_text))
            narrative_value, narrative_truncated = _build_frontend_preview(
                text=narrative_text,
                limit=limit,
                artifact_ref=artifact_ref,
            )
            summary["narrative_summary"] = narrative_value
            if narrative_truncated:
                summary["narrative_summary_truncated"] = True
            if artifact_ref:
                summary["forensic_artifact_ref"] = artifact_ref

        if rollout_runtime.emit_observability_metadata:
            meta = r.get("_contract_rollout")
            if isinstance(meta, dict):
                summary["contract_rollout"] = meta
        receipt = r.get("tool_receipt")
        if not isinstance(receipt, dict):
            tool_call = r.get("tool_call")
            if isinstance(tool_call, dict):
                receipt = _build_tool_receipt(tool_call, r)
        if isinstance(receipt, dict):
            summary["tool_receipt"] = receipt

        summaries.append(summary)
        if r.get("conflict_ticket"):
            summaries[-1]["conflict_ticket"] = str(r.get("conflict_ticket"))
        if r.get("delegate_turns") is not None:
            summaries[-1]["delegate_turns"] = _clamp_int(r.get("delegate_turns"), 0, 0, 10000)
        if "freeze" in r:
            summaries[-1]["freeze"] = bool(r.get("freeze"))
        if "hitl" in r:
            summaries[-1]["hitl"] = bool(r.get("hitl"))
        router_arbiter = r.get("router_arbiter")
        if isinstance(router_arbiter, dict):
            summaries[-1]["router_arbiter"] = router_arbiter
        gc_budget_guard = r.get("gc_budget_guard")
        if isinstance(gc_budget_guard, dict):
            summaries[-1]["gc_budget_guard"] = gc_budget_guard
        if "guard_hit" in r:
            summaries[-1]["guard_hit"] = bool(r.get("guard_hit"))
        if r.get("guard_stop_reason"):
            summaries[-1]["guard_stop_reason"] = str(r.get("guard_stop_reason"))
    return summaries


def _build_tool_call_descriptions(actionable_calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    descriptions: List[Dict[str, Any]] = []
    for tc in actionable_calls:
        descriptions.append(
            {
                "agentType": str(tc.get("agentType", "")),
                "service_name": str(tc.get("service_name", "")),
                "tool_name": str(tc.get("tool_name", "")),
                "message": str(tc.get("message", ""))[:100],
                "call_id": str(tc.get("_tool_call_id", "")),
                "risk_level": str(tc.get("_risk_level", "read_only")),
                "execution_scope": str(tc.get("_execution_scope", "local")),
                "requires_global_mutex": bool(tc.get("_requires_global_mutex", False)),
            }
        )
    return descriptions


def _extract_terminal_stream_error_text(text: str) -> str:
    """Detect fatal upstream stream errors that should stop the loop immediately."""
    if not text:
        return ""
    normalized = " ".join(str(text).strip().split())
    lowered = normalized.lower()
    markers = (
        "streaming call error",
        "google streaming error",
        "google live streaming error",
        "llm service unavailable",
        "chat call error",
        "google api call error",
        "login expired",
    )
    return normalized if any(marker in lowered for marker in markers) else ""


_CODING_KEYWORDS = (
    "修复",
    "实现",
    "重构",
    "改造",
    "写代码",
    "代码",
    "开发",
    "bug",
    "fix",
    "implement",
    "refactor",
    "coding",
    "unit test",
    "integration test",
    "lint",
    "compile",
    "build",
    "repo",
    "repository",
)
_MUTATING_NATIVE_TOOL_NAMES = {"write_file", "git_checkout_file", "workspace_txn_apply"}
_SCHEMA_ERR_INPUT_INVALID = "E_SCHEMA_INPUT_INVALID"
_SCHEMA_ERR_OUTPUT_INVALID = "E_SCHEMA_OUTPUT_INVALID"
_SCHEMA_ERR_LEGACY_DECOMMISSIONED = "E_LEGACY_CONTRACT_DECOMMISSIONED"
_RISK_ERR_APPROVAL_REQUIRED = "E_RISK_APPROVAL_REQUIRED"
_RISK_ERR_POLICY_BLOCKED = "E_RISK_POLICY_BLOCKED"
_NATIVE_TOOL_ALIASES = {
    "read": "read_file",
    "write": "write_file",
    "cwd": "get_cwd",
    "exec": "run_cmd",
    "search": "search_keyword",
    "docs": "query_docs",
    "ls": "list_files",
    "status": "git_status",
    "diff": "git_diff",
    "log": "git_log",
    "show": "git_show",
    "blame": "git_blame",
    "grep": "git_grep",
    "changed": "git_changed_files",
    "checkout": "git_checkout_file",
    "python": "python_repl",
    "python_exec": "python_repl",
    "artifact": "artifact_reader",
    "read_artifact": "artifact_reader",
    "file_ast_chunk": "file_ast_chunk_read",
    "readchunkbyrange": "file_ast_chunk_read",
    "sleep_watch": "sleep_and_watch",
    "watch_log": "sleep_and_watch",
    "txn_apply": "workspace_txn_apply",
    "scaffold_apply": "workspace_txn_apply",
    "killswitch": "killswitch_plan",
    "repl": "python_repl",
}
_SUPPORTED_NATIVE_TOOL_NAMES = {
    "read_file",
    "write_file",
    "get_cwd",
    "run_cmd",
    "search_keyword",
    "query_docs",
    "list_files",
    "git_status",
    "git_diff",
    "git_log",
    "git_show",
    "git_blame",
    "git_grep",
    "git_changed_files",
    "git_checkout_file",
    "python_repl",
    "artifact_reader",
    "file_ast_skeleton",
    "file_ast_chunk_read",
    "workspace_txn_apply",
    "sleep_and_watch",
    "killswitch_plan",
}
_NATIVE_TOOL_ALLOWED_INPUT_ARGS: Dict[str, Set[str]] = {
    "read_file": {"tool_name", "path", "file_path", "start_line", "end_line", "max_chars"},
    "write_file": {
        "tool_name",
        "path",
        "file_path",
        "content",
        "mode",
        "encoding",
        "requester",
        "approvalPolicy",
        "approval_policy",
        "approval_granted",
        "approved",
    },
    "get_cwd": {"tool_name"},
    "run_cmd": {
        "tool_name",
        "command",
        "cmd",
        "cwd",
        "timeout_seconds",
        "max_output_chars",
        "artifact_priority",
        "approvalPolicy",
        "approval_policy",
        "approval_granted",
        "approved",
    },
    "search_keyword": {
        "tool_name",
        "keyword",
        "query",
        "search_path",
        "glob",
        "case_sensitive",
        "max_results",
        "max_file_size_kb",
    },
    "query_docs": {"tool_name", "query", "keyword", "max_results", "max_file_size_kb", "case_sensitive"},
    "list_files": {"tool_name", "path", "recursive", "max_results", "glob"},
    "git_status": {
        "tool_name",
        "repo_path",
        "cwd",
        "timeout_seconds",
        "max_output_chars",
        "porcelain",
        "include_untracked",
        "short",
        "branch",
    },
    "git_diff": {
        "tool_name",
        "repo_path",
        "cwd",
        "timeout_seconds",
        "max_output_chars",
        "name_only",
        "stat",
        "cached",
        "staged",
        "unified",
        "ref",
        "base_ref",
        "target_path",
        "pathspec",
    },
    "git_log": {
        "tool_name",
        "repo_path",
        "cwd",
        "timeout_seconds",
        "max_output_chars",
        "max_count",
        "oneline",
        "pretty",
        "since",
        "ref",
        "target_path",
        "pathspec",
    },
    "git_show": {
        "tool_name",
        "repo_path",
        "cwd",
        "timeout_seconds",
        "max_output_chars",
        "ref",
        "stat_only",
        "name_only",
        "target_path",
        "pathspec",
    },
    "git_blame": {
        "tool_name",
        "repo_path",
        "cwd",
        "timeout_seconds",
        "max_output_chars",
        "target_path",
        "path",
        "file_path",
        "ref",
        "max_lines",
        "start_line",
        "end_line",
    },
    "git_grep": {
        "tool_name",
        "repo_path",
        "cwd",
        "timeout_seconds",
        "max_output_chars",
        "pattern",
        "keyword",
        "query",
        "case_sensitive",
        "use_regex",
        "max_results",
        "ref",
        "target_path",
        "pathspec",
    },
    "git_changed_files": {"tool_name", "repo_path", "cwd", "timeout_seconds", "max_output_chars", "max_results"},
    "git_checkout_file": {
        "tool_name",
        "repo_path",
        "cwd",
        "timeout_seconds",
        "max_output_chars",
        "target_path",
        "path",
        "file_path",
        "confirm",
        "ref",
        "staged",
        "worktree",
    },
    "python_repl": {
        "tool_name",
        "code",
        "expression",
        "sandbox",
        "timeout_seconds",
        "max_output_chars",
        "docker_image",
        "python_cmd",
    },
    "artifact_reader": {
        "tool_name",
        "forensic_artifact_ref",
        "raw_result_ref",
        "artifact_id",
        "mode",
        "max_results",
        "start_line",
        "end_line",
        "pattern",
        "keyword",
        "query",
        "use_regex",
        "case_sensitive",
        "jsonpath",
        "max_chars",
    },
    "file_ast_skeleton": {"tool_name", "path", "file_path", "max_results"},
    "file_ast_chunk_read": {
        "tool_name",
        "path",
        "file_path",
        "start_line",
        "end_line",
        "context_before",
        "context_after",
    },
    "workspace_txn_apply": {
        "tool_name",
        "changes",
        "contract_id",
        "contract_checksum",
        "verify_after_apply",
        "requester",
        "approvalPolicy",
        "approval_policy",
        "approval_granted",
        "approved",
    },
    "sleep_and_watch": {
        "tool_name",
        "log_file",
        "path",
        "pattern",
        "regex",
        "timeout_seconds",
        "poll_interval_seconds",
        "from_end",
        "max_line_chars",
    },
    "killswitch_plan": {"tool_name", "mode", "oob_allowlist", "dns_allow"},
}
_VALID_RESULT_STATUS = {"success", "ok", "error", "timeout", "blocked"}
_SSE_PROTOCOL_VERSION = "ws20-002-v1"
_HIGH_RISK_LEVELS = {"write_repo", "deploy", "secrets", "self_modify"}
_RISK_DEFAULT_APPROVAL_POLICY = {
    "write_repo": "on-request",
    "deploy": "on-request",
    "secrets": "always",
    "self_modify": "always",
}
_RISK_POLICY_BLOCKLIST = {"never", "deny", "denied", "disabled", "off", "none"}
_RISK_POLICY_STRICT_APPROVAL = {"always", "required"}
_L15_SLICE_MARKER = "[Prompt Slice][L1.5_EPISODIC_MEMORY]"
_ATOMIC_CTRL_SLICE_UID = "ws28_atomic_ctrl_plane"
_ATOMIC_CTRL_PROTOCOL_VERSION = "ws28_agent_state_submission.v1"
_SUBMIT_RESULT_TOOL_NAME = "SubmitResult_Tool"
_INTERNAL_SUBMIT_TOOL_NAME = "submit_result"
_CONTRACT_GATE_REASON_READONLY_DOWNGRADE = "contract_checksum_missing_parallel_write_downgraded_to_readonly"


def _schema_error(code: str, call_id: str, detail: str) -> str:
    normalized_detail = str(detail or "").strip()
    return f"[{code}] id={call_id} {normalized_detail}".strip()


def _as_nonempty_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_submit_string_list(value: Any, *, max_items: int = 20, max_item_chars: int = 240) -> List[str]:
    if not isinstance(value, list):
        return []
    normalized: List[str] = []
    for raw in value:
        text = _as_nonempty_text(raw)
        if not text:
            continue
        normalized.append(text[:max_item_chars])
        if len(normalized) >= max_items:
            break
    return normalized


def _normalize_submit_state_patch(value: Any, *, max_items: int = 20) -> Dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    normalized: Dict[str, Any] = {}
    for index, (raw_key, raw_val) in enumerate(value.items()):
        if index >= max_items:
            break
        key = _as_nonempty_text(raw_key)
        if not key:
            continue
        if isinstance(raw_val, (str, int, float, bool)) or raw_val is None:
            normalized[key[:80]] = raw_val
            continue
        normalized[key[:80]] = str(raw_val)[:500]
    return normalized


def _is_completion_submitted(runtime: AgenticLoopRuntimeState) -> bool:
    return bool(runtime.submit_result_called and runtime.agent_state.get("task_completed") is True)


def _normalize_native_tool_name(tool_name: str) -> str:
    lowered = _as_nonempty_text(tool_name).lower()
    return _NATIVE_TOOL_ALIASES.get(lowered, lowered)


def _validate_native_call_schema(call_id: str, args: Dict[str, Any]) -> Tuple[str, List[str]]:
    errors: List[str] = []
    normalized_tool = _normalize_native_tool_name(args.get("tool_name"))
    if not normalized_tool:
        errors.append(_schema_error(_SCHEMA_ERR_INPUT_INVALID, call_id, "native_call 缺少 tool_name"))
        return "", errors
    if normalized_tool not in _SUPPORTED_NATIVE_TOOL_NAMES:
        errors.append(
            _schema_error(_SCHEMA_ERR_INPUT_INVALID, call_id, f"native_call tool_name 不支持: {normalized_tool}")
        )
        return normalized_tool, errors

    has_path = bool(_as_nonempty_text(args.get("path")) or _as_nonempty_text(args.get("file_path")))
    if normalized_tool in {"read_file", "write_file", "file_ast_skeleton", "file_ast_chunk_read", "git_checkout_file"}:
        if not has_path:
            errors.append(
                _schema_error(
                    _SCHEMA_ERR_INPUT_INVALID,
                    call_id,
                    f"{normalized_tool} 缺少 path/file_path",
                )
            )

    if normalized_tool == "write_file" and args.get("content") is None:
        errors.append(_schema_error(_SCHEMA_ERR_INPUT_INVALID, call_id, "write_file 缺少 content"))

    if normalized_tool == "run_cmd" and not (
        _as_nonempty_text(args.get("command")) or _as_nonempty_text(args.get("cmd"))
    ):
        errors.append(_schema_error(_SCHEMA_ERR_INPUT_INVALID, call_id, "run_cmd 缺少 command/cmd"))

    if normalized_tool == "artifact_reader":
        has_ref = bool(
            _as_nonempty_text(args.get("artifact_id"))
            or _as_nonempty_text(args.get("forensic_artifact_ref"))
            or _as_nonempty_text(args.get("raw_result_ref"))
        )
        if not has_ref:
            errors.append(
                _schema_error(
                    _SCHEMA_ERR_INPUT_INVALID,
                    call_id,
                    "artifact_reader 缺少 artifact_id/forensic_artifact_ref/raw_result_ref",
                )
            )

    if normalized_tool == "workspace_txn_apply":
        changes = args.get("changes")
        if not isinstance(changes, list) or not changes:
            errors.append(_schema_error(_SCHEMA_ERR_INPUT_INVALID, call_id, "workspace_txn_apply 缺少 changes[]"))
        else:
            for idx, item in enumerate(changes):
                if not isinstance(item, dict):
                    errors.append(
                        _schema_error(
                            _SCHEMA_ERR_INPUT_INVALID,
                            call_id,
                            f"workspace_txn_apply changes[{idx}] 必须为对象",
                        )
                    )
                    continue
                if not _as_nonempty_text(item.get("path") or item.get("file_path")) or item.get("content") is None:
                    errors.append(
                        _schema_error(
                            _SCHEMA_ERR_INPUT_INVALID,
                            call_id,
                            f"workspace_txn_apply changes[{idx}] 缺少 path/content",
                        )
                    )
                    break

    if normalized_tool == "sleep_and_watch":
        if not has_path:
            errors.append(_schema_error(_SCHEMA_ERR_INPUT_INVALID, call_id, "sleep_and_watch 缺少 log_file/path"))
        if not (_as_nonempty_text(args.get("pattern")) or _as_nonempty_text(args.get("regex"))):
            errors.append(_schema_error(_SCHEMA_ERR_INPUT_INVALID, call_id, "sleep_and_watch 缺少 pattern/regex"))

    return normalized_tool, errors


def _prune_native_call_arguments(
    *,
    normalized_tool: str,
    args: Dict[str, Any],
) -> Tuple[Dict[str, Any], List[str]]:
    """Drop per-tool unsupported fields before firewall validation.

    Firewall remains strict; pruning only removes incompatible keys from model payload.
    """
    allowed = _NATIVE_TOOL_ALLOWED_INPUT_ARGS.get(normalized_tool)
    if allowed is None:
        return dict(args), []

    pruned: Dict[str, Any] = {}
    dropped: List[str] = []
    for key, value in args.items():
        name = str(key)
        if name.startswith("_") or name in allowed:
            pruned[name] = value
        else:
            dropped.append(name)
    return pruned, sorted(set(dropped))


def _enforce_tool_result_schema(
    result: Any,
    *,
    call: Dict[str, Any],
    call_id: str,
    default_service_name: str,
    default_tool_name: str,
) -> Dict[str, Any]:
    rollout = _resolve_tool_contract_rollout_runtime()
    if not isinstance(result, dict):
        detail = f"result payload must be object, got {type(result).__name__}"
        return {
            "tool_call": call,
            "result": _schema_error(_SCHEMA_ERR_OUTPUT_INVALID, call_id, detail),
            "status": "error",
            "service_name": "tool_protocol",
            "tool_name": "validation",
            "error_code": _SCHEMA_ERR_OUTPUT_INVALID,
            "_contract_rollout": {
                **rollout.snapshot(),
                "used_legacy": False,
                "used_new": False,
                "legacy_blocked": False,
            },
        }

    normalized_result: Dict[str, Any] = dict(result)
    errors: List[str] = []
    status = _as_nonempty_text(normalized_result.get("status")).lower()
    if not status:
        errors.append("missing status")
    elif status not in _VALID_RESULT_STATUS:
        errors.append(f"unsupported status={status}")
    if not _as_nonempty_text(normalized_result.get("service_name")):
        errors.append("missing service_name")
    if not _as_nonempty_text(normalized_result.get("tool_name")):
        errors.append("missing tool_name")

    has_legacy_payload = "result" in normalized_result
    has_new_payload = _has_new_contract_payload(normalized_result)
    if not has_legacy_payload and not has_new_payload:
        errors.append("missing result payload")

    legacy_blocked = bool(has_legacy_payload and not has_new_payload and not rollout.legacy_contract_enabled)
    if legacy_blocked:
        errors.append("legacy-only result blocked by decommission gate")

    if errors:
        detail = "; ".join(errors)
        error_code = _SCHEMA_ERR_LEGACY_DECOMMISSIONED if legacy_blocked else _SCHEMA_ERR_OUTPUT_INVALID
        return {
            "tool_call": call,
            "result": _schema_error(error_code, call_id, detail),
            "status": "error",
            "service_name": default_service_name or "tool_protocol",
            "tool_name": default_tool_name or "validation",
            "error_code": error_code,
            "_contract_rollout": {
                **rollout.snapshot(),
                "used_legacy": has_legacy_payload,
                "used_new": has_new_payload,
                "legacy_blocked": legacy_blocked,
            },
        }

    if rollout.new_contract_enabled and not has_new_payload and has_legacy_payload:
        legacy_text = str(normalized_result.get("result", ""))
        normalized_result.setdefault("narrative_summary", legacy_text)
        normalized_result.setdefault("display_preview", legacy_text)
        has_new_payload = True

    if rollout.legacy_contract_enabled and not has_legacy_payload:
        fallback_text = str(normalized_result.get("narrative_summary") or normalized_result.get("display_preview") or "")
        normalized_result["result"] = fallback_text
        has_legacy_payload = True

    normalized_result["_contract_rollout"] = {
        **rollout.snapshot(),
        "used_legacy": has_legacy_payload,
        "used_new": has_new_payload,
        "legacy_blocked": False,
    }
    return normalized_result


def _extract_latest_user_message(messages: List[Dict[str, Any]]) -> str:
    return extract_latest_user_message(messages)


def _looks_like_coding_request(text: str) -> bool:
    if contains_direct_coding_signal(text):
        return True
    lowered = (text or "").lower()
    return any(keyword in lowered for keyword in _CODING_KEYWORDS)


def _stable_contract_checksum(payload: Dict[str, Any]) -> str:
    normalized = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


def _looks_like_write_intent(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    if not lowered:
        return False
    write_markers = (
        "修改",
        "改造",
        "重构",
        "实现",
        "修复",
        "提交",
        "发布",
        "部署",
        "回滚",
        "写入",
        "删除",
        "apply",
        "patch",
        "fix",
        "implement",
        "refactor",
        "release",
        "deploy",
        "rollback",
    )
    return any(marker in lowered for marker in write_markers)


def _should_seed_contract(latest_user_request: str) -> bool:
    text = str(latest_user_request or "").strip()
    if not text:
        return False
    return _looks_like_coding_request(text) or _looks_like_write_intent(text)


def _build_seed_contract_state(
    *,
    session_id: str,
    latest_user_request: str,
) -> Optional[Dict[str, Any]]:
    normalized_request = str(latest_user_request or "").strip()
    if not _should_seed_contract(normalized_request):
        return None

    requires_coding_intent = _looks_like_coding_request(normalized_request)
    requires_write_intent = _looks_like_write_intent(normalized_request)
    seed_contract = {
        "session_id": str(session_id or ""),
        "intent_summary": normalized_request[:500],
        "requires_write_intent": bool(requires_write_intent),
        "requires_core_escalation": bool(requires_coding_intent or requires_write_intent),
        "acceptance_hint": "提供可验证证据路径（例如 scratch/reports/...）",
        "evidence_path_hint": "scratch/reports/",
        "created_at_ms": int(time.time() * 1000),
    }
    seed_checksum = _stable_contract_checksum(seed_contract)
    seed_contract_id = f"seed_{seed_checksum[:12]}"
    return {
        "stage": "seed",
        "seed_contract": seed_contract,
        "seed_contract_id": seed_contract_id,
        "seed_contract_checksum": seed_checksum,
        "execution_contract": {},
        "execution_contract_id": "",
        "execution_contract_checksum": "",
        "contract_upgrade_latency_ms": None,
        "upgraded_round": 0,
    }


def _upgrade_seed_to_execution_contract_state(
    *,
    contract_state: Optional[Dict[str, Any]],
    actionable_calls: List[Dict[str, Any]],
    round_num: int,
    elapsed_ms: float,
) -> Optional[Dict[str, Any]]:
    if not isinstance(contract_state, dict):
        return contract_state
    if str(contract_state.get("stage") or "").strip().lower() == "execution":
        return contract_state
    if not actionable_calls:
        return contract_state

    mutating_call_count = 0
    call_specs: List[Dict[str, Any]] = []
    existing_contract_ids = set()
    for call in actionable_calls:
        if _is_mutating_native_call(call):
            mutating_call_count += 1
        cid = str(call.get("contract_id") or "").strip()
        if cid:
            existing_contract_ids.add(cid)
        call_specs.append(
            {
                "agent_type": str(call.get("agentType") or "").strip().lower(),
                "service_name": str(call.get("service_name") or "").strip().lower(),
                "tool_name": str(call.get("tool_name") or "").strip().lower(),
                "risk_level": str(call.get("_risk_level") or call.get("risk_level") or "").strip().lower(),
                "mutating": bool(_is_mutating_native_call(call)),
            }
        )

    if len(existing_contract_ids) == 1:
        execution_contract_id = next(iter(existing_contract_ids))
    else:
        seed_checksum = str(contract_state.get("seed_contract_checksum") or "")
        execution_contract_id = f"exec_{seed_checksum[:12] or uuid.uuid4().hex[:12]}"

    execution_contract = {
        "source_seed_contract_id": str(contract_state.get("seed_contract_id") or ""),
        "mutating_call_count": int(mutating_call_count),
        "total_call_count": int(len(actionable_calls)),
        "call_specs": call_specs,
        "requires_parallel_contract_gate": bool(mutating_call_count > 1),
        "upgraded_round": int(round_num),
        "upgraded_at_ms": int(time.time() * 1000),
    }
    execution_checksum = _stable_contract_checksum(execution_contract)

    upgraded = dict(contract_state)
    upgraded["stage"] = "execution"
    upgraded["execution_contract"] = execution_contract
    upgraded["execution_contract_id"] = execution_contract_id
    upgraded["execution_contract_checksum"] = execution_checksum
    upgraded["upgraded_round"] = int(round_num)
    upgraded["contract_upgrade_latency_ms"] = max(0.0, float(elapsed_ms))
    return upgraded


def _bind_execution_contract_to_calls(
    actionable_calls: List[Dict[str, Any]],
    *,
    contract_state: Optional[Dict[str, Any]],
) -> None:
    if not isinstance(contract_state, dict):
        return
    if str(contract_state.get("stage") or "").strip().lower() != "execution":
        return
    execution_contract_id = str(contract_state.get("execution_contract_id") or "").strip()
    execution_checksum = str(contract_state.get("execution_contract_checksum") or "").strip()
    if not execution_contract_id or not execution_checksum:
        return

    for call in actionable_calls:
        call["_contract_stage"] = "execution"
        call["_contract_id"] = execution_contract_id
        call["_contract_checksum"] = execution_checksum
        if _is_mutating_native_call(call):
            call.setdefault("contract_id", execution_contract_id)
            call.setdefault("contract_checksum", execution_checksum)


def _build_contract_state_event_payload(
    *,
    contract_state: Dict[str, Any],
    transition: str,
    round_num: int,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "round": int(round_num),
        "transition": str(transition or "state_update"),
        "contract_stage": str(contract_state.get("stage") or ""),
        "seed_contract_id": str(contract_state.get("seed_contract_id") or ""),
        "seed_contract_checksum": str(contract_state.get("seed_contract_checksum") or ""),
        "execution_contract_id": str(contract_state.get("execution_contract_id") or ""),
        "execution_contract_checksum": str(contract_state.get("execution_contract_checksum") or ""),
    }
    latency_ms = contract_state.get("contract_upgrade_latency_ms")
    if latency_ms is not None:
        try:
            payload["contract_upgrade_latency_ms"] = max(0.0, float(latency_ms))
        except Exception:
            pass
    seed_contract = contract_state.get("seed_contract")
    if isinstance(seed_contract, dict):
        payload["requires_core_escalation"] = bool(seed_contract.get("requires_core_escalation"))
        payload["requires_write_intent"] = bool(seed_contract.get("requires_write_intent"))
    payload["upgraded_round"] = int(contract_state.get("upgraded_round") or 0)
    return payload


def _build_l1_5_prompt_slice_context(
    *,
    episodic_context: str,
    contract_state: Optional[Dict[str, Any]],
    agent_state: Optional[Dict[str, Any]],
    submit_result_called: bool,
) -> str:
    normalized_episodic = str(episodic_context or "").strip()
    if normalized_episodic.startswith("[Episodic Memory Reinjection]"):
        normalized_episodic = normalized_episodic.split("\n", 1)[1].strip() if "\n" in normalized_episodic else ""

    normalized_agent_state = dict(agent_state or {})
    task_completed = bool(normalized_agent_state.get("task_completed") is True)
    pending_actions = _normalize_submit_string_list(normalized_agent_state.get("pending_actions"))

    lines: List[str] = [
        _L15_SLICE_MARKER,
        f"slice_uid: {_ATOMIC_CTRL_SLICE_UID}",
        f"slice_protocol: {_ATOMIC_CTRL_PROTOCOL_VERSION}",
        "ttl_scope: task_lifecycle",
        "[AtomicControlPlane]",
        "该区块为原子注入控制面：需一次性读取并同时遵守，不要拆分执行。",
        "[CompletionGate]",
        "仅当以下条件同时满足，才能视为工具循环完成：",
        "1) agent_state.task_completed == true",
        f"2) 已调用 {_SUBMIT_RESULT_TOOL_NAME} 并更新状态",
        f"若任务完成，必须调用 {_SUBMIT_RESULT_TOOL_NAME}(task_completed=true, final_answer=..., deliverables=[...])。",
        f"若任务未完成，可调用 {_SUBMIT_RESULT_TOOL_NAME}(task_completed=false, pending_actions=[...])，并继续工具执行。",
        "[AgentState]",
        f"task_completed: {'true' if task_completed else 'false'}",
        f"submit_result_called: {'true' if bool(submit_result_called) else 'false'}",
        f"submit_result_round: {int(normalized_agent_state.get('submit_result_round') or 0)}",
    ]
    if pending_actions:
        lines.append("pending_actions: " + "; ".join(pending_actions))

    lines.append("[ContractState]")
    if isinstance(contract_state, dict):
        stage = str(contract_state.get("stage") or "")
        lines.append(f"contract_stage: {stage}")
        lines.append(f"seed_contract_id: {str(contract_state.get('seed_contract_id') or '')}")
        lines.append(f"seed_contract_checksum: {str(contract_state.get('seed_contract_checksum') or '')}")
        if stage == "execution":
            lines.append(f"execution_contract_id: {str(contract_state.get('execution_contract_id') or '')}")
            lines.append(
                f"execution_contract_checksum: {str(contract_state.get('execution_contract_checksum') or '')}"
            )
    else:
        lines.append("contract_stage: unknown")

    if normalized_episodic:
        lines.append("[Episodic Memory Reinjection]")
        lines.append(normalized_episodic)

    lines.append("若历史经验与当前事实冲突，以当前事实为准。")
    return "\n".join(lines)


def _inject_ephemeral_system_context(messages: List[Dict[str, Any]], content: str) -> bool:
    text = str(content or "").strip()
    if not text:
        return False

    normalized = text if _L15_SLICE_MARKER in text else f"{_L15_SLICE_MARKER}\n{text}"

    for index, msg in enumerate(messages):
        if str(msg.get("role", "")).strip() != "system":
            continue
        if _L15_SLICE_MARKER not in str(msg.get("content", "")):
            continue
        if str(msg.get("content", "")).strip() == normalized:
            return False
        messages[index] = {"role": "system", "content": normalized}
        return True

    insert_at = 0
    while insert_at < len(messages) and str(messages[insert_at].get("role", "")).strip() == "system":
        insert_at += 1
    messages.insert(insert_at, {"role": "system", "content": normalized})
    return True


def _is_mutating_native_call(call: Dict[str, Any]) -> bool:
    if str(call.get("agentType", "")).strip().lower() != "native":
        return False
    tool_name = str(call.get("tool_name", "")).strip().lower()
    return tool_name in _MUTATING_NATIVE_TOOL_NAMES


def _build_tool_envelope_from_call(call: Dict[str, Any]) -> ToolCallEnvelope:
    tool_name = str(call.get("tool_name", "") or "unknown")
    legacy_call = {
        "tool_name": tool_name,
        "_tool_call_id": call.get("_tool_call_id"),
        "arguments": {k: v for k, v in call.items() if not str(k).startswith("_")},
    }
    return ToolCallEnvelope.from_legacy_call(
        legacy_call,
        session_id=str(call.get("_session_id") or "") or None,
        trace_id=str(call.get("_trace_id") or "") or None,
    )


def _inject_call_context_metadata(
    call: Dict[str, Any],
    *,
    call_id: str,
    trace_id: str,
    session_id: Optional[str],
) -> None:
    """Attach normalized trace/session/risk metadata onto a dispatched call."""
    call["_tool_call_id"] = call_id
    call["_trace_id"] = trace_id
    if session_id:
        call["_session_id"] = session_id
    if "_fencing_epoch" not in call:
        call["_fencing_epoch"] = call.get("fencing_epoch")
    try:
        envelope = _build_tool_envelope_from_call(call)
        call["_risk_level"] = envelope.risk_level.value
        call["_execution_scope"] = envelope.execution_scope.value
        call["_requires_global_mutex"] = bool(envelope.requires_global_mutex)
    except Exception:
        call.setdefault("_risk_level", "read_only")
        call.setdefault("_execution_scope", "local")
        call.setdefault("_requires_global_mutex", False)
    try:
        _evaluate_risk_gate(call)
    except Exception:
        call.setdefault("_approval_required", False)


def _requires_global_mutex(call: Dict[str, Any]) -> bool:
    try:
        envelope = _build_tool_envelope_from_call(call)
        return bool(envelope.requires_global_mutex)
    except Exception:
        return False


def _apply_parallel_contract_gate(actionable_calls: List[Dict[str, Any]]) -> ParallelContractGateDecision:
    """
    WS13-002 + WS24x(P2):
    - Parallel mutating calls must share the same non-empty contract_id.
    - Parallel mutating calls must carry non-empty contract_checksum.
    - Missing checksum on parallel mutating writes downgrades this round to readonly exploration.
    """
    mutating_native_calls = [call for call in actionable_calls if _is_mutating_native_call(call)]
    if len(mutating_native_calls) <= 1:
        return ParallelContractGateDecision(
            actionable_calls=actionable_calls,
            messages=[],
            validation_errors=[],
        )

    missing_checksum_calls = [
        call
        for call in mutating_native_calls
        if not str(call.get("contract_checksum") or "").strip()
    ]
    if missing_checksum_calls:
        passthrough_calls = [call for call in actionable_calls if not _is_mutating_native_call(call)]
        validation_errors: List[str] = []
        for idx, call in enumerate(missing_checksum_calls, 1):
            call_id = str(call.get("_tool_call_id") or f"parallel_write_{idx}")
            call["_contract_gate_blocked"] = True
            call["_contract_gate_reason"] = _CONTRACT_GATE_REASON_READONLY_DOWNGRADE
            validation_errors.append(
                _schema_error(
                    _SCHEMA_ERR_INPUT_INVALID,
                    call_id,
                    "并行写任务缺少 contract_checksum，已降级为只读探索；请先建立 execution contract 后重试。",
                )
            )

        message = (
            "Contract gate: parallel mutating calls missing contract_checksum; "
            "downgraded to readonly exploration for this round."
        )
        return ParallelContractGateDecision(
            actionable_calls=passthrough_calls,
            messages=[message],
            force_serial=False,
            readonly_downgraded=True,
            dropped_mutating_calls=len(mutating_native_calls),
            validation_errors=validation_errors,
            reason=_CONTRACT_GATE_REASON_READONLY_DOWNGRADE,
        )

    contract_ids = {
        str(call.get("contract_id") or "").strip()
        for call in mutating_native_calls
    }
    checksum_values = {
        str(call.get("contract_checksum") or "").strip()
        for call in mutating_native_calls
        if str(call.get("contract_checksum") or "").strip()
    }

    gate_messages: List[str] = []
    force_serial = False
    if "" in contract_ids or len(contract_ids) != 1:
        force_serial = True
        gate_messages.append(
            "Contract gate: parallel mutating calls missing/mismatched contract_id; downgraded to serial execution."
        )
    if len(checksum_values) > 1:
        force_serial = True
        gate_messages.append(
            "Contract gate: parallel mutating calls mismatched contract_checksum; downgraded to serial execution."
        )

    if force_serial:
        for call in mutating_native_calls:
            call["_force_serial"] = True

    return ParallelContractGateDecision(
        actionable_calls=actionable_calls,
        messages=gate_messages,
        force_serial=force_serial,
        validation_errors=[],
    )


def _apply_coding_route_guard(
    actionable_calls: List[Dict[str, Any]],
    *,
    latest_user_request: str,
) -> Tuple[List[Dict[str, Any]], int]:
    """Coding-route force injection has been retired from execution path."""
    _ = latest_user_request
    return actionable_calls, 0


_WORKFLOW_PHASES = {"plan", "execute", "verify", "repair"}
_WORKFLOW_PHASE_STATUS = {"start", "success", "error", "skip"}


def _build_loop_event(event_type: str, data: Any) -> Dict[str, Any]:
    payload = {
        "type": event_type,
        "schema_version": _SSE_PROTOCOL_VERSION,
        "event_ts": int(time.time() * 1000),
    }
    if isinstance(data, dict):
        payload.update(data)
    else:
        payload["data"] = data
    return payload


def _format_workflow_stage_event(
    round_num: int,
    phase: str,
    status: str,
    *,
    policy: AgenticLoopPolicy,
    reason: str = "",
    decision: str = "",
    details: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    if not policy.emit_workflow_stage_events:
        return None

    normalized_phase = phase if phase in _WORKFLOW_PHASES else "verify"
    normalized_status = status if status in _WORKFLOW_PHASE_STATUS else "start"
    payload: Dict[str, Any] = {
        "round": round_num,
        "phase": normalized_phase,
        "status": normalized_status,
    }
    if reason:
        payload["reason"] = reason
    if decision:
        payload["decision"] = decision
    if details:
        payload.update(details)
    return _build_loop_event("tool_stage", payload)


def _parse_structured_tool_calls_payload(raw_payload: Any) -> List[Dict[str, Any]]:
    def _normalize(value: Any) -> List[Dict[str, Any]]:
        if isinstance(value, dict):
            return [value]
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        return []

    # Strict protocol: tool_calls must already be structured objects from model delta.
    if isinstance(raw_payload, (dict, list)):
        return _normalize(raw_payload)
    return []


def _shorten_for_log(value: Any, limit: int = 300) -> str:
    text = str(value)
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def _normalize_mcp_call_payload(call: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(call or {})

    nested_args = normalized.get("arguments")
    if isinstance(nested_args, dict):
        for key, value in nested_args.items():
            normalized.setdefault(key, value)
    return normalized


def _extract_mcp_call_status(raw_result: Any) -> Tuple[str, str]:
    if raw_result is None:
        return "ok", "(empty mcp response)"
    if isinstance(raw_result, dict):
        status = str(raw_result.get("status", "ok"))
        if "message" in raw_result:
            detail = raw_result.get("message", "")
        elif "result" in raw_result:
            detail = raw_result.get("result", "")
        else:
            detail = raw_result
        return status, _shorten_for_log(detail)
    if not isinstance(raw_result, str):
        return "ok", _shorten_for_log(raw_result)
    try:
        parsed = json.loads(raw_result)
    except Exception:
        return "ok", _shorten_for_log(raw_result)

    if not isinstance(parsed, dict):
        return "ok", _shorten_for_log(raw_result)

    status = str(parsed.get("status", "ok"))
    if "message" in parsed:
        detail = parsed.get("message", "")
    elif "result" in parsed:
        detail = parsed.get("result", "")
    else:
        detail = raw_result
    return status, _shorten_for_log(detail)


# ---------------------------------------------------------------------------
# 工具执行
# ---------------------------------------------------------------------------


async def _execute_mcp_call(call: Dict[str, Any]) -> Dict[str, Any]:
    """执行单个MCP调用"""
    call = _normalize_mcp_call_payload(call)
    service_name = call.get("service_name", "")
    tool_name = call.get("tool_name", "")
    call_id = str(call.get("_tool_call_id") or f"mcp_call_{tool_name or 'unknown'}")

    logger.info(
        "[AgenticLoop] MCP tool start id=%s service=%s tool=%s payload_keys=%s",
        call_id,
        service_name or "<missing>",
        tool_name or "<missing>",
        sorted(call.keys()),
    )

    try:
        from mcpserver.mcp_manager import get_mcp_manager

        manager = get_mcp_manager()
        result = await manager.unified_call(service_name, call)
        mcp_status, mcp_detail = _extract_mcp_call_status(result)
        if mcp_status == "error":
            logger.warning(
                "[AgenticLoop] MCP tool failed id=%s service=%s tool=%s detail=%s",
                call_id,
                service_name,
                tool_name,
                mcp_detail,
            )
            return _upgrade_tool_result_contract_payload({
                "tool_call": call,
                "result": result,
                "status": "error",
                "service_name": service_name,
                "tool_name": tool_name,
            })
        logger.info(
            "[AgenticLoop] MCP tool success id=%s service=%s tool=%s detail=%s",
            call_id,
            service_name,
            tool_name,
            mcp_detail,
        )
        return _upgrade_tool_result_contract_payload({
            "tool_call": call,
            "result": result,
            "status": "success",
            "service_name": service_name,
            "tool_name": tool_name,
        })
    except Exception as e:
        logger.error("[AgenticLoop] MCP调用异常 id=%s service=%s tool=%s error=%s", call_id, service_name, tool_name, e)
        return _upgrade_tool_result_contract_payload({
            "tool_call": call,
            "result": f"调用失败: {e}",
            "status": "error",
            "service_name": service_name,
            "tool_name": tool_name,
        })
async def _execute_native_call(call: Dict[str, Any], session_id: str) -> Dict[str, Any]:
    """执行单个本地native调用"""
    executor = get_native_tool_executor()
    return await executor.execute(call, session_id=session_id)


async def _execute_single_tool_call(call: Dict[str, Any], session_id: str) -> Dict[str, Any]:
    agent_type = call.get("agentType", "")
    if agent_type == "mcp":
        return await _execute_mcp_call(call)
    if agent_type == "native":
        return await _execute_native_call(call, session_id)

    logger.warning(f"[AgenticLoop] 未知agentType: {agent_type}, 跳过: {call}")
    return {
        "tool_call": call,
        "result": f"未知agentType: {agent_type}",
        "status": "error",
        "service_name": "unknown",
        "tool_name": "unknown",
    }


async def _execute_tool_call_with_retry(
    call: Dict[str, Any],
    session_id: str,
    *,
    semaphore: asyncio.Semaphore,
    retry_failed: bool,
    max_retries: int,
    retry_backoff_seconds: float,
) -> Dict[str, Any]:
    max_attempts = max(1, int(max_retries) + 1)
    max_delegate_turns = _clamp_int(call.get("max_delegate_turns"), MAX_DELEGATE_TURNS, 1, 20)
    tracked_conflict_ticket = ""
    tracked_delegate_turns = 0
    call_id = str(call.get("_tool_call_id") or f"tool_{uuid.uuid4().hex[:8]}")
    agent_type = str(call.get("agentType", ""))
    service_name = str(call.get("service_name", ""))
    tool_name = str(call.get("tool_name", call.get("task_type", "")))
    for attempt in range(1, max_attempts + 1):
        logger.info(
            "[AgenticLoop] tool attempt start id=%s agent=%s service=%s tool=%s attempt=%s/%s",
            call_id,
            agent_type,
            service_name or "<n/a>",
            tool_name or "<n/a>",
            attempt,
            max_attempts,
        )
        risk_gate = _evaluate_risk_gate(call)
        approval_hook = {
            "required": bool(risk_gate.get("requires_approval")),
            "policy": risk_gate.get("approval_policy"),
            "granted": bool(risk_gate.get("approval_granted")),
            "risk_level": risk_gate.get("risk_level"),
        }
        lease: Optional[LeaseHandle] = None
        heartbeat_task: Optional[asyncio.Task[None]] = None
        stop_heartbeat = asyncio.Event()
        heartbeat_errors: List[str] = []
        mutex_manager = None
        mutex_scavenge_report: Dict[str, Any] = {}
        if not bool(risk_gate.get("allowed", True)):
            result = {
                "tool_call": call,
                "result": f"{risk_gate.get('reason', 'risk gate blocked')}",
                "status": "error",
                "service_name": "tool_protocol",
                "tool_name": tool_name or "risk_gate",
                "error_code": str(risk_gate.get("error_code") or _RISK_ERR_POLICY_BLOCKED),
                "approval_hook": approval_hook,
            }
        else:
            try:
                if _requires_global_mutex(call):
                    mutex_manager = get_global_mutex_manager()
                    try:
                        mutex_scavenge_report = await mutex_manager.scan_and_reap_expired(
                            reason=f"tool_call_pre_acquire:{call_id}:attempt:{attempt}"
                        )
                    except Exception as scavenge_exc:
                        mutex_scavenge_report = {"cleanup_mode": "scan_error", "scan_error": type(scavenge_exc).__name__}
                    if mutex_scavenge_report:
                        call["_mutex_scavenge_report"] = dict(mutex_scavenge_report)
                    lease = await mutex_manager.acquire(
                        owner_id=str(session_id or call.get("_session_id") or "unknown_session"),
                        job_id=call_id,
                        ttl_seconds=10.0,
                        wait_timeout_seconds=30.0,
                        poll_interval_seconds=0.2,
                    )
                    call["_fencing_epoch"] = lease.fencing_epoch

                    async def _heartbeat_loop() -> None:
                        nonlocal lease
                        if lease is None:
                            return
                        interval = max(1.0, min(5.0, lease.ttl_seconds / 2.0))
                        while not stop_heartbeat.is_set():
                            await asyncio.sleep(interval)
                            if stop_heartbeat.is_set():
                                return
                            try:
                                lease = await mutex_manager.renew(lease)  # type: ignore[union-attr]
                            except Exception as hb_exc:
                                heartbeat_errors.append(str(hb_exc))
                                return

                    heartbeat_task = asyncio.create_task(_heartbeat_loop())

                async with semaphore:
                    result = await _execute_single_tool_call(call, session_id)

                if heartbeat_errors:
                    result = {
                        "tool_call": call,
                        "result": f"lease heartbeat failed: {'; '.join(heartbeat_errors)}",
                        "status": "error",
                        "service_name": "runtime",
                        "tool_name": tool_name or "unknown",
                        "error_code": "E_MUTEX_HEARTBEAT_FAILED",
                    }
                    if mutex_manager is not None:
                        try:
                            heartbeat_scavenge = await mutex_manager.scan_and_reap_expired(
                                reason=f"tool_call_heartbeat_failure:{call_id}:attempt:{attempt}"
                            )
                            if heartbeat_scavenge:
                                result["mutex_scavenge_report"] = heartbeat_scavenge
                        except Exception as scavenge_exc:
                            result["mutex_scavenge_report"] = {
                                "cleanup_mode": "scan_error",
                                "scan_error": type(scavenge_exc).__name__,
                            }
            except Exception as e:
                result = {
                    "tool_call": call,
                    "result": f"执行异常: {e}",
                    "status": "error",
                    "service_name": "unknown",
                    "tool_name": "unknown",
                    "error_code": "E_TOOL_EXECUTION_EXCEPTION",
                    "stack_trace": traceback.format_exc(),
                }
            finally:
                stop_heartbeat.set()
                if heartbeat_task is not None:
                    try:
                        await heartbeat_task
                    except Exception:
                        pass
                if lease is not None and mutex_manager is not None:
                    try:
                        await mutex_manager.release(lease)
                    except Exception:
                        pass
        if mutex_scavenge_report and "mutex_scavenge_report" not in result:
            result["mutex_scavenge_report"] = mutex_scavenge_report
        if approval_hook.get("required"):
            result.setdefault("approval_hook", approval_hook)

        if isinstance(result, dict):
            result = _upgrade_tool_result_contract_payload(result)
        result = _enforce_tool_result_schema(
            result,
            call=call,
            call_id=call_id,
            default_service_name=service_name or "tool_protocol",
            default_tool_name=tool_name or "validation",
        )
        _attach_tool_receipt(call, result)
        if result.get("error_code") == _SCHEMA_ERR_OUTPUT_INVALID:
            logger.warning(
                "[AgenticLoop] output schema rejected id=%s detail=%s",
                call_id,
                _shorten_for_log(_coalesce_result_text(result)),
            )

        logger.info(
            "[AgenticLoop] tool attempt done id=%s status=%s service=%s tool=%s result=%s",
            call_id,
            result.get("status", "unknown"),
            result.get("service_name", service_name or "unknown"),
            result.get("tool_name", tool_name or "unknown"),
            _shorten_for_log(_coalesce_result_text(result)),
        )

        if result.get("status") != "error":
            if attempt > 1:
                result["retry_attempts"] = attempt - 1
            return result
        if result.get("error_code") in {_RISK_ERR_APPROVAL_REQUIRED, _RISK_ERR_POLICY_BLOCKED}:
            return result

        arbiter_signal = evaluate_workspace_conflict_retry(
            call,
            result,
            previous_conflict_ticket=tracked_conflict_ticket,
            previous_delegate_turns=tracked_delegate_turns,
            max_delegate_turns=max_delegate_turns,
        )
        if arbiter_signal is not None:
            tracked_conflict_ticket = arbiter_signal.conflict_ticket or tracked_conflict_ticket
            tracked_delegate_turns = arbiter_signal.delegate_turns
            result["conflict_ticket"] = tracked_conflict_ticket
            result["delegate_turns"] = tracked_delegate_turns
            result["freeze"] = arbiter_signal.freeze
            result["hitl"] = arbiter_signal.hitl
            result["router_arbiter"] = arbiter_signal.to_payload()
            if arbiter_signal.escalated:
                result["retry_attempts"] = attempt - 1
                logger.warning(
                    "[AgenticLoop] router arbiter escalation id=%s conflict_ticket=%s delegate_turns=%s threshold=%s",
                    call_id,
                    tracked_conflict_ticket or "<unknown>",
                    tracked_delegate_turns,
                    max_delegate_turns,
                )
                return result

        if not retry_failed:
            return result
        if attempt >= max_attempts:
            result["retry_attempts"] = max_attempts - 1
            return result
        if not _is_retryable_tool_failure(call, result):
            return result

        await asyncio.sleep(max(0.0, min(10.0, retry_backoff_seconds * attempt)))

    fallback_row = {
        "tool_call": call,
        "result": "执行异常: 未知重试状态",
        "status": "error",
        "service_name": "unknown",
        "tool_name": "unknown",
        "error_code": "E_TOOL_EXECUTION_UNKNOWN_RETRY_STATE",
    }
    fallback_row = _upgrade_tool_result_contract_payload(fallback_row)
    fallback_row = _enforce_tool_result_schema(
        fallback_row,
        call=call,
        call_id=call_id,
        default_service_name=service_name or "tool_protocol",
        default_tool_name=tool_name or "validation",
    )
    _attach_tool_receipt(call, fallback_row)
    return fallback_row


async def execute_tool_calls(
    tool_calls: List[Dict[str, Any]],
    session_id: str,
    *,
    max_parallel_calls: int = 8,
    retry_failed: bool = True,
    max_retries: int = 1,
    retry_backoff_seconds: float = 0.8,
) -> List[Dict[str, Any]]:
    """并发执行工具调用，支持重试与并发控制。"""
    if not tool_calls:
        return []

    force_serial = any(bool(call.get("_force_serial", False)) for call in tool_calls)
    parallel_limit = 1 if force_serial else _clamp_int(max_parallel_calls, 8, 1, 64)
    semaphore = asyncio.Semaphore(parallel_limit)

    tasks = [
        _execute_tool_call_with_retry(
            call,
            session_id,
            semaphore=semaphore,
            retry_failed=retry_failed,
            max_retries=max_retries,
            retry_backoff_seconds=retry_backoff_seconds,
        )
        for call in tool_calls
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)
    final: List[Dict[str, Any]] = []
    for idx, r in enumerate(results):
        if isinstance(r, Exception):
            failed_call = tool_calls[idx] if idx < len(tool_calls) else {}
            row = {
                "tool_call": failed_call,
                "result": f"执行异常: {r}",
                "status": "error",
                "service_name": "unknown",
                "tool_name": "unknown",
                "error_code": "E_TOOL_EXECUTION_GATHER_EXCEPTION",
                "stack_trace": "".join(traceback.format_exception(type(r), r, r.__traceback__)),
            }
            row = _upgrade_tool_result_contract_payload(row)
            row = _enforce_tool_result_schema(
                row,
                call=failed_call,
                call_id=str(failed_call.get("_tool_call_id") or f"tool_error_{idx + 1}"),
                default_service_name="tool_protocol",
                default_tool_name=str(failed_call.get("tool_name") or "validation"),
            )
            _attach_tool_receipt(failed_call, row)
            final.append(row)
        else:
            final.append(r)
    return final


def _build_gc_reader_suggestion_result(reason: str, suggestion: str, error_text: str = "") -> Dict[str, Any]:
    lines = [
        "[gc_reader_bridge] 自动证据回读已降级为建议。",
        f"[reason] {reason or 'unknown'}",
    ]
    if error_text:
        lines.append(f"[readback_error] {error_text}")
    if suggestion:
        lines.append(f"[suggested_call] {suggestion}")
    row = {
        "tool_call": {"agentType": "native", "tool_name": "artifact_reader", "_gc_reader_bridge": True},
        "result": "\n".join(lines),
        "status": "success",
        "service_name": "gc_reader_bridge",
        "tool_name": "artifact_reader_suggestion",
    }
    row = _upgrade_tool_result_contract_payload(row)
    _attach_tool_receipt(row["tool_call"], row)
    return row


async def _maybe_execute_gc_reader_followup(
    primary_results: List[Dict[str, Any]],
    session_id: str,
    *,
    round_num: int,
) -> List[Dict[str, Any]]:
    """Execute at most one automatic artifact_reader follow-up for current round."""
    plan = build_gc_reader_followup_plan(primary_results, round_num=round_num, max_calls_per_round=1)
    if not plan.call:
        return []

    logger.info(
        "[AgenticLoop] gc_reader_bridge trigger round=%s source_index=%s reason=%s",
        round_num,
        plan.source_index,
        plan.reason,
    )
    try:
        followup_results = await execute_tool_calls(
            [plan.call],
            session_id,
            max_parallel_calls=1,
            retry_failed=False,
            max_retries=0,
            retry_backoff_seconds=0.0,
        )
    except Exception as exc:
        logger.warning("[AgenticLoop] gc_reader_bridge execution failed round=%s error=%s", round_num, exc)
        return [
            _build_gc_reader_suggestion_result(
                reason=plan.reason,
                suggestion=plan.suggestion,
                error_text=str(exc),
            )
        ]

    if followup_results and followup_results[0].get("status") == "error":
        err_preview = str(followup_results[0].get("result", ""))
        logger.warning(
            "[AgenticLoop] gc_reader_bridge follow-up failed round=%s detail=%s",
            round_num,
            _shorten_for_log(err_preview),
        )
        followup_results.append(
            _build_gc_reader_suggestion_result(
                reason=plan.reason,
                suggestion=plan.suggestion,
                error_text=err_preview,
            )
        )
    return followup_results


# ---------------------------------------------------------------------------
# 格式化
# ---------------------------------------------------------------------------


def format_tool_results_for_llm(results: List[Dict[str, Any]]) -> str:
    """Serialize tool outcomes into structured JSON for deterministic repair/continuation."""

    def _normalize_stack_trace(raw: Any) -> str:
        if isinstance(raw, str):
            text = raw.strip()
            if text:
                return text[:8000]
        return ""

    def _extract_stack_trace_from_text(result_text: str) -> str:
        marker = "Traceback (most recent call last):"
        if marker not in result_text:
            return ""
        return result_text[result_text.find(marker) :][:8000]

    payload_results: List[Dict[str, Any]] = []
    total = len(results)
    for idx, row in enumerate(results, start=1):
        if not isinstance(row, dict):
            continue
        status = str(row.get("status") or "unknown")
        service_name = str(row.get("service_name") or "unknown")
        tool_name = str(row.get("tool_name") or "")
        result_text = _coalesce_result_text(row)
        receipt = row.get("tool_receipt") if isinstance(row.get("tool_receipt"), dict) else {}
        result_info = receipt.get("result") if isinstance(receipt, dict) and isinstance(receipt.get("result"), dict) else {}
        error_code = str(
            row.get("error_code")
            or (result_info.get("error_code") if isinstance(result_info, dict) else "")
            or ""
        )
        stack_trace = _normalize_stack_trace(row.get("stack_trace"))
        if not stack_trace:
            stack_trace = _extract_stack_trace_from_text(result_text)
        memory_card = build_gc_memory_index_card(row, index=idx, total=total)

        entry: Dict[str, Any] = {
            "index": idx,
            "total": total,
            "status": status,
            "service_name": service_name,
            "tool_name": tool_name,
            "result_text": result_text,
            "error_code": error_code,
            "stack_trace": stack_trace,
            "narrative_summary": str(row.get("narrative_summary") or ""),
            "display_preview": str(row.get("display_preview") or ""),
            "forensic_artifact_ref": str(row.get("forensic_artifact_ref") or ""),
            "raw_result_ref": str(row.get("raw_result_ref") or ""),
            "memory_card": memory_card or "",
            "tool_receipt": receipt,
        }
        if status == "error":
            entry["error"] = {
                "code": error_code or "E_TOOL_EXECUTION_FAILED",
                "message": result_text[:4000],
                "stack_trace": stack_trace,
            }
        payload_results.append(entry)

    payload = {
        "schema": "agentic_tool_results.v2",
        "total_results": len(payload_results),
        "results": payload_results,
    }
    return json.dumps(payload, ensure_ascii=False)


def get_agentic_tool_definitions() -> List[Dict[str, Any]]:
    """原生工具调用定义（OpenAI-compatible tools schema）"""
    return [
        {
            "type": "function",
            "function": {
                "name": "native_call",
                "description": "Execute a local native tool in current project workspace.",
                "parameters": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "tool_name": {
                            "type": "string",
                            "enum": [
                                "read_file",
                                "write_file",
                                "get_cwd",
                                "run_cmd",
                                "search_keyword",
                                "query_docs",
                                "list_files",
                                "git_status",
                                "git_diff",
                                "git_log",
                                "git_show",
                                "git_blame",
                                "git_grep",
                                "git_changed_files",
                                "git_checkout_file",
                                "python_repl",
                                "artifact_reader",
                                "file_ast_skeleton",
                                "file_ast_chunk_read",
                                "workspace_txn_apply",
                                "sleep_and_watch",
                                "killswitch_plan",
                                "os_bash",
                            ],
                        },
                        "path": {"type": "string"},
                        "file_path": {"type": "string"},
                        "artifact_id": {"type": "string"},
                        "forensic_artifact_ref": {"type": "string"},
                        "raw_result_ref": {"type": "string"},
                        "content": {"type": "string"},
                        "changes": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "path": {"type": "string"},
                                    "file_path": {"type": "string"},
                                    "content": {"type": "string"},
                                    "mode": {"type": "string", "enum": ["overwrite", "append"]},
                                    "encoding": {"type": "string"},
                                },
                                "required": ["content"],
                            },
                        },
                        "mode": {
                            "type": "string",
                            "enum": ["overwrite", "append", "preview", "line_range", "grep", "jsonpath", "freeze"],
                        },
                        "encoding": {"type": "string"},
                        "command": {"type": "string"},
                        "cmd": {"type": "string"},
                        "cwd": {"type": "string"},
                        "artifact_priority": {"type": "string", "enum": ["low", "normal", "high", "critical"]},
                        "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 1200},
                        "keyword": {"type": "string"},
                        "query": {"type": "string"},
                        "jsonpath": {"type": "string"},
                        "log_file": {"type": "string"},
                        "regex": {"type": "string"},
                        "search_path": {"type": "string"},
                        "repo_path": {"type": "string"},
                        "target_path": {"type": "string"},
                        "pathspec": {"type": "string"},
                        "pattern": {"type": "string"},
                        "ref": {"type": "string"},
                        "base_ref": {"type": "string"},
                        "since": {"type": "string"},
                        "pretty": {"type": "string"},
                        "docker_image": {"type": "string"},
                        "python_cmd": {"type": "string"},
                        "code": {"type": "string"},
                        "expression": {"type": "string"},
                        "sandbox": {"type": "string", "enum": ["restricted", "docker"]},
                        "glob": {"type": "string"},
                        "case_sensitive": {"type": "boolean"},
                        "use_regex": {"type": "boolean"},
                        "short": {"type": "boolean"},
                        "branch": {"type": "boolean"},
                        "porcelain": {"type": "boolean"},
                        "include_untracked": {"type": "boolean"},
                        "confirm": {"type": "boolean"},
                        "cached": {"type": "boolean"},
                        "staged": {"type": "boolean"},
                        "worktree": {"type": "boolean"},
                        "name_only": {"type": "boolean"},
                        "stat": {"type": "boolean"},
                        "stat_only": {"type": "boolean"},
                        "oneline": {"type": "boolean"},
                        "max_results": {"type": "integer", "minimum": 1, "maximum": 1000},
                        "max_count": {"type": "integer", "minimum": 1, "maximum": 500},
                        "max_lines": {"type": "integer", "minimum": 1, "maximum": 5000},
                        "max_file_size_kb": {"type": "integer", "minimum": 64, "maximum": 4096},
                        "unified": {"type": "integer", "minimum": 0, "maximum": 30},
                        "start_line": {"type": "integer", "minimum": 1},
                        "end_line": {"type": "integer", "minimum": 1},
                        "context_before": {"type": "integer", "minimum": 0, "maximum": 200},
                        "context_after": {"type": "integer", "minimum": 0, "maximum": 200},
                        "max_chars": {"type": "integer", "minimum": 200, "maximum": 100000},
                        "max_output_chars": {"type": "integer", "minimum": 200, "maximum": 500000},
                        "poll_interval_seconds": {"type": "number", "minimum": 0.05, "maximum": 10.0},
                        "from_end": {"type": "boolean"},
                        "max_line_chars": {"type": "integer", "minimum": 64, "maximum": 20000},
                        "contract_id": {"type": "string"},
                        "contract_checksum": {"type": "string"},
                        "verify_after_apply": {"type": "boolean"},
                        "oob_allowlist": {"type": "array", "items": {"type": "string"}},
                        "dns_allow": {"type": "boolean"},
                        "recursive": {"type": "boolean"},
                        "approvalPolicy": {"type": "string"},
                        "approval_policy": {"type": "string"},
                        "approval_granted": {"type": "boolean"},
                        "approved": {"type": "boolean"},
                    },
                    "required": ["tool_name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "mcp_call",
                "description": "Invoke one MCP service tool.",
                "parameters": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "service_name": {"type": "string"},
                        "tool_name": {"type": "string"},
                        "arguments": {"type": "object", "additionalProperties": True},
                    },
                    "required": ["tool_name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": _SUBMIT_RESULT_TOOL_NAME,
                "description": (
                    "Atomically submit machine-readable completion state for the current task. "
                    "Task is complete only when this tool is called with task_completed=true."
                ),
                "parameters": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "task_completed": {"type": "boolean"},
                        "outcome_code": {"type": "string"},
                        "state_patch": {"type": "object", "additionalProperties": True},
                        "artifact_refs": {"type": "array", "items": {"type": "string"}},
                        "completion_summary": {"type": "string"},
                        "deliverables": {"type": "array", "items": {"type": "string"}},
                        "pending_actions": {"type": "array", "items": {"type": "string"}},
                        "final_answer": {
                            "type": "string",
                            "description": "Deprecated legacy field. Prefer completion_summary + deliverables.",
                        },
                    },
                    "required": ["task_completed"],
                },
            },
        },
    ]


def _convert_structured_tool_calls(
    structured_calls: List[Dict[str, Any]],
    session_id: Optional[str] = None,
    trace_id: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    转换结构化工具调用，注入上下文元数据

    NGA-WS10-002: 注入 call_id/trace_id/session_id 等上下文元数据
    """
    actionable_calls: List[Dict[str, Any]] = []
    validation_errors: List[str] = []

    # 生成 trace_id（如果未提供）
    if not trace_id:
        trace_id = f"trace_{uuid.uuid4().hex[:16]}"

    for idx, call in enumerate(structured_calls, 1):
        call_id = str(call.get("id") or f"tool_call_{idx}")
        tool_name = str(call.get("name") or "").strip()
        parse_error = call.get("parse_error")
        args = call.get("arguments")

        # 注入上下文元数据（NGA-WS10-002）
        call["_tool_call_id"] = call_id
        call["_trace_id"] = trace_id
        if session_id:
            call["_session_id"] = session_id

        if parse_error:
            validation_errors.append(
                _schema_error(_SCHEMA_ERR_INPUT_INVALID, call_id, f"工具调用参数解析失败: error={parse_error}")
            )
            continue

        if not isinstance(args, dict):
            validation_errors.append(
                _schema_error(
                    _SCHEMA_ERR_INPUT_INVALID,
                    call_id,
                    f"工具调用参数非法: name={tool_name}, arguments必须是对象",
                )
            )
            continue

        if tool_name == "native_call":
            native_tool_name = str(args.get("tool_name") or "").strip()
            if not native_tool_name:
                validation_errors.append(_schema_error(_SCHEMA_ERR_INPUT_INVALID, call_id, "native_call 缺少 tool_name"))
                continue
            normalized_native_tool = _normalize_native_tool_name(native_tool_name)
            pruned_args, dropped_args = _prune_native_call_arguments(
                normalized_tool=normalized_native_tool,
                args=args,
            )
            pruned_args["tool_name"] = normalized_native_tool
            _, native_schema_errors = _validate_native_call_schema(call_id, pruned_args)
            if native_schema_errors:
                validation_errors.extend(native_schema_errors)
                continue
            native_call = {
                "agentType": "native",
                **pruned_args,
            }
            if dropped_args:
                native_call["_dropped_input_args"] = dropped_args
            _inject_call_context_metadata(
                native_call,
                call_id=call_id,
                trace_id=trace_id,
                session_id=session_id,
            )
            actionable_calls.append(native_call)
            continue

        if tool_name == "mcp_call":
            mcp_tool_name = str(args.get("tool_name") or "").strip()
            if not mcp_tool_name:
                validation_errors.append(_schema_error(_SCHEMA_ERR_INPUT_INVALID, call_id, "mcp_call 缺少 tool_name"))
                continue

            merged_call: Dict[str, Any] = {
                "agentType": "mcp",
                "tool_name": mcp_tool_name,
            }
            service_name = str(args.get("service_name") or "").strip()
            if service_name:
                merged_call["service_name"] = service_name

            arg_payload = args.get("arguments") or {}
            if not isinstance(arg_payload, dict):
                validation_errors.append(
                    _schema_error(_SCHEMA_ERR_INPUT_INVALID, call_id, "mcp_call.arguments 必须是对象")
                )
                continue
            legacy_flattened_keys = sorted(
                str(key)
                for key in args.keys()
                if key not in {"tool_name", "service_name", "arguments"}
            )
            if legacy_flattened_keys:
                validation_errors.append(
                    _schema_error(
                        _SCHEMA_ERR_INPUT_INVALID,
                        call_id,
                        "mcp_call 仅支持结构化 arguments 对象，检测到扁平参数: "
                        + ",".join(legacy_flattened_keys),
                    )
                )
                continue
            merged_call.update(arg_payload)
            _inject_call_context_metadata(
                merged_call,
                call_id=call_id,
                trace_id=trace_id,
                session_id=session_id,
            )
            actionable_calls.append(merged_call)
            continue

        if tool_name == _SUBMIT_RESULT_TOOL_NAME:
            task_completed = args.get("task_completed")
            if not isinstance(task_completed, bool):
                validation_errors.append(
                    _schema_error(
                        _SCHEMA_ERR_INPUT_INVALID,
                        call_id,
                        f"{_SUBMIT_RESULT_TOOL_NAME} 的 task_completed 必须是 boolean",
                    )
                )
                continue

            submit_call: Dict[str, Any] = {
                "agentType": "internal",
                "tool_name": _INTERNAL_SUBMIT_TOOL_NAME,
                "task_completed": bool(task_completed),
                "_submit_tool_name": _SUBMIT_RESULT_TOOL_NAME,
            }
            outcome_code = _as_nonempty_text(args.get("outcome_code"))
            final_answer = _as_nonempty_text(args.get("final_answer"))
            completion_summary = _as_nonempty_text(args.get("completion_summary"))
            deliverables = _normalize_submit_string_list(args.get("deliverables"))
            pending_actions = _normalize_submit_string_list(args.get("pending_actions"))
            artifact_refs = _normalize_submit_string_list(args.get("artifact_refs"), max_items=20, max_item_chars=500)
            state_patch = _normalize_submit_state_patch(args.get("state_patch"))
            if outcome_code:
                submit_call["outcome_code"] = outcome_code[:80]
            if final_answer:
                submit_call["final_answer"] = final_answer[:2000]
            if completion_summary:
                submit_call["completion_summary"] = completion_summary[:1200]
            if deliverables:
                submit_call["deliverables"] = deliverables
            if pending_actions:
                submit_call["pending_actions"] = pending_actions
            if artifact_refs:
                submit_call["artifact_refs"] = artifact_refs
            if state_patch:
                submit_call["state_patch"] = state_patch

            _inject_call_context_metadata(
                submit_call,
                call_id=call_id,
                trace_id=trace_id,
                session_id=session_id,
            )
            actionable_calls.append(submit_call)
            continue

        validation_errors.append(_schema_error(_SCHEMA_ERR_INPUT_INVALID, call_id, f"未知函数调用: name={tool_name}"))

    return actionable_calls, validation_errors


def convert_structured_tool_calls(
    structured_calls: List[Dict[str, Any]],
    *,
    session_id: Optional[str] = None,
    trace_id: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Public alias of structured-call converter under canonical namespace."""

    return _convert_structured_tool_calls(
        structured_calls,
        session_id=session_id,
        trace_id=trace_id,
    )


def _build_validation_results(errors: List[str]) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for msg in errors:
        row = {
            "tool_call": {"agentType": "tool_protocol"},
            "result": msg,
            "status": "error",
            "service_name": "tool_protocol",
            "tool_name": "validation",
        }
        _attach_tool_receipt(row["tool_call"], row)
        results.append(row)
    return results


def _apply_submit_result_calls(
    actionable_calls: List[Dict[str, Any]],
    *,
    runtime: AgenticLoopRuntimeState,
    round_num: int,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    passthrough_calls: List[Dict[str, Any]] = []
    submit_calls: List[Dict[str, Any]] = []
    submit_results: List[Dict[str, Any]] = []

    for call in actionable_calls:
        if str(call.get("agentType") or "").strip().lower() != "internal":
            passthrough_calls.append(call)
            continue
        if str(call.get("tool_name") or "").strip().lower() != _INTERNAL_SUBMIT_TOOL_NAME:
            passthrough_calls.append(call)
            continue

        submit_calls.append(call)
        task_completed = bool(call.get("task_completed") is True)
        runtime.submit_result_called = True
        runtime.submit_result_round = int(round_num)
        runtime.agent_state["task_completed"] = task_completed
        runtime.agent_state["submit_result_called"] = True
        runtime.agent_state["submit_result_round"] = int(round_num)

        final_answer = _as_nonempty_text(call.get("final_answer"))
        completion_summary = _as_nonempty_text(call.get("completion_summary"))
        deliverables = _normalize_submit_string_list(call.get("deliverables"))
        pending_actions = _normalize_submit_string_list(call.get("pending_actions"))
        artifact_refs = _normalize_submit_string_list(call.get("artifact_refs"), max_items=20, max_item_chars=500)
        state_patch = _normalize_submit_state_patch(call.get("state_patch"))
        outcome_code = _as_nonempty_text(call.get("outcome_code"))
        if final_answer:
            runtime.agent_state["final_answer"] = final_answer
        if completion_summary:
            runtime.agent_state["completion_summary"] = completion_summary
        if deliverables:
            runtime.agent_state["deliverables"] = deliverables
        if pending_actions:
            runtime.agent_state["pending_actions"] = pending_actions
        if artifact_refs:
            runtime.agent_state["artifact_refs"] = artifact_refs
        if state_patch:
            runtime.agent_state["state_patch"] = state_patch
        if outcome_code:
            runtime.agent_state["outcome_code"] = outcome_code[:80]

        summary_text = completion_summary or final_answer
        if not summary_text:
            summary_text = "task_completed=true" if task_completed else "task_completed=false"
        preview = summary_text[:500]
        handoff_payload = {
            "task_completed": task_completed,
            "round": int(round_num),
            "outcome_code": outcome_code[:80] if outcome_code else "",
            "deliverables": deliverables,
            "pending_actions": pending_actions,
            "artifact_refs": artifact_refs,
            "state_patch": state_patch,
        }
        result_text = json.dumps(handoff_payload, ensure_ascii=False)
        row = {
            "tool_call": call,
            "result": result_text,
            "status": "success",
            "service_name": "agent_state",
            "tool_name": _SUBMIT_RESULT_TOOL_NAME,
            "narrative_summary": summary_text,
            "display_preview": preview,
            "submission": handoff_payload,
        }
        if deliverables:
            row["deliverables"] = deliverables
        if pending_actions:
            row["pending_actions"] = pending_actions
        if artifact_refs:
            row["artifact_refs"] = artifact_refs
            row["forensic_artifact_ref"] = artifact_refs[0]
        if state_patch:
            row["state_patch"] = state_patch
        if outcome_code:
            row["outcome_code"] = outcome_code[:80]
        row = _upgrade_tool_result_contract_payload(row)
        _attach_tool_receipt(call, row)
        submit_results.append(row)

    return passthrough_calls, submit_calls, submit_results

# ---------------------------------------------------------------------------
# SSE 辅助
# ---------------------------------------------------------------------------


def _format_sse_event(event_type: str, data: Any) -> str:
    """格式化扩展SSE事件（JSON SSE 协议）"""
    payload = _build_loop_event(event_type, data)
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _build_execution_receipt_payload(
    *,
    session_id: str,
    runtime: AgenticLoopRuntimeState,
    policy: AgenticLoopPolicy,
) -> Dict[str, Any]:
    task_completed = bool(runtime.agent_state.get("task_completed") is True)
    submit_called = bool(runtime.submit_result_called)
    return {
        "session_id": str(session_id or ""),
        "stop_reason": str(runtime.stop_reason or ""),
        "round_num": int(runtime.round_num),
        "max_rounds": int(policy.max_rounds),
        "task_completed": task_completed,
        "submit_result_called": submit_called,
        "submit_result_round": int(runtime.submit_result_round or 0),
        "total_tool_calls": int(runtime.total_tool_calls),
        "total_tool_success": int(runtime.total_tool_success),
        "total_tool_errors": int(runtime.total_tool_errors),
        "consecutive_tool_failures": int(runtime.consecutive_tool_failures),
        "consecutive_validation_failures": int(runtime.consecutive_validation_failures),
        "consecutive_no_tool_rounds": int(runtime.consecutive_no_tool_rounds),
        "gc_guard": {
            "repeat_count": int(runtime.gc_guard_repeat_count),
            "error_total": int(runtime.gc_guard_error_total),
            "success_total": int(runtime.gc_guard_success_total),
            "hit_total": int(runtime.gc_guard_hit_total),
        },
        "agent_state": dict(runtime.agent_state),
    }


# ---------------------------------------------------------------------------
# Agentic Loop 核心
# ---------------------------------------------------------------------------


async def run_agentic_loop(
    messages: List[Dict[str, Any]],
    session_id: str,
    max_rounds: int = 500,
    model_override: Optional[Dict[str, str]] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """Agentic tool loop 核心（原生结构化 tool calling + 配置化编排控制）。"""
    from apiserver.llm_service import get_llm_service

    llm_service = get_llm_service()
    tool_definitions = get_agentic_tool_definitions()
    policy = _resolve_agentic_loop_policy(max_rounds)
    contract_rollout = _resolve_tool_contract_rollout_runtime()
    runtime = AgenticLoopRuntimeState()
    gc_budget_guard: Optional[GCBudgetGuard] = None
    loop_watchdog = _build_agentic_loop_watchdog()
    loop_cfg = getattr(get_config(), "agentic_loop", None)
    watchdog_sample_per_round = (
        bool(getattr(loop_cfg, "watchdog_sample_per_round", True)) if loop_cfg is not None else True
    )
    if policy.gc_budget_guard_enabled:
        gc_budget_guard = GCBudgetGuard(
            GCBudgetGuardConfig(
                repeat_threshold=policy.gc_budget_repeat_threshold,
                window_size=policy.gc_budget_window_size,
            )
        )
    latest_user_request = _extract_latest_user_message(messages)
    loop_start_monotonic = time.monotonic()
    contract_state = _build_seed_contract_state(
        session_id=session_id,
        latest_user_request=latest_user_request,
    )
    episodic_context_cache = ""

    if contract_rollout.emit_observability_metadata:
        yield _build_loop_event("contract_rollout_snapshot", {"snapshot": contract_rollout.snapshot()})
        if isinstance(contract_state, dict):
            yield _build_loop_event(
                "contract_state",
                _build_contract_state_event_payload(
                    contract_state=contract_state,
                    transition="seed_initialized",
                    round_num=0,
                ),
            )

    if latest_user_request:
        try:
            episodic_context_cache = build_reinjection_context(
                session_id=session_id,
                query=latest_user_request,
                top_k=3,
            )
        except Exception as exc:
            logger.warning("[AgenticLoop] episodic reinjection skipped: %s", exc)
            episodic_context_cache = ""

    for round_num in range(1, policy.max_rounds + 1):
        runtime.round_num = round_num
        atomic_context = _build_l1_5_prompt_slice_context(
            episodic_context=episodic_context_cache,
            contract_state=contract_state,
            agent_state=runtime.agent_state,
            submit_result_called=runtime.submit_result_called,
        )
        if atomic_context and _inject_ephemeral_system_context(messages, atomic_context):
            logger.info("[AgenticLoop] upserted atomic prompt control plane for session=%s round=%s", session_id, round_num)
        if round_num > 1:
            yield _build_loop_event("round_start", {"round": round_num})
        plan_start_event = _format_workflow_stage_event(round_num, "plan", "start", policy=policy)
        if plan_start_event:
            yield plan_start_event

        complete_text = ""
        complete_reasoning = ""
        structured_tool_calls: List[Dict[str, Any]] = []
        stream_terminal_error = ""
        stream_terminal_error_reason = ""
        buffered_round_events: List[Dict[str, Any]] = []

        def _drain_buffered_round_events() -> List[Dict[str, Any]]:
            if not buffered_round_events:
                return []
            drained_raw = list(buffered_round_events)
            buffered_round_events.clear()
            return drained_raw

        round_tool_choice = "required"

        async for chunk in llm_service.stream_chat_with_context(
            messages,
            get_config().api.temperature,
            model_override=model_override,
            tools=tool_definitions,
            tool_choice=round_tool_choice,
        ):
            should_passthrough_chunk = True
            chunk_data: Optional[Dict[str, Any]] = None
            try:
                if isinstance(chunk, dict):
                    chunk_data = dict(chunk)
                elif isinstance(chunk, str) and chunk.startswith("data: "):
                    chunk_data = _decode_sse_payload(chunk)
            except Exception as e:
                logger.warning(f"[AgenticLoop] 解析流式工具调用失败: {e}")

            if isinstance(chunk_data, dict):
                chunk_type = chunk_data.get("type", "content")
                chunk_payload = chunk_data.get("text", "")

                if chunk_type == "content":
                    if isinstance(chunk_payload, str):
                        complete_text += chunk_payload
                        if not stream_terminal_error:
                            detected = _extract_terminal_stream_error_text(complete_text)
                            if detected:
                                stream_terminal_error = detected
                                stream_terminal_error_reason = "llm_stream_error"
                    buffered_round_events.append(chunk_data)
                    should_passthrough_chunk = False
                elif chunk_type == "reasoning":
                    if isinstance(chunk_payload, str):
                        complete_reasoning += chunk_payload
                    buffered_round_events.append(chunk_data)
                    should_passthrough_chunk = False
                elif chunk_type == "tool_calls":
                    parsed_calls = _parse_structured_tool_calls_payload(chunk_payload)
                    structured_tool_calls.extend(parsed_calls)
                    # 原生 tool_calls 事件不透传给前端，统一由 loop 生成 tool_calls/tool_results 事件
                    continue
                elif chunk_type == "auth_expired":
                    stream_terminal_error = (
                        str(chunk_payload).strip() if isinstance(chunk_payload, str) and chunk_payload else "Login expired"
                    )
                    stream_terminal_error_reason = "auth_expired"
                elif chunk_type == "error":
                    stream_terminal_error = (
                        str(chunk_payload).strip() if isinstance(chunk_payload, str) and chunk_payload else "LLM stream error"
                    )
                    stream_terminal_error_reason = "llm_stream_error"

            if should_passthrough_chunk:
                if isinstance(chunk_data, dict):
                    yield chunk_data
                elif isinstance(chunk, str) and chunk.strip() != "data: [DONE]":
                    yield _build_loop_event("raw_chunk", {"text": str(chunk)[:2000]})

        logger.debug(
            f"[AgenticLoop] Round {round_num} complete_text ({len(complete_text)} chars): {complete_text[:300]!r}"
        )

        if not stream_terminal_error:
            detected = _extract_terminal_stream_error_text(complete_text)
            if detected:
                stream_terminal_error = detected
                stream_terminal_error_reason = "llm_stream_error"

        if stream_terminal_error:
            for buffered_chunk in _drain_buffered_round_events():
                yield buffered_chunk
            runtime.stop_reason = stream_terminal_error_reason or "llm_stream_error"
            logger.error(
                "[AgenticLoop] Round %s: 检测到上游流式错误，终止循环: %s",
                round_num,
                stream_terminal_error,
            )
            plan_error_event = _format_workflow_stage_event(
                round_num,
                "plan",
                "error",
                policy=policy,
                reason=runtime.stop_reason,
                details={"error": stream_terminal_error[:500]},
            )
            if plan_error_event:
                yield plan_error_event
            execute_skip_event = _format_workflow_stage_event(
                round_num,
                "execute",
                "skip",
                policy=policy,
                reason=runtime.stop_reason,
            )
            if execute_skip_event:
                yield execute_skip_event
            verify_error_event = _format_workflow_stage_event(
                round_num,
                "verify",
                "error",
                policy=policy,
                reason=runtime.stop_reason,
                decision="stop",
                details={"error": stream_terminal_error[:500]},
            )
            if verify_error_event:
                yield verify_error_event
            yield _build_loop_event("round_end", {"round": round_num, "has_more": False})
            break

        actionable_calls, validation_errors = _convert_structured_tool_calls(
            structured_tool_calls,
            session_id=session_id,
            trace_id=None,  # 自动生成
        )
        actionable_calls, blocked_mutating_calls = _apply_coding_route_guard(
            actionable_calls,
            latest_user_request=latest_user_request,
        )
        if blocked_mutating_calls > 0:
            logger.info(
                "[AgenticLoop] round %s blocked %s mutating native call(s) before route guard",
                round_num,
                blocked_mutating_calls,
            )

        contract_gate = _apply_parallel_contract_gate(actionable_calls)
        actionable_calls = contract_gate.actionable_calls
        if contract_gate.validation_errors:
            validation_errors.extend(contract_gate.validation_errors)

        actionable_calls, submit_result_calls, submit_result_rows = _apply_submit_result_calls(
            actionable_calls,
            runtime=runtime,
            round_num=round_num,
        )
        has_model_tool_activity = bool(actionable_calls or submit_result_calls)

        if contract_gate.messages:
            for msg in contract_gate.messages:
                logger.warning("[AgenticLoop] round %s %s", round_num, msg)
            guardrail_payload: Dict[str, Any] = {
                "round": round_num,
                "type": "contract_gate",
                "force_serial": bool(contract_gate.force_serial),
                "readonly_downgraded": bool(contract_gate.readonly_downgraded),
                "dropped_mutating_calls": int(contract_gate.dropped_mutating_calls),
                "messages": contract_gate.messages,
            }
            if contract_gate.reason:
                guardrail_payload["reason"] = contract_gate.reason
            yield _build_loop_event("guardrail", guardrail_payload)

        if submit_result_calls:
            logger.info(
                "[AgenticLoop] round %s received %s %s call(s), task_completed=%s",
                round_num,
                len(submit_result_calls),
                _SUBMIT_RESULT_TOOL_NAME,
                runtime.agent_state.get("task_completed"),
            )

        if actionable_calls:
            if not isinstance(contract_state, dict):
                contract_state = _build_seed_contract_state(
                    session_id=session_id,
                    latest_user_request=latest_user_request,
                )
                if contract_rollout.emit_observability_metadata and isinstance(contract_state, dict):
                    yield _build_loop_event(
                        "contract_state",
                        _build_contract_state_event_payload(
                            contract_state=contract_state,
                            transition="seed_initialized",
                            round_num=round_num,
                        ),
                    )

            if isinstance(contract_state, dict) and str(contract_state.get("stage") or "") != "execution":
                contract_state = _upgrade_seed_to_execution_contract_state(
                    contract_state=contract_state,
                    actionable_calls=actionable_calls,
                    round_num=round_num,
                    elapsed_ms=(time.monotonic() - loop_start_monotonic) * 1000.0,
                )
                if isinstance(contract_state, dict):
                    _bind_execution_contract_to_calls(actionable_calls, contract_state=contract_state)
                    execution_l1_5 = _build_l1_5_prompt_slice_context(
                        episodic_context=episodic_context_cache,
                        contract_state=contract_state,
                        agent_state=runtime.agent_state,
                        submit_result_called=runtime.submit_result_called,
                    )
                    if execution_l1_5:
                        _inject_ephemeral_system_context(messages, execution_l1_5)
                    if contract_rollout.emit_observability_metadata:
                        yield _build_loop_event(
                            "contract_state",
                            _build_contract_state_event_payload(
                                contract_state=contract_state,
                                transition="seed_to_execution",
                                round_num=round_num,
                            ),
                        )
            else:
                _bind_execution_contract_to_calls(actionable_calls, contract_state=contract_state)

        validation_results = _build_validation_results(validation_errors)

        def _build_round_model_output_event(*, fallback_text: str) -> Dict[str, Any]:
            output_text = complete_text if isinstance(complete_text, str) else str(complete_text)
            placeholder = False
            if not output_text.strip():
                placeholder = True
                output_text = fallback_text
            return _build_loop_event(
                "model_output",
                {
                    "round": round_num,
                    "text": output_text,
                    "placeholder": placeholder,
                    "has_tool_calls": has_model_tool_activity,
                    "validation_errors": len(validation_results),
                },
            )

        if has_model_tool_activity:
            yield _build_round_model_output_event(fallback_text="（本轮模型未返回正文，已发起工具调用或状态提交）")
            for buffered_chunk in _drain_buffered_round_events():
                yield buffered_chunk
            plan_success_event = _format_workflow_stage_event(
                round_num,
                "plan",
                "success",
                policy=policy,
                details={
                    "actionable_calls": len(actionable_calls),
                    "submit_result_calls": len(submit_result_calls),
                    "validation_errors": len(validation_results),
                },
            )
            if plan_success_event:
                yield plan_success_event
        elif validation_results:
            yield _build_round_model_output_event(fallback_text="（本轮模型未返回正文，且工具调用参数/协议校验失败）")
            plan_error_event = _format_workflow_stage_event(
                round_num,
                "plan",
                "error",
                policy=policy,
                reason="validation_errors",
                details={"validation_errors": len(validation_results)},
            )
            if plan_error_event:
                yield plan_error_event
        else:
            plan_no_action_event = _format_workflow_stage_event(
                round_num,
                "plan",
                "success",
                policy=policy,
                reason="no_actionable_calls",
                details={
                    "actionable_calls": 0,
                    "validation_errors": 0,
                },
            )
            if plan_no_action_event:
                yield plan_no_action_event

        if not actionable_calls and not submit_result_calls:
            execute_skip_event = _format_workflow_stage_event(
                round_num,
                "execute",
                "skip",
                policy=policy,
                reason="no_actionable_calls",
                details={"validation_errors": len(validation_results)},
            )
            if execute_skip_event:
                yield execute_skip_event

            verify_start_event = _format_workflow_stage_event(
                round_num,
                "verify",
                "start",
                policy=policy,
                reason="no_actionable_calls",
            )
            if verify_start_event:
                yield verify_start_event

            if validation_results:
                for buffered_chunk in _drain_buffered_round_events():
                    yield buffered_chunk
                runtime.consecutive_validation_failures += 1
                runtime.consecutive_no_tool_rounds = 0
                logger.warning(
                    f"[AgenticLoop] Round {round_num}: 工具参数/协议校验失败 {len(validation_results)} 条 "
                    f"(连续 {runtime.consecutive_validation_failures} 轮)"
                )

                validation_summaries = _summarize_results_for_frontend(
                    validation_results,
                    policy.tool_result_preview_chars,
                    rollout=contract_rollout,
                )
                tool_results_payload: Dict[str, Any] = {"results": validation_summaries}
                if contract_rollout.emit_observability_metadata:
                    tool_results_payload["metadata"] = {
                        "contract_rollout": _build_contract_observability_metadata(
                            validation_results,
                            rollout=contract_rollout,
                        )
                    }
                yield _build_loop_event("tool_results", tool_results_payload)

                if runtime.consecutive_validation_failures >= policy.max_consecutive_validation_failures:
                    runtime.stop_reason = "validation_failures"
                    logger.warning("[AgenticLoop] 连续工具参数/协议错误达到阈值")
                    verify_error_event = _format_workflow_stage_event(
                        round_num,
                        "verify",
                        "error",
                        policy=policy,
                        reason="validation_failures",
                        decision="stop",
                        details={
                            "consecutive_validation_failures": runtime.consecutive_validation_failures,
                            "threshold": policy.max_consecutive_validation_failures,
                        },
                    )
                    if verify_error_event:
                        yield verify_error_event
                    yield _build_loop_event("round_end", {"round": round_num, "has_more": False})
                    break

                if round_num < policy.max_rounds:
                    assistant_content = complete_text if complete_text else "(工具调用参数错误)"
                    repair_start_event = _format_workflow_stage_event(
                        round_num,
                        "repair",
                        "start",
                        policy=policy,
                        reason="validation_errors",
                        details={"validation_errors": len(validation_results)},
                    )
                    if repair_start_event:
                        yield repair_start_event
                    messages.append({"role": "assistant", "content": assistant_content})
                    messages.append({"role": "user", "content": format_tool_results_for_llm(validation_results)})
                    repair_success_event = _format_workflow_stage_event(
                        round_num,
                        "repair",
                        "success",
                        policy=policy,
                        reason="validation_feedback_injected",
                        details={"validation_errors": len(validation_results)},
                    )
                    if repair_success_event:
                        yield repair_success_event
                    verify_success_event = _format_workflow_stage_event(
                        round_num,
                        "verify",
                        "success",
                        policy=policy,
                        decision="continue",
                        reason="validation_retry",
                        details={"consecutive_validation_failures": runtime.consecutive_validation_failures},
                    )
                    if verify_success_event:
                        yield verify_success_event
                    yield _build_loop_event("round_end", {"round": round_num, "has_more": True})
                else:
                    runtime.stop_reason = "validation_failures"
                    verify_error_event = _format_workflow_stage_event(
                        round_num,
                        "verify",
                        "error",
                        policy=policy,
                        reason="validation_failures_max_rounds",
                        decision="stop",
                    )
                    if verify_error_event:
                        yield verify_error_event
                    yield _build_loop_event("round_end", {"round": round_num, "has_more": False})
                    break
                continue

            runtime.consecutive_validation_failures = 0
            runtime.consecutive_no_tool_rounds += 1

            if _is_completion_submitted(runtime):
                yield _build_round_model_output_event(fallback_text="（状态已提交，等待结束）")
                for buffered_chunk in _drain_buffered_round_events():
                    yield buffered_chunk
                runtime.stop_reason = "submitted_completion"
                verify_success_event = _format_workflow_stage_event(
                    round_num,
                    "verify",
                    "success",
                    policy=policy,
                    reason="submitted_completion",
                    decision="stop",
                    details={"submit_result_round": runtime.submit_result_round},
                )
                if verify_success_event:
                    yield verify_success_event
                logger.info("[AgenticLoop] Round %s: completion gate satisfied, stop loop", round_num)
                yield _build_loop_event("round_end", {"round": round_num, "has_more": False})
                break

            yield _build_round_model_output_event(fallback_text="（本轮模型未返回正文）")
            for buffered_chunk in _drain_buffered_round_events():
                yield buffered_chunk

            if round_num >= policy.max_rounds:
                runtime.stop_reason = "completion_not_submitted"
                verify_error_event = _format_workflow_stage_event(
                    round_num,
                    "verify",
                    "error",
                    policy=policy,
                    reason="completion_not_submitted",
                    decision="stop",
                    details={
                        "task_completed": bool(runtime.agent_state.get("task_completed") is True),
                        "submit_result_called": bool(runtime.submit_result_called),
                    },
                )
                if verify_error_event:
                    yield verify_error_event
                yield _build_loop_event("round_end", {"round": round_num, "has_more": False})
                break

            can_continue_no_tool = (
                runtime.consecutive_no_tool_rounds < policy.max_consecutive_no_tool_rounds
                and round_num < policy.max_rounds
            )

            if can_continue_no_tool:
                verify_success_event = _format_workflow_stage_event(
                    round_num,
                    "verify",
                    "success",
                    policy=policy,
                    decision="continue",
                    reason="await_submit_result_tool",
                    details={
                        "consecutive_no_tool_rounds": runtime.consecutive_no_tool_rounds,
                        "threshold": policy.max_consecutive_no_tool_rounds,
                        "task_completed": bool(runtime.agent_state.get("task_completed") is True),
                        "submit_result_called": bool(runtime.submit_result_called),
                        "tool_choice": "required",
                    },
                )
                if verify_success_event:
                    yield verify_success_event
                yield _build_loop_event("round_end", {"round": round_num, "has_more": True})
                continue

            runtime.stop_reason = "completion_not_submitted"
            verify_error_event = _format_workflow_stage_event(
                round_num,
                "verify",
                "error",
                policy=policy,
                reason="completion_not_submitted",
                decision="stop",
                details={
                    "consecutive_no_tool_rounds": runtime.consecutive_no_tool_rounds,
                    "threshold": policy.max_consecutive_no_tool_rounds,
                    "task_completed": bool(runtime.agent_state.get("task_completed") is True),
                    "submit_result_called": bool(runtime.submit_result_called),
                    "tool_choice": "required",
                },
            )
            if verify_error_event:
                yield verify_error_event
            yield _build_loop_event("round_end", {"round": round_num, "has_more": False})
            break

        runtime.consecutive_validation_failures = 0
        runtime.consecutive_no_tool_rounds = 0
        planned_tool_call_count = len(actionable_calls) + len(submit_result_calls)
        logger.info(
            "[AgenticLoop] Round %s: 检测到 %s 个工具调用 (external=%s, submit_state=%s)",
            round_num,
            planned_tool_call_count,
            len(actionable_calls),
            len(submit_result_calls),
        )
        execute_start_event = _format_workflow_stage_event(
            round_num,
            "execute",
            "start",
            policy=policy,
            details={
                "actionable_calls": planned_tool_call_count,
                "external_calls": len(actionable_calls),
                "submit_result_calls": len(submit_result_calls),
            },
        )
        if execute_start_event:
            yield execute_start_event

        call_descriptions = _build_tool_call_descriptions(actionable_calls + submit_result_calls)
        yield _build_loop_event("tool_calls", {"calls": call_descriptions})

        primary_results: List[Dict[str, Any]] = []
        followup_results: List[Dict[str, Any]] = []
        if actionable_calls:
            primary_results = await execute_tool_calls(
                actionable_calls,
                session_id,
                max_parallel_calls=policy.max_parallel_tool_calls,
                retry_failed=policy.retry_failed_tool_calls,
                max_retries=policy.max_tool_retries,
                retry_backoff_seconds=policy.retry_backoff_seconds,
            )
            followup_results = await _maybe_execute_gc_reader_followup(primary_results, session_id, round_num=round_num)
        executed_results = submit_result_rows + primary_results + followup_results

        try:
            archived_records = archive_tool_results_for_session(session_id, executed_results)
            if archived_records:
                logger.debug(
                    "[AgenticLoop] archived %s episodic record(s) in round %s",
                    len(archived_records),
                    round_num,
                )
                try:
                    updated_edges = update_semantic_graph_from_records(session_id, archived_records)
                    logger.debug(
                        "[AgenticLoop] semantic graph updated with %s edge mutation(s) in round %s",
                        updated_edges,
                        round_num,
                    )
                except Exception as exc:
                    logger.warning("[AgenticLoop] semantic graph update skipped in round %s: %s", round_num, exc)
        except Exception as exc:
            logger.warning("[AgenticLoop] episodic archive skipped in round %s: %s", round_num, exc)

        success_count = sum(1 for r in executed_results if r.get("status") == "success")
        error_count = sum(1 for r in executed_results if r.get("status") == "error")
        runtime.total_tool_calls += planned_tool_call_count
        runtime.total_tool_success += success_count
        runtime.total_tool_errors += error_count

        watchdog_signals: List[Dict[str, Any]] = []
        if loop_watchdog is not None:
            for row in executed_results:
                if not isinstance(row, dict):
                    continue
                if str(row.get("service_name") or "").strip().lower() == "agent_state":
                    continue
                tool_name = str(row.get("tool_name") or row.get("service_name") or "unknown_tool")
                success = str(row.get("status") or "").strip().lower() == "success"
                signal = loop_watchdog.observe_tool_call(
                    task_id=session_id,
                    tool_name=tool_name,
                    success=success,
                    call_cost=_extract_tool_call_cost(row),
                )
                if isinstance(signal, dict):
                    watchdog_signals.append(signal)
            if watchdog_sample_per_round:
                try:
                    snapshot = loop_watchdog.sample()
                    resource_action = loop_watchdog.evaluate(snapshot)
                    if resource_action is not None:
                        watchdog_signals.append(resource_action.to_dict())
                except Exception as exc:
                    logger.warning("[AgenticLoop] watchdog sample/evaluate skipped in round %s: %s", round_num, exc)

        for signal in watchdog_signals:
            if isinstance(signal, dict) and "reason" in signal:
                try:
                    _get_budget_guard_controller().record_action_payload(signal)
                except Exception as exc:
                    logger.warning("[AgenticLoop] budget guard state update skipped in round %s: %s", round_num, exc)
            yield _build_loop_event(
                "guardrail",
                _build_watchdog_guardrail_payload(
                    signal=signal,
                    source="loop_cost_guard" if "reason" in signal else "resource_watchdog",
                    round_num=round_num,
                ),
            )

        blocking_watchdog_signal = next(
            (signal for signal in watchdog_signals if _should_stop_on_watchdog_signal(signal)),
            None,
        )
        if isinstance(blocking_watchdog_signal, dict):
            runtime.stop_reason = _resolve_watchdog_stop_reason(blocking_watchdog_signal)
            logger.warning(
                "[AgenticLoop] watchdog guard hit in round %s: reason=%s action=%s level=%s",
                round_num,
                runtime.stop_reason,
                blocking_watchdog_signal.get("action", ""),
                blocking_watchdog_signal.get("level", ""),
            )
            watchdog_details = dict(blocking_watchdog_signal)
            if "reason" in watchdog_details and "watchdog_reason" not in watchdog_details:
                watchdog_details["watchdog_reason"] = watchdog_details.pop("reason")
            verify_error_event = _format_workflow_stage_event(
                round_num,
                "verify",
                "error",
                policy=policy,
                reason=runtime.stop_reason,
                decision="stop",
                details=watchdog_details,
            )
            if verify_error_event:
                yield verify_error_event
            yield _build_loop_event("round_end", {"round": round_num, "has_more": False})
            break

        results = validation_results + executed_results
        gc_guard_observed_results = primary_results + followup_results
        gc_guard_signal = (
            gc_budget_guard.observe_round(gc_guard_observed_results) if gc_budget_guard is not None else None
        )
        gc_guard_snapshot = gc_budget_guard.snapshot() if gc_budget_guard is not None else {}
        runtime.gc_guard_repeat_count = _clamp_int(gc_guard_snapshot.get("repeat_count", 0), 0, 0, 9999)
        runtime.gc_guard_error_total = _clamp_int(gc_guard_snapshot.get("gc_error_total", 0), 0, 0, 999999)
        runtime.gc_guard_success_total = _clamp_int(gc_guard_snapshot.get("gc_success_total", 0), 0, 0, 999999)
        runtime.gc_guard_hit_total = _clamp_int(gc_guard_snapshot.get("gc_guard_hits", 0), 0, 0, 999999)

        all_failed = bool(executed_results) and success_count == 0
        if all_failed:
            runtime.consecutive_tool_failures += 1
            logger.warning(
                f"[AgenticLoop] Round {round_num}: 本轮所有已调度工具调用失败 "
                f"(连续 {runtime.consecutive_tool_failures} 轮)"
            )
        else:
            runtime.consecutive_tool_failures = 0
        execute_final_status = "error" if all_failed else "success"
        execute_finish_event = _format_workflow_stage_event(
            round_num,
            "execute",
            execute_final_status,
            policy=policy,
            details={
                "actionable_calls": planned_tool_call_count,
                "external_calls": len(actionable_calls),
                "submit_result_calls": len(submit_result_calls),
                "auto_followup_calls": len(followup_results),
                "success_count": success_count,
                "error_count": error_count,
                "gc_guard_repeat_count": runtime.gc_guard_repeat_count,
                "gc_guard_error_total": runtime.gc_guard_error_total,
                "gc_guard_success_total": runtime.gc_guard_success_total,
                "gc_guard_hit_total": runtime.gc_guard_hit_total,
            },
        )
        if execute_finish_event:
            yield execute_finish_event
        if gc_guard_signal and gc_guard_signal.guard_hit:
            yield _build_loop_event(
                "guardrail",
                {
                    "guard_type": "gc_budget_guard",
                    "round": round_num,
                    **gc_guard_signal.to_payload(),
                },
            )

        result_summaries = _summarize_results_for_frontend(
            results,
            policy.tool_result_preview_chars,
            rollout=contract_rollout,
        )
        tool_results_payload = {"results": result_summaries}
        rollout_metadata = _build_contract_observability_metadata(results, rollout=contract_rollout)
        if contract_rollout.emit_observability_metadata:
            tool_results_payload["metadata"] = {"contract_rollout": rollout_metadata}
        yield _build_loop_event("tool_results", tool_results_payload)

        if (
            contract_rollout.emit_observability_metadata
            and isinstance(rollout_metadata.get("stats"), dict)
            and int(rollout_metadata["stats"].get("legacy_blocked_count", 0)) > 0
        ):
            yield _build_loop_event(
                "guardrail",
                {
                    "round": round_num,
                    "type": "legacy_contract_decommission_gate",
                    "snapshot": rollout_metadata.get("snapshot", {}),
                    "stats": rollout_metadata.get("stats", {}),
                },
            )

        assistant_content = complete_text if complete_text else "(工具调用中)"
        messages.append({"role": "assistant", "content": assistant_content})
        messages.append({"role": "user", "content": format_tool_results_for_llm(results)})
        verify_start_event = _format_workflow_stage_event(
            round_num,
            "verify",
            "start",
            policy=policy,
            reason="post_execute",
            details={
                "consecutive_tool_failures": runtime.consecutive_tool_failures,
                "gc_guard_repeat_count": runtime.gc_guard_repeat_count,
                "gc_guard_hit_total": runtime.gc_guard_hit_total,
            },
        )
        if verify_start_event:
            yield verify_start_event

        if _is_completion_submitted(runtime):
            runtime.stop_reason = "submitted_completion"
            verify_success_event = _format_workflow_stage_event(
                round_num,
                "verify",
                "success",
                policy=policy,
                reason="submitted_completion",
                decision="stop",
                details={
                    "task_completed": True,
                    "submit_result_round": runtime.submit_result_round,
                },
            )
            if verify_success_event:
                yield verify_success_event
            yield _build_loop_event("round_end", {"round": round_num, "has_more": False})
            break

        arbiter_escalation = next(
            (
                r.get("router_arbiter")
                for r in executed_results
                if isinstance(r.get("router_arbiter"), dict) and bool(r["router_arbiter"].get("escalated"))
            ),
            None,
        )
        if isinstance(arbiter_escalation, dict):
            runtime.stop_reason = "router_arbiter_escalation"
            logger.warning(
                "[AgenticLoop] Router arbiter escalation triggered in round %s, conflict_ticket=%s, delegate_turns=%s",
                round_num,
                arbiter_escalation.get("conflict_ticket", ""),
                arbiter_escalation.get("delegate_turns", 0),
            )
            verify_error_event = _format_workflow_stage_event(
                round_num,
                "verify",
                "error",
                policy=policy,
                reason="router_arbiter_escalation",
                decision="stop",
                details=arbiter_escalation,
            )
            if verify_error_event:
                yield verify_error_event
            yield _build_loop_event("round_end", {"round": round_num, "has_more": False})
            break

        if gc_guard_signal and gc_guard_signal.guard_hit:
            runtime.stop_reason = gc_guard_signal.stop_reason or "gc_budget_guard_hit"
            logger.warning(
                "[AgenticLoop] GC budget guard hit in round %s: fingerprint=%s repeat=%s threshold=%s artifact_ref=%s",
                round_num,
                gc_guard_signal.fingerprint,
                gc_guard_signal.repeat_count,
                gc_guard_signal.threshold,
                gc_guard_signal.artifact_ref or "<none>",
            )
            verify_error_event = _format_workflow_stage_event(
                round_num,
                "verify",
                "error",
                policy=policy,
                reason=runtime.stop_reason,
                decision="stop",
                details=gc_guard_signal.to_payload(),
            )
            if verify_error_event:
                yield verify_error_event
            yield _build_loop_event("round_end", {"round": round_num, "has_more": False})
            break

        if runtime.consecutive_tool_failures >= policy.max_consecutive_tool_failures:
            runtime.stop_reason = "tool_failures"
            logger.warning(
                f"[AgenticLoop] 连续 {runtime.consecutive_tool_failures} 轮工具全部失败，触发循环停止策略"
            )
            verify_error_event = _format_workflow_stage_event(
                round_num,
                "verify",
                "error",
                policy=policy,
                reason="tool_failures",
                decision="stop",
                details={
                    "consecutive_tool_failures": runtime.consecutive_tool_failures,
                    "threshold": policy.max_consecutive_tool_failures,
                },
            )
            if verify_error_event:
                yield verify_error_event
            yield _build_loop_event("round_end", {"round": round_num, "has_more": False})
            break

        verify_success_event = _format_workflow_stage_event(
            round_num,
            "verify",
            "success",
            policy=policy,
            reason="post_execute",
            decision="continue",
            details={"consecutive_tool_failures": runtime.consecutive_tool_failures},
        )
        if verify_success_event:
            yield verify_success_event
        yield _build_loop_event("round_end", {"round": round_num, "has_more": True})
        logger.info(f"[AgenticLoop] Round {round_num}: 工具结果已注入，继续下一轮")
    else:
        runtime.stop_reason = "submitted_completion" if _is_completion_submitted(runtime) else "completion_not_submitted"
    yield _build_loop_event(
        "execution_receipt",
        _build_execution_receipt_payload(
            session_id=session_id,
            runtime=runtime,
            policy=policy,
        ),
    )


def _decode_sse_payload(chunk: str) -> Optional[Dict[str, Any]]:
    if not isinstance(chunk, str) or not chunk.startswith("data: "):
        return None
    payload_text = chunk[6:].strip()
    if not payload_text or payload_text == "[DONE]":
        return None
    try:
        payload = json.loads(payload_text)
    except Exception:
        return None
    if isinstance(payload, dict):
        return payload
    return None


async def run_agentic_loop_events(
    messages: List[Dict[str, Any]],
    session_id: str,
    max_rounds: int = 500,
    model_override: Optional[Dict[str, str]] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """Structured event stream for parent-agent orchestration (non-SSE)."""
    async for event in run_agentic_loop(
        messages,
        session_id,
        max_rounds=max_rounds,
        model_override=model_override,
    ):
        if isinstance(event, dict):
            yield event
            continue
        payload = _decode_sse_payload(str(event))
        if isinstance(payload, dict):
            yield payload


async def run_agentic_loop_receipt(
    messages: List[Dict[str, Any]],
    session_id: str,
    max_rounds: int = 500,
    model_override: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Run the loop and return terminal execution receipt."""
    latest_receipt: Dict[str, Any] = {}
    async for event in run_agentic_loop_events(
        messages,
        session_id,
        max_rounds=max_rounds,
        model_override=model_override,
    ):
        if str(event.get("type") or "") == "execution_receipt":
            latest_receipt = dict(event)
    return latest_receipt
