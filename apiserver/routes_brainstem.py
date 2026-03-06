"""Brainstem bootstrap domain — extracted from api_server.py (Phase 3).

Contains:
- Brainstem autostart/autostop lifecycle management
- Immutable DNA preflight and monitoring
- Global mutex lease bootstrap
- Budget guard state bootstrap
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)
_BRAINSTEM_RUNTIME_CONTEXT: Dict[str, Any] = {
    "app": None,
    "app_getter": None,
    "llm_service_getter": None,
    "event_store_class_getter": None,
}

# ── Import shared utilities ──────────────────────────────────
from apiserver._shared import env_flag as _env_flag
from apiserver._shared import env_float as _env_float
from apiserver._shared import ops_repo_root as _ops_repo_root


# ── Lazy cross-module accessors (avoid circular import) ──────
def _bind_brainstem_runtime_context(
    *,
    app: Any = None,
    app_getter: Any = None,
    llm_service_getter: Any = None,
    event_store_class_getter: Any = None,
) -> None:
    """Bind runtime dependencies to reduce api_server import coupling."""
    if app is not None:
        _BRAINSTEM_RUNTIME_CONTEXT["app"] = app
    if app_getter is not None:
        _BRAINSTEM_RUNTIME_CONTEXT["app_getter"] = app_getter
    if llm_service_getter is not None:
        _BRAINSTEM_RUNTIME_CONTEXT["llm_service_getter"] = llm_service_getter
    if event_store_class_getter is not None:
        _BRAINSTEM_RUNTIME_CONTEXT["event_store_class_getter"] = event_store_class_getter


def _get_llm_service():
    getter = _BRAINSTEM_RUNTIME_CONTEXT.get("llm_service_getter")
    if callable(getter):
        return getter()
    from apiserver.llm_service import get_llm_service
    return get_llm_service()

def _get_event_store_class():
    getter = _BRAINSTEM_RUNTIME_CONTEXT.get("event_store_class_getter")
    if callable(getter):
        return getter()
    from core.event_bus import EventStore
    return EventStore

def _get_app():
    app = _BRAINSTEM_RUNTIME_CONTEXT.get("app")
    if app is not None:
        return app
    getter = _BRAINSTEM_RUNTIME_CONTEXT.get("app_getter")
    if callable(getter):
        app = getter()
        if app is not None:
            return app
    raise RuntimeError("brainstem runtime app context is not bound")

__all__ = [
    "_BRAINSTEM_AUTOSTART_DEFAULT",
    "_BRAINSTEM_AUTOSTART_ENV",
    "_BRAINSTEM_AUTOSTART_OUTPUT",
    "_BRAINSTEM_AUTOSTART_TIMEOUT_ENV",
    "_BRAINSTEM_AUTOSTOP_ENV",
    "_BRAINSTEM_AUTOSTOP_OUTPUT",
    "_BRAINSTEM_BOOTSTRAP_OWNER_API",
    "_BRAINSTEM_BOOTSTRAP_OWNER_ENV",
    "_BUDGET_GUARD_BOOTSTRAP_STATE_FILE",
    "_GLOBAL_MUTEX_BOOTSTRAP_TTL_SECONDS",
    "_IMMUTABLE_DNA_MONITOR_ALLOW_HASH_ROTATION_ENV",
    "_IMMUTABLE_DNA_MONITOR_ENABLED_ENV",
    "_IMMUTABLE_DNA_MONITOR_INTERVAL_SECONDS_ENV",
    "_IMMUTABLE_DNA_MONITOR_STATE_FILE",
    "_IMMUTABLE_DNA_PREFLIGHT_REQUIRED_ENV",
    "_bootstrap_brainstem_control_plane_shutdown",
    "_bootstrap_brainstem_control_plane_startup",
    "_bootstrap_budget_guard_state",
    "_bootstrap_global_mutex_lease_state",
    "_bootstrap_immutable_dna_monitor_shutdown",
    "_bootstrap_immutable_dna_monitor_startup",
    "_bootstrap_immutable_dna_preflight",
    "_bind_brainstem_runtime_context",
    "_brainstem_bootstrap_owned_by_external",
    "_brainstem_bootstrap_owner",
    "_env_flag",
    "_env_float",
    "_should_bootstrap_brainstem_control_plane",
]

# ── Brainstem bootstrap constants ─────────────────────────────
_BRAINSTEM_AUTOSTART_ENV = "EMBLA_BRAINSTEM_AUTOSTART"
_BRAINSTEM_AUTOSTOP_ENV = "EMBLA_BRAINSTEM_AUTOSTOP_ON_API_SHUTDOWN"
_BRAINSTEM_AUTOSTART_TIMEOUT_ENV = "EMBLA_BRAINSTEM_AUTOSTART_TIMEOUT_SECONDS"
_BRAINSTEM_BOOTSTRAP_OWNER_ENV = "EMBLA_BRAINSTEM_BOOTSTRAP_OWNER"
_BRAINSTEM_BOOTSTRAP_OWNER_API = "api"
_BRAINSTEM_AUTOSTART_DEFAULT = True
_BRAINSTEM_AUTOSTART_OUTPUT = Path("scratch/reports/brainstem_control_plane_autostart_ws28_017.json")
_BRAINSTEM_AUTOSTOP_OUTPUT = Path("scratch/reports/brainstem_control_plane_autostop_ws28_017.json")
_GLOBAL_MUTEX_BOOTSTRAP_TTL_SECONDS = 10.0
_BUDGET_GUARD_BOOTSTRAP_STATE_FILE = Path("scratch/runtime/budget_guard_state_ws28_028.json")
_IMMUTABLE_DNA_PREFLIGHT_REQUIRED_ENV = "EMBLA_IMMUTABLE_DNA_PREFLIGHT_REQUIRED"
_IMMUTABLE_DNA_MONITOR_ENABLED_ENV = "EMBLA_IMMUTABLE_DNA_MONITOR_ENABLED"
_IMMUTABLE_DNA_MONITOR_INTERVAL_SECONDS_ENV = "EMBLA_IMMUTABLE_DNA_MONITOR_INTERVAL_SECONDS"
_IMMUTABLE_DNA_MONITOR_ALLOW_HASH_ROTATION_ENV = "EMBLA_IMMUTABLE_DNA_MONITOR_ALLOW_HASH_ROTATION"
_IMMUTABLE_DNA_MONITOR_STATE_FILE = Path("scratch/runtime/immutable_dna_integrity_state_ws30_001.json")


# ── Brainstem bootstrap functions ─────────────────────────────
def _brainstem_bootstrap_owner() -> str:
    return str(os.environ.get(_BRAINSTEM_BOOTSTRAP_OWNER_ENV) or "").strip().lower()


def _brainstem_bootstrap_owned_by_external() -> tuple[bool, str]:
    owner = _brainstem_bootstrap_owner()
    if not owner:
        return False, ""
    if owner in {_BRAINSTEM_BOOTSTRAP_OWNER_API, "apiserver"}:
        return False, owner
    return True, owner


def _should_bootstrap_brainstem_control_plane() -> tuple[bool, str]:
    external_owned, owner = _brainstem_bootstrap_owned_by_external()
    if external_owned:
        return False, f"owned_by_{owner}"
    explicit = os.environ.get(_BRAINSTEM_AUTOSTART_ENV)
    if explicit is None and os.environ.get("PYTEST_CURRENT_TEST"):
        return False, "pytest_default_skip"
    enabled = _env_flag(_BRAINSTEM_AUTOSTART_ENV, _BRAINSTEM_AUTOSTART_DEFAULT)
    if not enabled:
        return False, "env_disabled"
    return True, "enabled"


def _bootstrap_brainstem_control_plane_startup(
    *,
    manager: Optional[Callable[..., Dict[str, Any]]] = None,
    repo_root: Optional[Path] = None,
) -> Dict[str, Any]:
    enabled, reason = _should_bootstrap_brainstem_control_plane()
    root = (repo_root or _ops_repo_root()).resolve()
    report: Dict[str, Any] = {
        "enabled": enabled,
        "reason": reason,
        "repo_root": str(root).replace("\\", "/"),
        "env": {
            "autostart_env": _BRAINSTEM_AUTOSTART_ENV,
            "autostop_env": _BRAINSTEM_AUTOSTOP_ENV,
            "autostart_timeout_env": _BRAINSTEM_AUTOSTART_TIMEOUT_ENV,
        },
    }
    if not enabled:
        return report

    run_manager = manager
    if run_manager is None:
        from scripts.manage_brainstem_control_plane_ws28_017 import run_manage_brainstem_control_plane_ws28_017

        run_manager = run_manage_brainstem_control_plane_ws28_017

    timeout_seconds = max(2.0, _env_float(_BRAINSTEM_AUTOSTART_TIMEOUT_ENV, 8.0))
    try:
        startup_report = run_manager(
            repo_root=root,
            action="start",
            output_file=_BRAINSTEM_AUTOSTART_OUTPUT,
            start_timeout_seconds=timeout_seconds,
            force_restart=False,
        )
        report["passed"] = bool(startup_report.get("passed"))
        report["startup_report"] = startup_report
        if bool(startup_report.get("passed")):
            logger.info("[brainstem_bootstrap] control plane startup ensured")
        else:
            logger.warning("[brainstem_bootstrap] control plane startup failed")
    except Exception as exc:
        report["passed"] = False
        report["error"] = f"{type(exc).__name__}:{exc}"
        logger.error(f"[brainstem_bootstrap] startup error: {exc}")
    return report


def _bootstrap_brainstem_control_plane_shutdown(
    *,
    manager: Optional[Callable[..., Dict[str, Any]]] = None,
    repo_root: Optional[Path] = None,
) -> Dict[str, Any]:
    external_owned, owner = _brainstem_bootstrap_owned_by_external()
    enabled = _env_flag(_BRAINSTEM_AUTOSTOP_ENV, False)
    root = (repo_root or _ops_repo_root()).resolve()
    report: Dict[str, Any] = {
        "enabled": enabled,
        "repo_root": str(root).replace("\\", "/"),
        "env": {
            "autostop_env": _BRAINSTEM_AUTOSTOP_ENV,
            "owner_env": _BRAINSTEM_BOOTSTRAP_OWNER_ENV,
        },
    }
    if external_owned:
        report["enabled"] = False
        report["reason"] = f"owned_by_{owner}"
        return report
    if not enabled:
        report["reason"] = "env_disabled"
        return report

    run_manager = manager
    if run_manager is None:
        from scripts.manage_brainstem_control_plane_ws28_017 import run_manage_brainstem_control_plane_ws28_017

        run_manager = run_manage_brainstem_control_plane_ws28_017

    try:
        shutdown_report = run_manager(
            repo_root=root,
            action="stop",
            output_file=_BRAINSTEM_AUTOSTOP_OUTPUT,
        )
        report["passed"] = bool(shutdown_report.get("passed"))
        report["shutdown_report"] = shutdown_report
        if bool(shutdown_report.get("passed")):
            logger.info("[brainstem_bootstrap] control plane stop completed")
        else:
            logger.warning("[brainstem_bootstrap] control plane stop reported failures")
    except Exception as exc:
        report["passed"] = False
        report["error"] = f"{type(exc).__name__}:{exc}"
        logger.error(f"[brainstem_bootstrap] shutdown error: {exc}")
    return report


def _bootstrap_global_mutex_lease_state(
    *,
    manager_factory: Optional[Callable[[], Any]] = None,
) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "enabled": True,
        "ttl_seconds": float(_GLOBAL_MUTEX_BOOTSTRAP_TTL_SECONDS),
    }
    try:
        if manager_factory is None:
            from core.security import get_global_mutex_manager

            manager = get_global_mutex_manager()
        else:
            manager = manager_factory()

        state = manager.ensure_initialized(ttl_seconds=float(_GLOBAL_MUTEX_BOOTSTRAP_TTL_SECONDS))
        state_file = Path(str(getattr(manager, "state_file", "") or "")).resolve()
        report["state_file"] = str(state_file).replace("\\", "/")
        report["state"] = str(state.get("lease_state") or state.get("state") or "")
        report["fencing_epoch"] = int(state.get("fencing_epoch") or 0)
        report["passed"] = state_file.exists()
        if report["passed"]:
            logger.info("[global_mutex_bootstrap] lease state initialized")
        else:
            logger.warning("[global_mutex_bootstrap] state file missing after bootstrap")
    except Exception as exc:
        report["passed"] = False
        report["error"] = f"{type(exc).__name__}:{exc}"
        logger.error(f"[global_mutex_bootstrap] bootstrap error: {exc}")
    return report


def _bootstrap_immutable_dna_preflight() -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "enabled": True,
        "required": _env_flag(_IMMUTABLE_DNA_PREFLIGHT_REQUIRED_ENV, True),
    }
    try:
        llm = _get_llm_service()
        preflight = llm.immutable_dna_preflight()
        report.update(preflight if isinstance(preflight, dict) else {})
        report["passed"] = bool(report.get("passed", False))
        if bool(report.get("passed", False)):
            logger.info("[immutable_dna_bootstrap] preflight passed")
        else:
            logger.error("[immutable_dna_bootstrap] preflight failed: %s", report.get("reason", "unknown"))
    except Exception as exc:
        report["passed"] = False
        report["reason"] = "immutable_dna_preflight_exception"
        report["error"] = f"{type(exc).__name__}:{exc}"
        logger.error("[immutable_dna_bootstrap] preflight exception: %s", exc)
    return report


def _bootstrap_immutable_dna_monitor_startup(*, repo_root: Optional[Path] = None) -> Dict[str, Any]:
    root = (repo_root or _ops_repo_root()).resolve()
    state_file = (root / _IMMUTABLE_DNA_MONITOR_STATE_FILE).resolve()
    interval_seconds = max(5.0, _env_float(_IMMUTABLE_DNA_MONITOR_INTERVAL_SECONDS_ENV, 30.0))
    enabled = _env_flag(_IMMUTABLE_DNA_MONITOR_ENABLED_ENV, True)
    allow_hash_rotation = _env_flag(_IMMUTABLE_DNA_MONITOR_ALLOW_HASH_ROTATION_ENV, False)
    report: Dict[str, Any] = {
        "enabled": enabled,
        "state_file": str(state_file).replace("\\", "/"),
        "interval_seconds": float(interval_seconds),
        "allow_manifest_hash_rotation": bool(allow_hash_rotation),
        "passed": False,
    }
    if not enabled:
        report["passed"] = True
        report["reason"] = "immutable_dna_monitor_disabled"
        return report

    try:
        llm = _get_llm_service()
        loader = llm.get_immutable_dna_loader()
        if loader is None:
            report["reason"] = "immutable_dna_loader_unavailable"
            return report

        from core.security import ImmutableDNAIntegrityMonitor

        event_store = _get_event_store_class()(file_path=(root / "logs" / "autonomous" / "events.jsonl").resolve())
        monitor = ImmutableDNAIntegrityMonitor(
            loader=loader,
            event_emitter=event_store,
            state_file=state_file,
            interval_seconds=interval_seconds,
            allow_manifest_hash_rotation=allow_hash_rotation,
        )
        first_observation = monitor.run_once()
        stop_event = threading.Event()
        thread = threading.Thread(
            target=monitor.run_daemon,
            kwargs={
                "stop_event": stop_event,
                "interval_seconds": interval_seconds,
            },
            daemon=True,
            name="immutable_dna_integrity_monitor",
        )
        thread.start()

        _app = _get_app()
        _app.state.immutable_dna_integrity_monitor = monitor
        _app.state.immutable_dna_integrity_monitor_stop_event = stop_event
        _app.state.immutable_dna_integrity_monitor_thread = thread
        _app.state.immutable_dna_integrity_state_file = str(state_file).replace("\\", "/")

        report["initial_state"] = first_observation
        report["passed"] = str(first_observation.get("status") or "").strip().lower() != "critical"
        report["reason"] = str(first_observation.get("reason_code") or "")
        if report["passed"]:
            logger.info("[immutable_dna_monitor] startup succeeded")
        else:
            logger.error("[immutable_dna_monitor] startup detected critical state: %s", report.get("reason"))
    except Exception as exc:
        report["passed"] = False
        report["reason"] = "immutable_dna_monitor_startup_exception"
        report["error"] = f"{type(exc).__name__}:{exc}"
        logger.error("[immutable_dna_monitor] startup exception: %s", exc)

    return report


def _bootstrap_immutable_dna_monitor_shutdown() -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "enabled": True,
        "passed": True,
        "reason": "",
    }
    _app = _get_app()
    stop_event = getattr(_app.state, "immutable_dna_integrity_monitor_stop_event", None)
    thread = getattr(_app.state, "immutable_dna_integrity_monitor_thread", None)
    if stop_event is None and thread is None:
        report["reason"] = "immutable_dna_monitor_not_started"
        return report
    try:
        if isinstance(stop_event, threading.Event):
            stop_event.set()
        if isinstance(thread, threading.Thread):
            thread.join(timeout=2.0)
            report["thread_alive"] = bool(thread.is_alive())
            report["passed"] = not bool(thread.is_alive())
        report["reason"] = "ok" if report.get("passed") else "immutable_dna_monitor_thread_alive"
    except Exception as exc:
        report["passed"] = False
        report["reason"] = "immutable_dna_monitor_shutdown_exception"
        report["error"] = f"{type(exc).__name__}:{exc}"
        logger.error("[immutable_dna_monitor] shutdown exception: %s", exc)
    return report


def _bootstrap_budget_guard_state(
    *,
    controller_factory: Optional[Callable[[Path], Any]] = None,
    repo_root: Optional[Path] = None,
) -> Dict[str, Any]:
    root = (repo_root or _ops_repo_root()).resolve()
    state_file = root / _BUDGET_GUARD_BOOTSTRAP_STATE_FILE
    report: Dict[str, Any] = {
        "enabled": True,
        "state_file": str(state_file).replace("\\", "/"),
        "passed": False,
        "baseline_written": False,
    }
    try:
        if controller_factory is None:
            from core.security import BudgetGuardController

            controller = BudgetGuardController(state_file=state_file)
        else:
            controller = controller_factory(state_file)

        baseline = controller.ensure_baseline_state(requested_by="api_lifespan_bootstrap")
        report["baseline"] = baseline if isinstance(baseline, dict) else {}
        report["status"] = str(report["baseline"].get("status") or "")
        report["reason_code"] = str(report["baseline"].get("reason_code") or "")
        report["baseline_written"] = bool(report["baseline"].get("baseline_written"))
        report["passed"] = state_file.exists()
        if report["passed"]:
            if report["baseline_written"]:
                logger.info("[budget_guard_bootstrap] baseline state initialized")
            else:
                logger.info("[budget_guard_bootstrap] existing state reused")
        else:
            logger.warning("[budget_guard_bootstrap] state file missing after bootstrap")
    except Exception as exc:
        report["passed"] = False
        report["error"] = f"{type(exc).__name__}:{exc}"
        logger.error("[budget_guard_bootstrap] bootstrap error: %s", exc)
    return report
