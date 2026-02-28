from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

from autonomous.router_engine import RouterRequest, TaskRouterEngine


def _make_case_root(prefix: str) -> Path:
    root = Path("scratch") / prefix / uuid.uuid4().hex[:12]
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_case_root(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


def test_router_engine_routes_high_risk_ops_to_sys_admin_primary() -> None:
    router = TaskRouterEngine()
    request = RouterRequest(
        task_id="task-ops-001",
        description="nginx 故障恢复并重启服务",
        estimated_complexity="high",
        risk_level="deploy",
        budget_remaining=15000,
        trace_id="trace-ops-001",
    )
    decision = router.route(request)
    assert decision.task_type == "ops"
    assert decision.selected_role == "sys_admin"
    assert decision.selected_model_tier == "primary"
    assert decision.replay_fingerprint
    assert any("risk level deploy" in reason for reason in decision.reasoning)
    assert decision.workflow_entry_state == "planned"
    assert decision.controlled_execution_plan["schema_version"] == "ws28_router_workflow_engine.v1"
    assert decision.controlled_execution_plan["entry_state"] == "planned"
    assert decision.controlled_execution_plan["route_contract"]["selected_role"] == decision.selected_role
    assert decision.controlled_execution_plan["guardrails"]["requires_human_approval"] is True


def test_router_engine_uses_budget_tiering() -> None:
    router = TaskRouterEngine()
    low_budget = router.route(
        RouterRequest(
            task_id="task-budget-001",
            description="整理接口文档并补充说明",
            estimated_complexity="low",
            risk_level="read_only",
            budget_remaining=1200,
        )
    )
    mid_budget = router.route(
        RouterRequest(
            task_id="task-budget-002",
            description="分析日志并总结问题",
            estimated_complexity="medium",
            risk_level="read_only",
            budget_remaining=5000,
        )
    )
    assert low_budget.selected_model_tier == "local"
    assert mid_budget.selected_model_tier == "secondary"


def test_router_engine_decision_is_replayable() -> None:
    router = TaskRouterEngine()
    request = RouterRequest(
        task_id="task-replay-001",
        description="修复 API 返回字段不一致的问题",
        estimated_complexity="medium",
        risk_level="write_repo",
        budget_remaining=9000,
    )
    first = router.route(request)
    second = router.route(request)
    assert first.replay_fingerprint == second.replay_fingerprint
    assert router.replay(request, first.replay_fingerprint) is True


def test_router_engine_writes_decision_log() -> None:
    case_root = _make_case_root("test_router_engine_ws19_002")
    try:
        log_file = case_root / "router_decisions.jsonl"
        router = TaskRouterEngine(decision_log=log_file)
        decision = router.route(
            RouterRequest(
                task_id="task-log-001",
                description="排查 k8s pod 重启原因",
                estimated_complexity="medium",
                risk_level="read_only",
                budget_remaining=7000,
                trace_id="trace-log-001",
                session_id="session-log-001",
            )
        )
        rows = [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert len(rows) == 1
        assert rows[0]["request"]["task_id"] == "task-log-001"
        assert rows[0]["decision"]["decision_id"] == decision.decision_id
        assert rows[0]["decision"]["replay_fingerprint"] == decision.replay_fingerprint
        assert rows[0]["decision"]["workflow_entry_state"] == "planned"
        assert rows[0]["decision"]["controlled_execution_plan"]["schema_version"] == "ws28_router_workflow_engine.v1"
    finally:
        _cleanup_case_root(case_root)
