"""WS16-002: guardrail to prevent new direct `agentserver` Python imports."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
DIRECT_IMPORT_PATTERN = re.compile(r"^\s*(from\s+agentserver(?:\.|\s)|import\s+agentserver(?:\.|\s|$))")

# AgentServer 已完成退役，不再允许任何直接导入。
ALLOWED_DIRECT_IMPORT_FILES: set[str] = set()


def _iter_python_files() -> Iterable[Path]:
    targets = [
        ROOT / "main.py",
        ROOT / "apiserver",
        ROOT / "autonomous",
        ROOT / "mcpserver",
        ROOT / "system",
        ROOT / "scripts",
    ]
    for target in targets:
        if target.is_file() and target.suffix == ".py":
            yield target
            continue
        if not target.is_dir():
            continue
        for path in target.rglob("*.py"):
            yield path


def test_no_new_direct_agentserver_imports_outside_allowlist() -> None:
    violations: list[str] = []
    allowlist_hits: set[str] = set()

    for path in _iter_python_files():
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="ignore")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if not DIRECT_IMPORT_PATTERN.search(line):
                continue
            if rel in ALLOWED_DIRECT_IMPORT_FILES:
                allowlist_hits.add(rel)
            else:
                violations.append(f"{rel}:{lineno}:{line.strip()}")

    assert not violations, "Unexpected new direct agentserver imports:\n" + "\n".join(violations)
    assert allowlist_hits <= ALLOWED_DIRECT_IMPORT_FILES
