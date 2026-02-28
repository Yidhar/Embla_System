from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent

RUNTIME_SCAN_DIRS = ("apiserver", "system", "scripts")

FORBIDDEN_PATTERNS = (
    "from autonomous.router_engine import",
    "from autonomous.meta_agent_runtime import",
    "from autonomous.gc_pipeline import",
    "from apiserver.agentic_tool_loop import",
)

ALLOWLIST_SUFFIXES = {
    "apiserver/agentic_tool_loop.py",  # compatibility shim itself
}


def _iter_runtime_py_files():
    for dirname in RUNTIME_SCAN_DIRS:
        root = REPO_ROOT / dirname
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            rel = path.relative_to(REPO_ROOT).as_posix()
            if rel.endswith("/__pycache__"):
                continue
            if rel in ALLOWLIST_SUFFIXES:
                continue
            yield path, rel


def test_runtime_imports_use_agents_canonical_namespace_ws28_033() -> None:
    violations: list[str] = []
    for path, rel in _iter_runtime_py_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in FORBIDDEN_PATTERNS:
            if pattern in text:
                violations.append(f"{rel}: {pattern}")
    assert not violations, "\n".join(violations)

