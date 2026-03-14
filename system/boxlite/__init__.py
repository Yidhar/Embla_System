from __future__ import annotations

from importlib import import_module


__all__ = [
    "BoxLiteRuntimeProfile",
    "BoxLiteRuntimeSettings",
    "BoxLiteRuntimeStatus",
    "BoxLiteManager",
    "build_box_session_name",
    "build_boxlite_volume_mounts",
    "build_local_boxlite_runtime_image",
    "clear_boxlite_runtime_readiness_cache",
    "ensure_boxlite_runtime_profile",
    "get_boxlite_runtime_assets_summary",
    "load_boxlite_runtime_settings",
    "prepare_boxlite_runtime_installation",
    "probe_boxlite_runtime",
    "probe_boxlite_runtime_readiness",
    "run_boxlite_runtime_reconciler",
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
