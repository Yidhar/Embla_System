"""WS19-003 LLM gateway (tiered routing + three-block prompt cache)."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


def _stable_hash_text(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _estimate_tokens(text: str) -> int:
    raw = str(text or "")
    if not raw:
        return 0
    # Lightweight heuristic: ~4 chars per token for mixed zh/en content.
    return max(1, len(raw) // 4)


_WRITE_TOOL_EXPOSURE_MARKERS = (
    "tool_name\":\"write_file",
    "tool_name\": \"write_file",
    "\"write_file\"",
    "tool_name\":\"workspace_txn_apply",
    "tool_name\": \"workspace_txn_apply",
    "\"workspace_txn_apply\"",
    "tool_name\":\"run_cmd",
    "tool_name\": \"run_cmd",
    "\"run_cmd\"",
    "tool_name\":\"apply_patch",
    "tool_name\": \"apply_patch",
    "\"apply_patch\"",
)


@dataclass(frozen=True)
class GatewayRouteRequest:
    task_type: str
    severity: str = "medium"
    budget_remaining: Optional[float] = None
    path: str = "path-c"
    prompt_profile: str = ""
    injection_mode: str = ""
    delegation_intent: str = ""
    workflow_id: str = ""
    trace_id: str = ""
    contract_upgrade_latency_ms: Optional[float] = None
    recovery_context_survived: Optional[bool] = None


@dataclass(frozen=True)
class GatewayRouteDecision:
    model_tier: str
    model_id: str
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PromptEnvelopeInput:
    static_header: str
    long_term_summary: str
    dynamic_messages: List[Dict[str, Any]] = field(default_factory=list)
    prompt_slices: List["PromptSlice"] = field(default_factory=list)


@dataclass(frozen=True)
class PromptSlice:
    slice_uid: str
    layer: str
    text: str
    owner: str = "system"
    cache_segment: str = "tail_dynamic"  # prefix_static|prefix_session|tail_dynamic
    priority: int = 100

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PromptComposeDecision:
    path: str
    selected_slices: List[str]
    dropped_slices: List[str]
    reasons: List[str]
    prefix_hash: str
    tail_hash: str
    token_budget_before: int
    token_budget_after: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PromptEnvelope:
    block1_text: str
    block2_text: str
    block3_messages: List[Dict[str, str]]
    block1_cache: str = "ephemeral"
    block2_cache: str = "ephemeral"
    block3_cache: str = "none"
    block3_soft_limit_tokens: int = 10000
    block1_tokens: int = 0
    block2_tokens: int = 0
    block3_tokens: int = 0
    block3_soft_limit_exceeded: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PromptCacheOutcome:
    block1_hit: bool
    block2_hit: bool
    block3_hit: bool
    cache_key_block1: str
    cache_key_block2: str
    stats: Dict[str, int]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GatewayPlanMetrics:
    effective_prompt_tokens: int
    estimated_cost_units: float
    estimated_latency_ms: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GatewayPlan:
    route: GatewayRouteDecision
    prompt_envelope: PromptEnvelope
    cache_outcome: PromptCacheOutcome
    metrics: GatewayPlanMetrics
    compose_decision: Optional[PromptComposeDecision] = None

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "route": self.route.to_dict(),
            "prompt_envelope": self.prompt_envelope.to_dict(),
            "cache_outcome": self.cache_outcome.to_dict(),
            "metrics": self.metrics.to_dict(),
        }
        if self.compose_decision is not None:
            payload["compose_decision"] = self.compose_decision.to_dict()
        return payload


class LLMGateway:
    """Tiered model routing and prompt cache plan for LLM requests."""

    DEFAULT_MODEL_MAP = {
        "primary": "openai/gpt-4.1",
        "secondary": "openai/gpt-4.1-mini",
        "local": "local/qwen2.5-7b-instruct",
    }
    COST_PER_1K_TOKENS = {"primary": 1.0, "secondary": 0.35, "local": 0.0}
    BASE_LATENCY_MS = {"primary": 1200, "secondary": 700, "local": 450}

    def __init__(
        self,
        *,
        model_map: Optional[Dict[str, str]] = None,
        block3_soft_limit_tokens: int = 10000,
        block1_ttl_seconds: int = 6 * 3600,
        block2_ttl_seconds: int = 3600,
        now_fn: Optional[Any] = None,
        event_log_file: Optional[Path] = Path("logs/autonomous/events.jsonl"),
        event_source: str = "autonomous.llm_gateway",
    ) -> None:
        merged_map = dict(self.DEFAULT_MODEL_MAP)
        if model_map:
            for tier, model_id in model_map.items():
                tier_key = str(tier or "").strip().lower()
                if tier_key in {"primary", "secondary", "local"} and model_id:
                    merged_map[tier_key] = str(model_id)
        self.model_map = merged_map
        self.block3_soft_limit_tokens = max(1, int(block3_soft_limit_tokens))
        self.block1_ttl_seconds = max(60, int(block1_ttl_seconds))
        self.block2_ttl_seconds = max(60, int(block2_ttl_seconds))
        self._now_fn = now_fn or time.time
        self._lock = threading.Lock()
        self._block1_cache: Dict[str, float] = {}
        self._block2_cache: Dict[str, float] = {}
        self._stats = {
            "block1_hits": 0,
            "block1_misses": 0,
            "block2_hits": 0,
            "block2_misses": 0,
        }
        self._event_source = str(event_source or "autonomous.llm_gateway")
        self._event_store = None
        if event_log_file is not None:
            try:
                from autonomous.event_log import EventStore

                self._event_store = EventStore(file_path=Path(event_log_file))
            except Exception:
                self._event_store = None

    def route(self, request: GatewayRouteRequest) -> GatewayRouteDecision:
        task_type = str(request.task_type or "").strip().lower()
        severity = str(request.severity or "").strip().lower()
        budget = request.budget_remaining

        if task_type == "heavy_log_parse":
            tier = "local"
            reason = "heavy_log_parse defaults to local tier"
        elif task_type == "memory_cleanup":
            tier = "secondary"
            reason = "memory_cleanup defaults to secondary tier"
        elif severity in {"critical", "high"}:
            if budget is not None and budget < 2:
                tier = "secondary"
                reason = f"{severity} severity but low budget {budget:.2f} => secondary tier"
            else:
                tier = "primary"
                reason = f"{severity} severity => primary tier"
        elif budget is not None and budget < 1:
            tier = "local"
            reason = f"very low budget {budget:.2f} => local tier"
        elif budget is not None and budget < 4:
            tier = "secondary"
            reason = f"constrained budget {budget:.2f} => secondary tier"
        elif task_type == "qa":
            tier = "secondary"
            reason = "qa default => secondary tier"
        else:
            tier = "primary"
            reason = "default => primary tier"

        return GatewayRouteDecision(model_tier=tier, model_id=self.model_map[tier], reason=reason)

    def build_prompt_envelope(self, data: PromptEnvelopeInput) -> PromptEnvelope:
        block1 = str(data.static_header or "")
        block2 = str(data.long_term_summary or "")

        normalized_messages: List[Dict[str, str]] = []
        block3_tokens = 0
        for message in data.dynamic_messages:
            role = str(message.get("role") or "user")
            content = str(message.get("content") or "")
            normalized_messages.append({"role": role, "content": content})
            block3_tokens += _estimate_tokens(role) + _estimate_tokens(content)

        return PromptEnvelope(
            block1_text=block1,
            block2_text=block2,
            block3_messages=normalized_messages,
            block3_soft_limit_tokens=self.block3_soft_limit_tokens,
            block1_tokens=_estimate_tokens(block1),
            block2_tokens=_estimate_tokens(block2),
            block3_tokens=block3_tokens,
            block3_soft_limit_exceeded=block3_tokens > self.block3_soft_limit_tokens,
        )

    def resolve(self, *, request: GatewayRouteRequest, prompt_input: PromptEnvelopeInput) -> Dict[str, Any]:
        path = str(request.path or "path-c").strip().lower()
        raw_slices = self._collect_prompt_slices(prompt_input)
        selected: List[PromptSlice] = []
        dropped: List[PromptSlice] = []
        reasons: List[str] = []

        for slice_item in raw_slices:
            if self._should_drop_slice_for_path(path=path, slice_item=slice_item):
                dropped.append(slice_item)
                reasons.append(f"{slice_item.slice_uid}: dropped for {path} policy")
                continue
            selected.append(slice_item)

        # Keep deterministic order for repeatable composition decisions.
        selected = sorted(selected, key=lambda item: (int(item.priority), str(item.slice_uid)))
        dropped = sorted(dropped, key=lambda item: (int(item.priority), str(item.slice_uid)))
        return {
            "path": path,
            "selected": selected,
            "dropped": dropped,
            "reasons": reasons,
        }

    def serialize_for_cache(self, *, selected_slices: List[PromptSlice]) -> Dict[str, Any]:
        prefix_segments: List[str] = []
        tail_segments: List[str] = []
        prefix_slice_ids: List[str] = []
        tail_slice_ids: List[str] = []
        for item in selected_slices:
            text = str(item.text or "")
            segment = str(item.cache_segment or "tail_dynamic").strip().lower()
            if segment in {"prefix_static", "prefix_session"}:
                if text:
                    prefix_segments.append(text)
                prefix_slice_ids.append(item.slice_uid)
            else:
                if text:
                    tail_segments.append(text)
                tail_slice_ids.append(item.slice_uid)

        prefix_text = "\n".join(segment for segment in prefix_segments if segment)
        tail_text = "\n".join(segment for segment in tail_segments if segment)
        return {
            "prefix_text": prefix_text,
            "tail_text": tail_text,
            "prefix_hash": _stable_hash_text(prefix_text) if prefix_text else "",
            "tail_hash": _stable_hash_text(tail_text) if tail_text else "",
            "prefix_slice_ids": prefix_slice_ids,
            "tail_slice_ids": tail_slice_ids,
        }

    def compose(self, *, request: GatewayRouteRequest, prompt_input: PromptEnvelopeInput) -> PromptComposeDecision:
        resolved = self.resolve(request=request, prompt_input=prompt_input)
        selected: List[PromptSlice] = list(resolved["selected"])
        dropped: List[PromptSlice] = list(resolved["dropped"])
        serialized = self.serialize_for_cache(selected_slices=selected)
        tokens_before = sum(_estimate_tokens(str(item.text or "")) for item in self._collect_prompt_slices(prompt_input))
        tokens_after = sum(_estimate_tokens(str(item.text or "")) for item in selected)
        return PromptComposeDecision(
            path=str(resolved["path"]),
            selected_slices=[item.slice_uid for item in selected],
            dropped_slices=[item.slice_uid for item in dropped],
            reasons=list(resolved["reasons"]),
            prefix_hash=str(serialized["prefix_hash"]),
            tail_hash=str(serialized["tail_hash"]),
            token_budget_before=tokens_before,
            token_budget_after=tokens_after,
        )

    def apply_prompt_cache(self, envelope: PromptEnvelope) -> PromptCacheOutcome:
        now = float(self._now_fn())
        block1_key = _stable_hash_text(envelope.block1_text) if envelope.block1_text else ""
        block2_key = _stable_hash_text(envelope.block2_text) if envelope.block2_text else ""
        block1_hit = False
        block2_hit = False

        with self._lock:
            if block1_key:
                block1_hit = self._is_alive(self._block1_cache.get(block1_key), now, self.block1_ttl_seconds)
                if block1_hit:
                    self._stats["block1_hits"] += 1
                else:
                    self._stats["block1_misses"] += 1
                    self._block1_cache[block1_key] = now

            if block2_key:
                block2_hit = self._is_alive(self._block2_cache.get(block2_key), now, self.block2_ttl_seconds)
                if block2_hit:
                    self._stats["block2_hits"] += 1
                else:
                    self._stats["block2_misses"] += 1
                    self._block2_cache[block2_key] = now

            stats_copy = dict(self._stats)

        return PromptCacheOutcome(
            block1_hit=block1_hit,
            block2_hit=block2_hit,
            block3_hit=False,
            cache_key_block1=block1_key,
            cache_key_block2=block2_key,
            stats=stats_copy,
        )

    def build_plan(self, *, request: GatewayRouteRequest, prompt_input: PromptEnvelopeInput) -> GatewayPlan:
        route = self.route(request)
        compose_decision = self.compose(request=request, prompt_input=prompt_input)
        envelope = self.build_prompt_envelope(prompt_input)

        # When prompt slices are provided by caller, honor resolve/serialize result directly.
        request_path = str(request.path or "").strip().lower()
        if prompt_input.prompt_slices or request_path in {"path-a", "path_a", "outer_readonly"}:
            resolved = self.resolve(request=request, prompt_input=prompt_input)
            selected = list(resolved["selected"])
            serialized = self.serialize_for_cache(selected_slices=selected)
            selected_ids = set(compose_decision.selected_slices)
            filtered_messages: List[Dict[str, str]] = []
            for index, message in enumerate(prompt_input.dynamic_messages):
                slice_uid = f"legacy_dynamic_message_{index}"
                if slice_uid in selected_ids:
                    filtered_messages.append(
                        {
                            "role": str(message.get("role") or "user"),
                            "content": str(message.get("content") or ""),
                        }
                    )
            filtered_block3_tokens = sum(
                _estimate_tokens(str(item.get("role") or "")) + _estimate_tokens(str(item.get("content") or ""))
                for item in filtered_messages
            )
            envelope = PromptEnvelope(
                block1_text=str(serialized["prefix_text"]),
                block2_text=str(serialized["tail_text"]),
                block3_messages=filtered_messages,
                block3_soft_limit_tokens=self.block3_soft_limit_tokens,
                block1_tokens=_estimate_tokens(str(serialized["prefix_text"])),
                block2_tokens=_estimate_tokens(str(serialized["tail_text"])),
                block3_tokens=filtered_block3_tokens,
                block3_soft_limit_exceeded=filtered_block3_tokens > self.block3_soft_limit_tokens,
            )

        if envelope.block3_soft_limit_exceeded and route.model_tier == "primary":
            route = GatewayRouteDecision(
                model_tier="secondary",
                model_id=self.model_map["secondary"],
                reason=f"{route.reason}; block3>{self.block3_soft_limit_tokens} requires GC before primary",
            )

        cache_outcome = self.apply_prompt_cache(envelope)
        metrics = self.estimate_metrics(route=route, envelope=envelope, cache_outcome=cache_outcome)
        self._emit_prompt_injection_event(
            request=request,
            prompt_input=prompt_input,
            route=route,
            compose_decision=compose_decision,
            cache_outcome=cache_outcome,
        )
        return GatewayPlan(
            route=route,
            prompt_envelope=envelope,
            cache_outcome=cache_outcome,
            metrics=metrics,
            compose_decision=compose_decision,
        )

    def estimate_metrics(
        self,
        *,
        route: GatewayRouteDecision,
        envelope: PromptEnvelope,
        cache_outcome: PromptCacheOutcome,
    ) -> GatewayPlanMetrics:
        tier = route.model_tier
        if tier not in {"primary", "secondary", "local"}:
            tier = "primary"

        effective_tokens = envelope.block3_tokens
        if not cache_outcome.block1_hit:
            effective_tokens += envelope.block1_tokens
        if not cache_outcome.block2_hit:
            effective_tokens += envelope.block2_tokens

        cost_factor = self.COST_PER_1K_TOKENS[tier]
        cost_units = round(cost_factor * (effective_tokens / 1000.0), 6)
        latency_base = self.BASE_LATENCY_MS[tier]
        latency = int(latency_base + min(2000, effective_tokens // 2))
        return GatewayPlanMetrics(
            effective_prompt_tokens=effective_tokens,
            estimated_cost_units=cost_units,
            estimated_latency_ms=latency,
        )

    @staticmethod
    def _is_alive(stored_at: Optional[float], now: float, ttl_seconds: int) -> bool:
        if stored_at is None:
            return False
        return (now - stored_at) <= float(ttl_seconds)

    @staticmethod
    def _collect_prompt_slices(prompt_input: PromptEnvelopeInput) -> List[PromptSlice]:
        if prompt_input.prompt_slices:
            return list(prompt_input.prompt_slices)

        slices: List[PromptSlice] = []
        if prompt_input.static_header:
            slices.append(
                PromptSlice(
                    slice_uid="legacy_block1",
                    layer="L0_DNA",
                    text=str(prompt_input.static_header),
                    owner="system",
                    cache_segment="prefix_static",
                    priority=10,
                )
            )
        if prompt_input.long_term_summary:
            slices.append(
                PromptSlice(
                    slice_uid="legacy_block2",
                    layer="L1_5_EPISODIC_MEMORY",
                    text=str(prompt_input.long_term_summary),
                    owner="memory",
                    cache_segment="prefix_session",
                    priority=20,
                )
            )
        for index, message in enumerate(prompt_input.dynamic_messages):
            role = str(message.get("role") or "user")
            content = str(message.get("content") or "")
            message_text = json.dumps({"role": role, "content": content}, ensure_ascii=False, sort_keys=True)
            slices.append(
                PromptSlice(
                    slice_uid=f"legacy_dynamic_message_{index}",
                    layer="L4_RECOVERY",
                    text=message_text,
                    owner="conversation",
                    cache_segment="tail_dynamic",
                    priority=100 + index,
                )
            )
        return slices

    @staticmethod
    def _should_drop_slice_for_path(*, path: str, slice_item: PromptSlice) -> bool:
        normalized_path = str(path or "").strip().lower()
        if normalized_path not in {"path-a", "path_a", "outer_readonly"}:
            return False

        layer = str(slice_item.layer or "").strip().upper()
        owner = str(slice_item.owner or "").strip().lower()
        if layer.startswith("L3") or layer.startswith("L4"):
            return True
        if owner in {"tool_policy", "execution", "recovery"}:
            return True
        return False

    @staticmethod
    def _normalize_path(path: str) -> str:
        normalized_path = str(path or "").strip().lower()
        if normalized_path in {"path_a", "outer_readonly"}:
            return "path-a"
        if normalized_path in {"path_c", "core_execution"}:
            return "path-c"
        return normalized_path or "path-c"

    @staticmethod
    def _is_write_tool_exposure_slice(slice_item: PromptSlice) -> bool:
        layer = str(slice_item.layer or "").strip().upper()
        owner = str(slice_item.owner or "").strip().lower()
        if layer.startswith("L3"):
            return True
        if owner in {"tool_policy", "execution"}:
            return True

        text = str(slice_item.text or "").strip().lower()
        if not text:
            return False
        return any(marker in text for marker in _WRITE_TOOL_EXPOSURE_MARKERS)

    def _emit_prompt_injection_event(
        self,
        *,
        request: GatewayRouteRequest,
        prompt_input: PromptEnvelopeInput,
        route: GatewayRouteDecision,
        compose_decision: PromptComposeDecision,
        cache_outcome: PromptCacheOutcome,
    ) -> None:
        if self._event_store is None:
            return

        try:
            normalized_path = self._normalize_path(str(request.path or "path-c"))
            selected_ids = set(compose_decision.selected_slices)
            selected_slices = [
                item for item in self._collect_prompt_slices(prompt_input) if str(item.slice_uid) in selected_ids
            ]
            selected_layer_counts: Dict[str, int] = {}
            selected_layers: List[str] = []
            recovery_hit = False
            readonly_write_tool_selected_ids: List[str] = []
            readonly_write_tool_dropped_ids: List[str] = []
            for item in selected_slices:
                layer = str(item.layer or "L_UNKNOWN")
                selected_layer_counts[layer] = selected_layer_counts.get(layer, 0) + 1
                if layer not in selected_layers:
                    selected_layers.append(layer)
                if layer.strip().upper().startswith("L4"):
                    recovery_hit = True
                if self._is_write_tool_exposure_slice(item):
                    readonly_write_tool_selected_ids.append(str(item.slice_uid))

            selected_slice_ids = {str(item.slice_uid) for item in selected_slices}
            all_slices = self._collect_prompt_slices(prompt_input)
            for item in all_slices:
                if not self._is_write_tool_exposure_slice(item):
                    continue
                slice_uid = str(item.slice_uid)
                if slice_uid in selected_slice_ids:
                    continue
                readonly_write_tool_dropped_ids.append(slice_uid)

            delegation_intent = str(request.delegation_intent or "").strip().lower()
            delegation_hit = delegation_intent.startswith("delegate")
            outer_readonly_hit = normalized_path == "path-a"
            core_escalation = normalized_path == "path-c"
            readonly_write_tool_exposed = outer_readonly_hit and bool(readonly_write_tool_selected_ids)
            readonly_write_tool_candidate_count = len(readonly_write_tool_selected_ids) + len(readonly_write_tool_dropped_ids)

            payload: Dict[str, Any] = {
                "task_type": str(request.task_type or ""),
                "severity": str(request.severity or ""),
                "path": normalized_path,
                "trigger": normalized_path,
                "prompt_profile": str(request.prompt_profile or ""),
                "injection_mode": str(request.injection_mode or ""),
                "delegation_intent": delegation_intent,
                "delegation_hit": delegation_hit,
                "outer_readonly_hit": outer_readonly_hit,
                "core_escalation": core_escalation,
                "readonly_write_tool_exposed": readonly_write_tool_exposed,
                "readonly_write_tool_candidate_count": readonly_write_tool_candidate_count,
                "readonly_write_tool_selected_count": len(readonly_write_tool_selected_ids),
                "readonly_write_tool_dropped_count": len(readonly_write_tool_dropped_ids),
                "readonly_write_tool_selected_slices": readonly_write_tool_selected_ids,
                "readonly_write_tool_dropped_slices": readonly_write_tool_dropped_ids,
                "selected_slices": list(compose_decision.selected_slices),
                "dropped_slices": list(compose_decision.dropped_slices),
                "selected_slice_count": len(compose_decision.selected_slices),
                "dropped_slice_count": len(compose_decision.dropped_slices),
                "dropped_conflict_count": len(compose_decision.dropped_slices),
                "selected_layers": selected_layers,
                "selected_layer_counts": selected_layer_counts,
                "recovery_hit": recovery_hit,
                "prefix_hash": str(compose_decision.prefix_hash or ""),
                "tail_hash": str(compose_decision.tail_hash or ""),
                "prefix_cache_hit": bool(cache_outcome.block1_hit and cache_outcome.block2_hit),
                "block1_cache_hit": bool(cache_outcome.block1_hit),
                "block2_cache_hit": bool(cache_outcome.block2_hit),
                "token_budget_before": int(compose_decision.token_budget_before),
                "token_budget_after": int(compose_decision.token_budget_after),
                "model_tier": str(route.model_tier or ""),
                "model_id": str(route.model_id or ""),
            }
            if request.workflow_id:
                payload["workflow_id"] = str(request.workflow_id)
            if request.trace_id:
                payload["trace_id"] = str(request.trace_id)
            if request.contract_upgrade_latency_ms is not None:
                payload["contract_upgrade_latency_ms"] = float(request.contract_upgrade_latency_ms)
            if request.recovery_context_survived is not None:
                payload["recovery_context_survived"] = bool(request.recovery_context_survived)

            self._event_store.emit(
                "PromptInjectionComposed",
                payload,
                source=self._event_source,
            )
        except Exception:
            return
