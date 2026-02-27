#!/usr/bin/env python3
"""Compatibility wrapper for Embla_core release gate entrypoint.

Canonical implementation lives in:
`scripts/gates/embla_core/embla_core_release_compat_gate.py`.
"""

from __future__ import annotations

from scripts.gates.embla_core.embla_core_release_compat_gate import (
    build_release_compat_report,
    main,
    write_report,
)

__all__ = ["build_release_compat_report", "write_report", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
