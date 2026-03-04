from pathlib import Path

from agents.core_agent import CoreAgent, PROMPT_PROFILE_MAP


def test_core_prompt_profile_templates_exist() -> None:
    prompts_root = Path("system/prompts")
    missing = []
    for profile_name, relative_path in PROMPT_PROFILE_MAP.items():
        candidate = prompts_root / relative_path
        if not candidate.exists():
            missing.append(f"{profile_name}:{candidate.as_posix()}")
    assert missing == []


def test_core_build_system_prompt_includes_profile_block() -> None:
    core = CoreAgent()
    prompt = core.build_system_prompt(prompt_profile="core_exec_ops")
    assert "Core Exec Profile: Ops" in prompt

