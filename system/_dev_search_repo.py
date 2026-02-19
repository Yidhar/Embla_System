#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Search plain substring in repo files.

Usage:
  python system/_dev_search_repo.py <needle> [root]

Prints: relative_path:line_no: line
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python system/_dev_search_repo.py <needle> [root]")
        return 2

    needle = sys.argv[1]
    root = Path(sys.argv[2]) if len(sys.argv) >= 3 else Path(__file__).parent.parent
    root = root.resolve()

    ignore_dirs = {".git", ".venv", "__pycache__", "node_modules", "dist", "release", "logs"}
    exts_skip = {".png", ".jpg", ".jpeg", ".gif", ".mp3", ".wav", ".zip", ".7z", ".exe"}

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in ignore_dirs]
        for fn in filenames:
            p = Path(dirpath) / fn
            if p.suffix.lower() in exts_skip:
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            if needle not in text:
                continue
            rel = p.relative_to(root).as_posix()
            for i, line in enumerate(text.splitlines(), 1):
                if needle in line:
                    print(f"{rel}:{i}: {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
