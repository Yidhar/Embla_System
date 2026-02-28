from __future__ import annotations

import importlib


def test_apiserver_tool_loop_shim_resolves_to_agents_module_ws28_033() -> None:
    legacy = importlib.import_module("apiserver.agentic_tool_loop")
    canonical = importlib.import_module("agents.tool_loop")

    assert legacy is canonical
    assert hasattr(legacy, "run_agentic_loop")
    assert hasattr(legacy, "_convert_structured_tool_calls")

