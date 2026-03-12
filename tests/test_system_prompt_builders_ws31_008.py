from system.config import build_system_prompt, build_system_prompt_for_route_semantic
from agents.pipeline import _build_core_loop_initial_task


def test_build_system_prompt_uses_shell_identity_and_style() -> None:
    prompt = build_system_prompt(include_skills=False, include_tool_instructions=False)

    assert "你是恩布拉（Embla）" in prompt
    assert "如何组织回答" in prompt


def test_build_system_prompt_for_core_execution_uses_core_identity_and_tool_contract() -> None:
    prompt = build_system_prompt_for_route_semantic("core_execution", include_skills=False)

    assert "你是 Embla 的内核层。" in prompt
    assert "Core Orchestrator Duties" in prompt
    assert "当前可用 MCP 工具摘要" in prompt


def test_core_loop_initial_task_uses_registered_prompt_block() -> None:
    prompt = _build_core_loop_initial_task(
        message="Fix the scheduler drift",
        core_execution_session_id="core-1",
        pipeline_id="pipe-1",
        children_snapshot=[],
    )

    assert "Core lifecycle orchestrator" in prompt
    assert "Pipeline ID: pipe-1" in prompt
    assert "Current descendant roster:" in prompt
