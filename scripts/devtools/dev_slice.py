#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Print file lines in a range.

Usage:
  python scripts/devtools/dev_slice.py <file> <start> <end>

Start/end are 1-based inclusive.
"""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 4:
        print("usage: python scripts/devtools/dev_slice.py <file> <start> <end>")
        return 2

    file_path = Path(sys.argv[1])
    start = int(sys.argv[2])
    end = int(sys.argv[3])

    try:
        text = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = file_path.read_text(encoding="utf-8", errors="replace")

    lines = text.splitlines()
    start = max(1, start)
    end = min(len(lines), end)

    for i in range(start, end + 1):
        print(f"{i}: {lines[i-1]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
