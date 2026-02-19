#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tiny repo-local grep helper.

Usage:
  python system/_dev_grep.py <file> <pattern>

Prints matching line numbers and the line text.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: python system/_dev_grep.py <file> <pattern>")
        return 2

    file_path = Path(sys.argv[1])
    pattern = sys.argv[2]

    try:
        text = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = file_path.read_text(encoding="utf-8", errors="replace")

    rx = re.compile(pattern)
    for i, line in enumerate(text.splitlines(), 1):
        if rx.search(line):
            print(f"{i}: {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
