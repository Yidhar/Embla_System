from __future__ import annotations

from pathlib import Path

from agents import (
    CoreAgent,
    DevAgent,
    ExpertAgent,
    Goal,
    MetaAgentRuntime,
    MiniLoopConfig,
    PromptAssembler,
    ReviewAgent,
    ReviewResult,
    RouterRequest,
    TaskRouterEngine,
    convert_structured_tool_calls,
    get_agentic_tool_definitions,
    run_agentic_loop,
)
from agents.contract_runtime import (
    CoreExecutionContractInput,
    build_core_execution_contract_payload,
    build_core_execution_messages,
)
from agents.memory import GCPipelineConfig, run_gc_pipeline
from pydantic import ValidationError


def test_agents_namespace_contracts_resolve() -> None:
    runtime = MetaAgentRuntime()
    goal = Goal(goal_id="goal-1", description="修复一次告警并验证")
    tasks = runtime.accept_goal(goal)
    assert len(tasks) >= 1

    router = TaskRouterEngine()
    decision = router.route(
        RouterRequest(
            task_id="task-1",
            description="修复 API bug 并补测试",
            risk_level="write_repo",
        )
    )
    assert decision.task_id == "task-1"
    assert decision.selected_role

    config = GCPipelineConfig()
    assert config.max_total_records > 0


def test_agents_namespace_owns_brain_implementations() -> None:
    assert MetaAgentRuntime.__module__.startswith("agents.")
    assert TaskRouterEngine.__module__.startswith("agents.")
    assert RouterRequest.__module__.startswith("agents.")
    assert Goal.__module__.startswith("agents.")
    assert CoreAgent.__module__.startswith("agents.")
    assert ExpertAgent.__module__.startswith("agents.")
    assert DevAgent.__module__.startswith("agents.")
    assert PromptAssembler.__module__.startswith("agents.")
    assert MiniLoopConfig.__module__.startswith("agents.")
    assert ReviewAgent.__module__.startswith("agents.")
    assert ReviewResult.__module__.startswith("agents.")


def test_agents_router_request_contract_rejects_unknown_field() -> None:
    try:
        RouterRequest(
            task_id="task-x",
            description="检查契约",
            risk_level="read_only",
            unknown_key="not_allowed",
        )
    except ValidationError:
        return
    raise AssertionError("RouterRequest should reject unknown fields")


def test_agents_gc_pipeline_has_pydantic_contract_and_report(tmp_path: Path) -> None:
    archive = tmp_path / "memory_archive.jsonl"
    archive.write_text(
        "\n".join(
            [
                '{"session_id":"s1","timestamp":1000.0,"result":"old"}',
                '{"session_id":"s1","timestamp":2000.0,"result":"new"}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "gc_report.json"
    report = run_gc_pipeline(
        archive_path=archive,
        output_path=output,
        config=GCPipelineConfig(
            retention_seconds=3600.0,
            max_records_per_session=1,
            max_total_records=10,
            dry_run=True,
        ),
    )
    assert report["scenario"] == "agents_gc_pipeline"
    assert report["checks"]["retained_not_exceed_total_cap"] is True
    assert Path(report["output_path"]).name == output.name


def test_agents_contract_runtime_builds_contract_and_messages() -> None:
    payload = build_core_execution_contract_payload(
        session_id="sess-1",
        current_message="继续",
        recent_messages=[],
    )
    validated = CoreExecutionContractInput.model_validate(payload)
    assert validated.contract_stage == "seed"
    assert validated.goal == "继续"
    assert validated.evidence_path_hint == "scratch/reports/"

    messages = build_core_execution_messages(
        session_id="sess-1",
        current_message="请修复失败用例",
        core_system_prompt="SYSTEM_PROMPT",
        recent_messages=[{"role": "user", "content": "先看报错"}],
    )
    assert len(messages) == 3
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "system"
    assert str(messages[1]["content"]).startswith("[ExecutionContractInput]")


def test_agents_tool_loop_entrypoint_contracts_resolve() -> None:
    definitions = get_agentic_tool_definitions()
    names = [str(item.get("function", {}).get("name", "")) for item in definitions]
    assert "native_call" in names
    assert "SubmitResult_Tool" in names

    calls, errors = convert_structured_tool_calls(
        [{"id": "c1", "name": "native_call", "arguments": {"tool_name": "read_file", "path": "README.md"}}],
        session_id="sess-x",
    )
    assert errors == []
    assert calls
    assert callable(run_agentic_loop)


def test_agents_memory_namespace_exports_core_modules() -> None:
    from agents.memory import (
        MemoryWindowThresholds,
        SemanticGraphStore,
        WorkingMemoryWindowManager,
    )

    thresholds = MemoryWindowThresholds()
    manager = WorkingMemoryWindowManager(thresholds=thresholds)
    assert manager.estimate_tokens([{"role": "user", "content": "hello"}]) > 0
    assert WorkingMemoryWindowManager.__module__.startswith("agents.memory.")
    assert SemanticGraphStore.__module__.startswith("agents.memory.")
