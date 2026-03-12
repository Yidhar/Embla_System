from pathlib import Path


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_conversation_style_prompt_stays_out_of_shell_identity_and_runtime_contract() -> None:
    content = _read("system/prompts/core/dna/conversation_style_prompt.md")

    forbidden_markers = (
        "Shell Chat Agent",
        "shell_readonly",
        "shell_clarify",
        "core_execution",
        "route_semantic",
        "Task Contract",
        "TSP-v1",
        "CanaryRunning",
        "ReleaseCandidate",
        "lease/fencing",
        "任务排期协议",
        "发布语义",
    )

    for marker in forbidden_markers:
        assert marker not in content


def test_shell_persona_keeps_identity_dna_separate_from_conversation_style() -> None:
    content = _read("system/prompts/dna/shell_persona.md")

    assert "你是恩布拉（Embla）" in content
    assert "不定义任务路由、工具边界或执行协议" in content


def test_agentic_tool_prompt_stays_out_of_route_and_role_semantics() -> None:
    content = _read("system/prompts/core/dna/agentic_tool_prompt.md")

    forbidden_markers = (
        "Shell 路径通常只暴露",
        "Core / Dev / Review",
        "dispatch_to_core",
        "执行优先",
        "执行闭环",
        "任务排期",
        "高风险确认或更高层 contract",
    )

    for marker in forbidden_markers:
        assert marker not in content
