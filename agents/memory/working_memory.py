"""WS19-004 working memory window manager with dual-threshold callbacks."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Callable, Dict, List, Optional


def _estimate_tokens(text: str) -> int:
    raw = str(text or "")
    if not raw:
        return 0
    return max(1, len(raw) // 4)


def _message_content_text(message: Dict[str, Any]) -> str:
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    try:
        return json.dumps(content, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        return str(content)


@dataclass(frozen=True)
class MemoryWindowThresholds:
    soft_limit_tokens: int = 10000
    hard_limit_tokens: int = 80000
    keep_recent_messages_soft: int = 10
    keep_recent_messages_hard: int = 6
    hard_truncate_chars: int = 1200

    def normalized(self) -> "MemoryWindowThresholds":
        soft = max(100, int(self.soft_limit_tokens))
        hard = max(soft, int(self.hard_limit_tokens))
        keep_soft = max(2, int(self.keep_recent_messages_soft))
        keep_hard = max(2, min(keep_soft, int(self.keep_recent_messages_hard)))
        truncate_chars = max(64, int(self.hard_truncate_chars))
        return MemoryWindowThresholds(
            soft_limit_tokens=soft,
            hard_limit_tokens=hard,
            keep_recent_messages_soft=keep_soft,
            keep_recent_messages_hard=keep_hard,
            hard_truncate_chars=truncate_chars,
        )


@dataclass(frozen=True)
class MemoryWindowRebalanceResult:
    soft_triggered: bool
    hard_triggered: bool
    tokens_before: int
    tokens_after: int
    messages_before: int
    messages_after: int
    trimmed_messages: int
    truncated_messages: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class WorkingMemoryWindowManager:
    """Keep working-memory token peaks bounded without dropping key context."""

    CRITICAL_MARKERS = (
        "trace_id",
        "error_code",
        "raw_result_ref",
        "artifact_ref",
        "conflict_ticket",
        "approval_ticket",
        "request_ticket",
        "replay_fingerprint",
    )

    def __init__(self, *, thresholds: Optional[MemoryWindowThresholds] = None) -> None:
        self.thresholds = (thresholds or MemoryWindowThresholds()).normalized()

    def estimate_tokens(self, messages: List[Dict[str, Any]]) -> int:
        total = 0
        for message in messages:
            role = str(message.get("role") or "")
            total += _estimate_tokens(role)
            total += _estimate_tokens(_message_content_text(message))
        return total

    def rebalance(
        self,
        messages: List[Dict[str, Any]],
        *,
        on_soft_limit: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_hard_limit: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> MemoryWindowRebalanceResult:
        before_tokens = self.estimate_tokens(messages)
        before_count = len(messages)
        soft_triggered = False
        hard_triggered = False
        truncated_messages = 0

        if before_tokens > self.thresholds.soft_limit_tokens:
            soft_triggered = True
            kept = self._select_messages(
                messages,
                keep_recent=self.thresholds.keep_recent_messages_soft,
            )
            messages[:] = kept
            if on_soft_limit:
                on_soft_limit(
                    {
                        "stage": "soft_limit",
                        "tokens_before": before_tokens,
                        "tokens_after": self.estimate_tokens(messages),
                        "messages_before": before_count,
                        "messages_after": len(messages),
                        "soft_limit_tokens": self.thresholds.soft_limit_tokens,
                    }
                )

        after_soft_tokens = self.estimate_tokens(messages)
        if after_soft_tokens > self.thresholds.hard_limit_tokens:
            hard_triggered = True
            kept_hard = self._select_messages(
                messages,
                keep_recent=self.thresholds.keep_recent_messages_hard,
            )
            messages[:] = kept_hard
            truncated_messages += self._truncate_or_drop_to_hard_limit(messages)
            if on_hard_limit:
                on_hard_limit(
                    {
                        "stage": "hard_limit",
                        "tokens_before": after_soft_tokens,
                        "tokens_after": self.estimate_tokens(messages),
                        "messages_before": len(kept_hard),
                        "messages_after": len(messages),
                        "hard_limit_tokens": self.thresholds.hard_limit_tokens,
                        "truncated_messages": truncated_messages,
                    }
                )

        after_tokens = self.estimate_tokens(messages)
        after_count = len(messages)
        return MemoryWindowRebalanceResult(
            soft_triggered=soft_triggered,
            hard_triggered=hard_triggered,
            tokens_before=before_tokens,
            tokens_after=after_tokens,
            messages_before=before_count,
            messages_after=after_count,
            trimmed_messages=max(0, before_count - after_count),
            truncated_messages=truncated_messages,
        )

    def _select_messages(self, messages: List[Dict[str, Any]], *, keep_recent: int) -> List[Dict[str, Any]]:
        system_indices = [idx for idx, msg in enumerate(messages) if str(msg.get("role") or "") == "system"]
        non_system_indices = [idx for idx, msg in enumerate(messages) if str(msg.get("role") or "") != "system"]
        recent_non_system = set(non_system_indices[-keep_recent:])
        critical_indices = {idx for idx in non_system_indices if self._is_critical_message(messages[idx])}
        keep_indices = set(system_indices) | recent_non_system | critical_indices

        selected: List[Dict[str, Any]] = []
        for idx, message in enumerate(messages):
            if idx not in keep_indices:
                continue
            selected.append(dict(message))
        return selected

    def _truncate_or_drop_to_hard_limit(self, messages: List[Dict[str, Any]]) -> int:
        truncated = 0
        truncate_limits = [self.thresholds.hard_truncate_chars, 512, 128]
        for limit in truncate_limits:
            if self.estimate_tokens(messages) <= self.thresholds.hard_limit_tokens:
                break
            for idx, message in enumerate(messages):
                if str(message.get("role") or "") == "system":
                    continue
                if self._is_critical_message(message):
                    continue
                content = _message_content_text(message)
                if len(content) <= limit:
                    continue
                new_content = content[:limit].rstrip() + " ...[truncated]"
                message["content"] = new_content
                truncated += 1
                if self.estimate_tokens(messages) <= self.thresholds.hard_limit_tokens:
                    return truncated

        if self.estimate_tokens(messages) > self.thresholds.hard_limit_tokens:
            idx = 0
            while idx < len(messages) and self.estimate_tokens(messages) > self.thresholds.hard_limit_tokens:
                role = str(messages[idx].get("role") or "")
                if role == "system" or self._is_critical_message(messages[idx]):
                    idx += 1
                    continue
                messages.pop(idx)
                truncated += 1

        return truncated

    def _is_critical_message(self, message: Dict[str, Any]) -> bool:
        text = _message_content_text(message).lower()
        return any(marker in text for marker in self.CRITICAL_MARKERS)


__all__ = [
    "MemoryWindowThresholds",
    "MemoryWindowRebalanceResult",
    "WorkingMemoryWindowManager",
]
