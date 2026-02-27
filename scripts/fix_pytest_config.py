#!/usr/bin/env python3
"""Fix duplicate pytest ini options keys in pyproject.toml.

- Ensures only one `addopts = ...` entry exists under [tool.pytest.ini_options].
- Keeps `addopts = "-q"` as the canonical value.

Idempotent.
"""

from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"


def main() -> int:
    text = PYPROJECT.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines(keepends=False)

    header = "[tool.pytest.ini_options]"
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == header)
    except StopIteration:
        raise SystemExit("pytest ini section not found")

    # Find end (next top-level table header)
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("[") and lines[i].strip() != header:
            end = i
            break

    before = lines[: start + 1]
    section = lines[start + 1 : end]
    after = lines[end:]

    # Remove all existing addopts lines
    section_wo_addopts = [line for line in section if not re.match(r"^\s*addopts\s*=", line)]

    desired_addopts = 'addopts = "-q"'

    # Insert addopts as the first non-empty, non-comment line (right after header)
    inserted = False
    new_section: list[str] = []
    for line in section_wo_addopts:
        if not inserted and line.strip() and not line.lstrip().startswith("#"):
            new_section.append(desired_addopts)
            inserted = True
        new_section.append(line)

    if not inserted:
        # section was empty or only comments
        new_section = [desired_addopts] + section_wo_addopts

    new_text = "\n".join(before + new_section + after) + "\n"
    PYPROJECT.write_text(new_text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
