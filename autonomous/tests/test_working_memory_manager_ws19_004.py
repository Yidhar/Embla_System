from __future__ import annotations

from agents.memory.working_memory import (
    MemoryWindowThresholds,
    WorkingMemoryWindowManager,
)


def _msg(role: str, content: str) -> dict[str, str]:
    return {"role": role, "content": content}


def test_working_memory_soft_limit_rebalances_and_invokes_callback() -> None:
    manager = WorkingMemoryWindowManager(
        thresholds=MemoryWindowThresholds(
            soft_limit_tokens=80,
            hard_limit_tokens=1000,
            keep_recent_messages_soft=4,
            keep_recent_messages_hard=3,
        )
    )
    messages = [
        _msg("system", "DNA policies"),
        _msg("user", "A" * 120),
        _msg("assistant", "B" * 120),
        _msg("user", "C" * 120),
        _msg("assistant", "D" * 120),
        _msg("user", "E" * 120),
    ]
    callback_payloads: list[dict[str, int]] = []
    result = manager.rebalance(
        messages,
        on_soft_limit=lambda payload: callback_payloads.append(payload),  # type: ignore[arg-type]
    )

    assert result.soft_triggered is True
    assert result.hard_triggered is False
    assert result.tokens_after < result.tokens_before
    assert result.messages_after < result.messages_before
    assert callback_payloads and callback_payloads[0]["stage"] == "soft_limit"
    assert messages[0]["role"] == "system"


def test_working_memory_rebalance_preserves_critical_context() -> None:
    manager = WorkingMemoryWindowManager(
        thresholds=MemoryWindowThresholds(
            soft_limit_tokens=70,
            hard_limit_tokens=300,
            keep_recent_messages_soft=3,
            keep_recent_messages_hard=2,
        )
    )
    messages = [
        _msg("system", "policy"),
        _msg("assistant", "normal output 1"),
        _msg("assistant", "trace_id=trace-abc-001 root cause segment"),
        _msg("assistant", "normal output 2"),
        _msg("assistant", "normal output 3"),
        _msg("user", "latest instruction"),
    ]
    manager.rebalance(messages)

    contents = [m["content"] for m in messages]
    assert any("trace_id=trace-abc-001" in c for c in contents)
    assert any("latest instruction" in c for c in contents)


def test_working_memory_hard_limit_truncates_and_drops_noncritical_messages() -> None:
    manager = WorkingMemoryWindowManager(
        thresholds=MemoryWindowThresholds(
            soft_limit_tokens=80,
            hard_limit_tokens=120,
            keep_recent_messages_soft=6,
            keep_recent_messages_hard=4,
            hard_truncate_chars=80,
        )
    )
    messages = [
        _msg("system", "policy"),
        _msg("assistant", "x" * 1200),
        _msg("user", "y" * 900),
        _msg("assistant", "z" * 800),
        _msg("user", "follow-up"),
    ]
    stages: list[str] = []
    result = manager.rebalance(
        messages,
        on_soft_limit=lambda payload: stages.append(str(payload.get("stage"))),
        on_hard_limit=lambda payload: stages.append(str(payload.get("stage"))),
    )

    assert result.soft_triggered is True
    assert result.hard_triggered is True
    assert result.tokens_after <= manager.thresholds.hard_limit_tokens
    assert result.truncated_messages > 0
    assert "soft_limit" in stages and "hard_limit" in stages
