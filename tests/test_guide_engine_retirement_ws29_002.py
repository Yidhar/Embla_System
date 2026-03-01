"""WS29-002: guardrail to ensure retired game-guide runtime path is removed."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]

# Docs may retain historical notes; guardrail focuses on runtime/test/code paths.
SCAN_TARGETS = (
    ROOT / "apiserver",
    ROOT / "autonomous",
    ROOT / "core",
    ROOT / "mcpserver",
    ROOT / "scripts",
    ROOT / "system",
    ROOT / "main.py",
    ROOT / "pyproject.toml",
    ROOT / "config.json.example",
)

BLOCKED_TOKENS = ("guide_engine", "agent_game_guide", "game_guide_llm_api")


def _iter_files() -> Iterable[Path]:
    for target in SCAN_TARGETS:
        if target.is_file():
            yield target
            continue
        if target.is_dir():
            for path in target.rglob("*"):
                if path.is_file() and path.suffix in {".py", ".toml", ".json", ".md"}:
                    yield path


def test_runtime_code_has_no_retired_game_guide_references() -> None:
    violations: list[str] = []
    for path in _iter_files():
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="ignore")
        lowered = text.lower()
        for token in BLOCKED_TOKENS:
            if token in lowered:
                violations.append(f"{rel}: contains {token}")
    assert not violations, "Found retired guide-engine references:\n" + "\n".join(violations)
