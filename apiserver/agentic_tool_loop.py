"""Compatibility shim for legacy imports.

Canonical implementation moved to `agents.tool_loop`.
"""

from __future__ import annotations

import sys

from agents import tool_loop as _impl

# Make `import apiserver.agentic_tool_loop` resolve to the canonical module
# object so monkeypatches and attribute writes affect runtime behavior.
sys.modules[__name__] = _impl
