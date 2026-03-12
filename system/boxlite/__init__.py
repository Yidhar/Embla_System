from __future__ import annotations

from importlib import import_module


__all__ = [
    "BoxLiteRuntimeSettings",
    "BoxLiteRuntimeStatus",
    "BoxLiteManager",
    "build_box_session_name",
    "build_boxlite_volume_mounts",
    "load_boxlite_runtime_settings",
    "probe_boxlite_runtime",
    "resolve_execution_runtime_metadata",
    "teardown_box_session",
]


def __getattr__(name: str):
    if name not in __all__:
        raise AttributeError(f"module 'system.boxlite' has no attribute {name!r}")
    manager = import_module("system.boxlite.manager")
    value = getattr(manager, name)
    globals()[name] = value
    return value
