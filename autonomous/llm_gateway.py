"""WS19-003 LLM gateway (tiered routing + three-block prompt cache)."""

from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


def _stable_hash_text(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _estimate_tokens(text: str) -> int:
    raw = str(text or "")
    if not raw:
        return 0
    # Lightweight heuristic: ~4 chars per token for mixed zh/en content.
    return max(1, len(raw) // 4)


@dataclass(frozen=True)
class GatewayRouteRequest:
    task_type: str
    severity: str = "medium"
    budget_remaining: Optional[float] = None


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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "route": self.route.to_dict(),
            "prompt_envelope": self.prompt_envelope.to_dict(),
            "cache_outcome": self.cache_outcome.to_dict(),
            "metrics": self.metrics.to_dict(),
        }


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
        envelope = self.build_prompt_envelope(prompt_input)

        if envelope.block3_soft_limit_exceeded and route.model_tier == "primary":
            route = GatewayRouteDecision(
                model_tier="secondary",
                model_id=self.model_map["secondary"],
                reason=f"{route.reason}; block3>{self.block3_soft_limit_tokens} requires GC before primary",
            )

        cache_outcome = self.apply_prompt_cache(envelope)
        metrics = self.estimate_metrics(route=route, envelope=envelope, cache_outcome=cache_outcome)
        return GatewayPlan(route=route, prompt_envelope=envelope, cache_outcome=cache_outcome, metrics=metrics)

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
