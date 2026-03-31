#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import main as embla_main


def main(argv: list[str] | None = None) -> int:
    forwarded = list(argv or sys.argv[1:])
    if "--prepare-runtime" not in forwarded and "--prepare-runtime-all-profiles" not in forwarded:
        forwarded = ["--prepare-runtime", *forwarded]
    return embla_main.main(forwarded)


if __name__ == "__main__":
    raise SystemExit(main())
