#!/usr/bin/env python3
"""Patch pyproject.toml pytest config.

Rewrites the [tool.pytest.ini_options] table to avoid collecting tests from
packaged artifacts / node_modules and to focus on project-owned tests.
"""

from __future__ import annotations

from pathlib import Path
import re


def main() -> int:
    path = Path("pyproject.toml")
    text = path.read_text(encoding="utf-8")

    new_block = """
[tool.pytest.ini_options]
addopts = "-q"
# Only run project-owned unit tests by default.
testpaths = [
  "autonomous/tests",
]
python_files = ["test_*.py", "*_test.py"]

# Avoid collecting tests from build artifacts or third-party vendored trees.
norecursedirs = [
  ".git",
  ".venv",
  "__pycache__",
  ".pytest_cache",
  "build",
  "dist",
  "frontend/backend-dist",
  "frontend/release",
  "frontend/node_modules",
  "node_modules",
]

# Exclude integration / manual scripts that are not pytest-ready.
addopts = "-q"
""".strip("\n")

    # Replace existing table if present, else append.
    m = re.search(r"^\[tool\.pytest\.ini_options\]\s*$", text, flags=re.MULTILINE)
    if not m:
        text2 = text.rstrip() + "\n\n" + new_block + "\n"
        path.write_text(text2, encoding="utf-8")
        return 0

    start = m.start()
    # Find next table header after start.
    nxt = re.search(r"^\[[^\]]+\]\s*$", text[m.end() :], flags=re.MULTILINE)
    end = m.end() + (nxt.start() if nxt else len(text[m.end() :]))
    text2 = text[:start].rstrip() + "\n\n" + new_block + "\n" + text[end:].lstrip()
    path.write_text(text2, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
