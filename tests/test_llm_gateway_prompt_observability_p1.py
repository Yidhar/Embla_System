from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

from agents.llm_gateway import GatewayRouteRequest, LLMGateway, PromptEnvelopeInput, PromptSlice
from core.event_bus import EventStore


def _make_case_root(prefix: str) -> Path:
    root = Path("scratch") / prefix / uuid.uuid4().hex[:12]
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_case_root(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


def _read_jsonl(path: Path) -> list[dict]:
    # TopicEventBus is primary storage; JSONL mirror may be disabled.
    # Read via EventStore first to stay compatible across storage backends.
    try:
        rows = EventStore(file_path=path).read_recent(limit=2000)
        if rows:
            return rows
    except Exception:
        pass
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def test_llm_gateway_emits_prompt_injection_composed_event() -> None:
    case_root = _make_case_root("test_llm_gateway_prompt_observability_p1")
    try:
        events_file = case_root / "logs" / "autonomous" / "events.jsonl"
        gateway = LLMGateway(
            event_log_file=events_file,
            block1_ttl_seconds=3600,
            block2_ttl_seconds=3600,
            now_fn=lambda: 1_000.0,
        )

        prompt_input = PromptEnvelopeInput(
            static_header="STATIC_BASE",
            long_term_summary="SESSION_SUMMARY",
            dynamic_messages=[{"role": "user", "content": "run checks"}],
            prompt_slices=[
                PromptSlice(
                    slice_uid="slice_l0",
                    layer="L0_DNA",
                    text="DNA",
                    cache_segment="prefix_static",
                    priority=10,
                ),
                PromptSlice(
                    slice_uid="slice_l3_policy",
                    layer="L3_TOOL_POLICY",
                    text='{"tool_name":"write_file","guard":"strict"}',
                    owner="tool_policy",
                    cache_segment="tail_dynamic",
                    priority=15,
                ),
                PromptSlice(
                    slice_uid="slice_l4",
                    layer="L4_RECOVERY",
                    text="recovery context",
                    owner="recovery",
                    cache_segment="tail_dynamic",
                    priority=20,
                ),
            ],
        )

        gateway.build_plan(
            request=GatewayRouteRequest(
                task_type="qa",
                severity="low",
                budget_remaining=10.0,
                path="path-a",
                prompt_profile="outer_readonly",
                injection_mode="minimal",
                delegation_intent="read_only_exploration",
                workflow_id="wf-a",
                trace_id="trace-a",
            ),
            prompt_input=prompt_input,
        )
        gateway.build_plan(
            request=GatewayRouteRequest(
                task_type="code_generation",
                severity="high",
                budget_remaining=10.0,
                path="path-c",
                prompt_profile="core_execution",
                injection_mode="hardened",
                delegation_intent="delegate_core_execution",
                workflow_id="wf-b",
                trace_id="trace-b",
                contract_upgrade_latency_ms=120.0,
                recovery_context_survived=True,
            ),
            prompt_input=prompt_input,
        )

        rows = _read_jsonl(events_file)
        prompt_rows = [row for row in rows if str(row.get("event_type") or "") == "PromptInjectionComposed"]
        assert len(prompt_rows) == 2

        payload_a = prompt_rows[0].get("data")
        payload_b = prompt_rows[1].get("data")
        assert isinstance(payload_a, dict)
        assert isinstance(payload_b, dict)

        assert payload_a["path"] == "path-a"
        assert payload_a["outer_readonly_hit"] is True
        assert payload_a["core_escalation"] is False
        assert payload_a["recovery_hit"] is False
        assert payload_a["readonly_write_tool_exposed"] is False
        assert payload_a["readonly_write_tool_selected_count"] == 0
        assert payload_a["readonly_write_tool_dropped_count"] == 1
        assert payload_a["readonly_write_tool_dropped_slices"] == ["slice_l3_policy"]
        assert payload_a["workflow_id"] == "wf-a"
        assert payload_a["trace_id"] == "trace-a"

        assert payload_b["path"] == "path-c"
        assert payload_b["outer_readonly_hit"] is False
        assert payload_b["core_escalation"] is True
        assert payload_b["recovery_hit"] is True
        assert payload_b["readonly_write_tool_exposed"] is False
        assert payload_b["readonly_write_tool_selected_count"] == 1
        assert payload_b["readonly_write_tool_selected_slices"] == ["slice_l3_policy"]
        assert payload_b["delegation_hit"] is True
        assert payload_b["contract_upgrade_latency_ms"] == 120.0
        assert payload_b["recovery_context_survived"] is True
        assert payload_b["workflow_id"] == "wf-b"
        assert payload_b["trace_id"] == "trace-b"
    finally:
        _cleanup_case_root(case_root)
