from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from system.config import get_config
from system.execution_backend.runtime_policy import (
    resolve_os_sandbox_runtime_policy,
    resolve_worktree_fallback_backend,
)
from system.sandbox_context import normalize_execution_backend


logger = logging.getLogger(__name__)
_BOXLITE_INSTALL_LOCK = threading.Lock()
_BOXLITE_INSTALL_CACHE: Dict[Tuple[str, str], Tuple[bool, str]] = {}
_BOXLITE_READINESS_LOCK = threading.Lock()
_BOXLITE_READINESS_CACHE: Dict[Tuple[str, ...], Tuple[bool, str]] = {}
_BOXLITE_STATE_LOCK = threading.Lock()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_int(value: Any, default: int, *, minimum: int | None = None) -> int:
    try:
        resolved = int(value)
    except (TypeError, ValueError):
        resolved = int(default)
    if minimum is not None:
        resolved = max(int(minimum), resolved)
    return resolved


def _safe_float(value: Any, default: float, *, minimum: float | None = None) -> float:
    try:
        resolved = float(value)
    except (TypeError, ValueError):
        resolved = float(default)
    if minimum is not None:
        resolved = max(float(minimum), resolved)
    return resolved


@dataclass(frozen=True)
class BoxLiteRuntimeProfile:
    name: str = "default"
    asset_name: str = "embla_py311_default"
    image: str = "embla/boxlite-runtime:py311"
    image_candidates: Tuple[str, ...] = ("embla/boxlite-runtime:py311", "python:slim")
    working_dir: str = "/workspace"
    cpus: int = 2
    memory_mib: int = 1024
    security_preset: str = "maximum"
    network_enabled: bool = False
    python_cmd: str = "python"
    prewarm_command: Tuple[str, ...] = ("python", "-V")


@dataclass(frozen=True)
class BoxLiteRuntimeSettings:
    enabled: bool = True
    mode: str = "required"
    provider: str = "sdk"
    base_url: str = ""
    runtime_profile: str = "default"
    runtime_profiles: Mapping[str, BoxLiteRuntimeProfile] | None = None
    runtime_state_file: str = "scratch/runtime/boxlite_runtime_assets.json"
    install_prefetch_enabled: bool = True
    local_image_build_enabled: bool = True
    local_image_builder: str = "auto"
    local_image_context_dir: str = "system/boxlite/runtime_image"
    local_image_dockerfile: str = "Dockerfile"
    auto_reconcile_enabled: bool = True
    reconcile_interval_seconds: int = 900
    reconcile_stale_after_seconds: int = 43200
    core_ensure_before_spawn_enabled: bool = True
    asset_name: str = "embla_py311_default"
    image: str = "embla/boxlite-runtime:py311"
    image_candidates: Tuple[str, ...] = ("embla/boxlite-runtime:py311", "python:slim")
    working_dir: str = "/workspace"
    cpus: int = 2
    memory_mib: int = 1024
    auto_remove: bool = True
    security_preset: str = "maximum"
    network_enabled: bool = False
    python_cmd: str = "python"
    prewarm_command: Tuple[str, ...] = ("python", "-V")
    auto_install_sdk: bool = True
    install_timeout_seconds: int = 300
    sdk_package_spec: str = "boxlite"
    ensure_timeout_seconds: int = 45
    startup_prewarm_enabled: bool = True
    startup_prewarm_timeout_seconds: int = 45


@dataclass(frozen=True)
class BoxLiteRuntimeStatus:
    available: bool
    reason: str = ""
    mode: str = "required"
    provider: str = "sdk"
    working_dir: str = "/workspace"
    image: str = "embla/boxlite-runtime:py311"
    runtime_profile: str = "default"
    asset_name: str = "embla_py311_default"


def _resolve_project_root(project_root: str | Path | None = None) -> Path:
    if project_root:
        return Path(project_root).resolve(strict=False)
    return Path(__file__).resolve().parents[2]


def _resolve_runtime_profile_name(runtime: BoxLiteRuntimeSettings, profile_name: str | None = None) -> str:
    requested = str(profile_name or runtime.runtime_profile or "default").strip() or "default"
    profiles = runtime.runtime_profiles or {}
    if requested in profiles:
        return requested
    if "default" in profiles:
        return "default"
    return requested


def _resolve_boxlite_runtime_profile(
    runtime: BoxLiteRuntimeSettings,
    *,
    profile_name: str | None = None,
) -> BoxLiteRuntimeProfile:
    resolved_name = _resolve_runtime_profile_name(runtime, profile_name)
    profiles = runtime.runtime_profiles or {}
    profile = profiles.get(resolved_name)
    if isinstance(profile, BoxLiteRuntimeProfile):
        return profile
    return BoxLiteRuntimeProfile(
        name=resolved_name,
        asset_name=str(runtime.asset_name or "embla_py311_default").strip() or "embla_py311_default",
        image=str(runtime.image or "embla/boxlite-runtime:py311").strip() or "embla/boxlite-runtime:py311",
        image_candidates=tuple(runtime.image_candidates or ("embla/boxlite-runtime:py311", "python:slim")) or ("embla/boxlite-runtime:py311", "python:slim"),
        working_dir=str(runtime.working_dir or "/workspace").strip() or "/workspace",
        cpus=max(1, int(runtime.cpus)),
        memory_mib=max(128, int(runtime.memory_mib)),
        security_preset=str(runtime.security_preset or "maximum").strip() or "maximum",
        network_enabled=bool(runtime.network_enabled),
        python_cmd=str(runtime.python_cmd or "python").strip() or "python",
        prewarm_command=tuple(runtime.prewarm_command or ("python", "-V")) or ("python", "-V"),
    )


def _settings_for_runtime_profile(
    runtime: BoxLiteRuntimeSettings,
    *,
    profile_name: str | None = None,
) -> BoxLiteRuntimeSettings:
    profile = _resolve_boxlite_runtime_profile(runtime, profile_name=profile_name)
    return replace(
        runtime,
        runtime_profile=str(profile.name or "default").strip() or "default",
        asset_name=str(profile.asset_name or "embla_py311_default").strip() or "embla_py311_default",
        image=str(profile.image or "embla/boxlite-runtime:py311").strip() or "embla/boxlite-runtime:py311",
        image_candidates=tuple(profile.image_candidates or (profile.image, "python:slim")) or (profile.image, "python:slim"),
        working_dir=str(profile.working_dir or "/workspace").strip() or "/workspace",
        cpus=max(1, int(profile.cpus)),
        memory_mib=max(128, int(profile.memory_mib)),
        security_preset=str(profile.security_preset or "maximum").strip() or "maximum",
        network_enabled=bool(profile.network_enabled),
        python_cmd=str(profile.python_cmd or "python").strip() or "python",
        prewarm_command=tuple(profile.prewarm_command or ("python", "-V")) or ("python", "-V"),
    )


def _iter_runtime_candidate_settings(runtime: BoxLiteRuntimeSettings) -> List[BoxLiteRuntimeSettings]:
    candidates: List[str] = []
    for value in [runtime.image, *(tuple(runtime.image_candidates or ()) or ())]:
        text = str(value or "").strip()
        if text and text not in candidates:
            candidates.append(text)
    if not candidates:
        candidates.append("python:slim")
    return [replace(runtime, image=image, image_candidates=tuple(candidates)) for image in candidates]


def _resolve_runtime_state_file(runtime: BoxLiteRuntimeSettings, *, project_root: str | Path | None = None) -> Path:
    root = _resolve_project_root(project_root)
    raw = str(getattr(runtime, "runtime_state_file", "") or "scratch/runtime/boxlite_runtime_assets.json").strip()
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = root / candidate
    return candidate


def _resolve_local_image_context_dir(runtime: BoxLiteRuntimeSettings, *, project_root: str | Path | None = None) -> Path:
    root = _resolve_project_root(project_root)
    raw = str(getattr(runtime, "local_image_context_dir", "") or "system/boxlite/runtime_image").strip()
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = root / candidate
    return candidate


def _resolve_local_image_dockerfile(runtime: BoxLiteRuntimeSettings, *, project_root: str | Path | None = None) -> Path:
    context_dir = _resolve_local_image_context_dir(runtime, project_root=project_root)
    raw = str(getattr(runtime, "local_image_dockerfile", "") or "Dockerfile").strip()
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = context_dir / candidate
    return candidate


def _detect_container_builder(preferred: str = "auto") -> List[str] | None:
    requested = str(preferred or "auto").strip().lower() or "auto"
    candidates = [requested] if requested in {"docker", "podman"} else ["docker", "podman"]
    for candidate in candidates:
        binary = shutil.which(candidate)
        if not binary:
            continue
        try:
            subprocess.run([binary, "version"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
            return [binary]
        except Exception:
            continue
    return None


def _load_runtime_asset_state(runtime: BoxLiteRuntimeSettings, *, project_root: str | Path | None = None) -> Dict[str, Any]:
    state_file = _resolve_runtime_state_file(runtime, project_root=project_root)
    if not state_file.exists():
        return {
            "generated_at": "",
            "state_file": str(state_file),
            "active_profile": _resolve_runtime_profile_name(runtime),
            "profiles": {},
        }
    try:
        loaded = json.loads(state_file.read_text(encoding="utf-8"))
    except Exception:
        return {
            "generated_at": "",
            "state_file": str(state_file),
            "active_profile": _resolve_runtime_profile_name(runtime),
            "profiles": {},
        }
    if not isinstance(loaded, dict):
        loaded = {}
    profiles = loaded.get("profiles")
    if not isinstance(profiles, dict):
        profiles = {}
    return {
        "generated_at": str(loaded.get("generated_at") or ""),
        "state_file": str(state_file),
        "active_profile": str(loaded.get("active_profile") or _resolve_runtime_profile_name(runtime)),
        "profiles": profiles,
    }


def _write_runtime_asset_state(
    runtime: BoxLiteRuntimeSettings,
    payload: Mapping[str, Any],
    *,
    project_root: str | Path | None = None,
) -> None:
    state_file = _resolve_runtime_state_file(runtime, project_root=project_root)
    state_file.parent.mkdir(parents=True, exist_ok=True)
    normalized = {
        "generated_at": str(payload.get("generated_at") or _utc_now_iso()),
        "active_profile": str(payload.get("active_profile") or _resolve_runtime_profile_name(runtime)),
        "profiles": dict(payload.get("profiles") or {}),
    }
    state_file.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")


def _is_embla_runtime_image(image: str) -> bool:
    text = str(image or "").strip().lower()
    return text.startswith("embla/")


def _entry_age_seconds(timestamp_text: str) -> float | None:
    text = str(timestamp_text or "").strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds())


def _summarize_profile_entry(
    runtime: BoxLiteRuntimeSettings,
    entry: Mapping[str, Any],
    *,
    profile_name: str,
) -> Dict[str, Any]:
    profile = _resolve_boxlite_runtime_profile(runtime, profile_name=profile_name)
    last_ready_at = str(entry.get("last_ready_at") or "")
    last_checked_at = str(entry.get("last_checked_at") or "")
    last_error = str(entry.get("last_error") or "")
    last_reason = str(entry.get("last_reason") or "")
    status = str(entry.get("status") or "").strip().lower()
    stale_after_seconds = max(300, int(getattr(runtime, "reconcile_stale_after_seconds", 43200) or 43200))
    ready_age_seconds = _entry_age_seconds(last_ready_at)

    if not status:
        if last_error:
            status = "failed"
        elif last_ready_at:
            status = "ready"
        else:
            status = "missing"
    if status == "ready" and ready_age_seconds is not None and ready_age_seconds > stale_after_seconds:
        status = "stale"

    if status == "ready":
        severity = "ok"
        reason_code = "BOXLITE_RUNTIME_READY"
        reason_text = "BoxLite runtime profile is ready."
    elif status == "stale":
        severity = "warning"
        reason_code = "BOXLITE_RUNTIME_STALE"
        reason_text = "BoxLite runtime profile is stale and should be reconciled."
    elif status in {"failed", "error"}:
        severity = "critical" if str(runtime.mode or "required") == "required" else "warning"
        reason_code = "BOXLITE_RUNTIME_FAILED"
        reason_text = last_error or last_reason or "BoxLite runtime profile ensure failed."
    elif status in {"refreshing", "bootstrapping"}:
        severity = "warning"
        reason_code = "BOXLITE_RUNTIME_REFRESHING"
        reason_text = "BoxLite runtime profile is refreshing."
    elif status == "disabled":
        severity = "ok"
        reason_code = "BOXLITE_RUNTIME_DISABLED"
        reason_text = "BoxLite runtime is disabled."
    else:
        severity = "unknown"
        reason_code = "BOXLITE_RUNTIME_UNOBSERVED"
        reason_text = "BoxLite runtime profile has not been ensured yet."

    return {
        "profile": str(profile.name or profile_name),
        "asset_name": str(entry.get("asset_name") or profile.asset_name),
        "status": status,
        "severity": severity,
        "reason_code": reason_code,
        "reason_text": reason_text,
        "image": str(entry.get("resolved_image") or entry.get("image") or profile.image or runtime.image),
        "requested_image": str(entry.get("requested_image") or profile.image or runtime.image),
        "resolved_image": str(entry.get("resolved_image") or entry.get("image") or profile.image or runtime.image),
        "image_candidates": list(entry.get("image_candidates") or list(profile.image_candidates)),
        "working_dir": str(entry.get("working_dir") or profile.working_dir or runtime.working_dir),
        "cpus": _safe_int(entry.get("cpus"), profile.cpus, minimum=1),
        "memory_mib": _safe_int(entry.get("memory_mib"), profile.memory_mib, minimum=128),
        "network_enabled": bool(entry.get("network_enabled", profile.network_enabled)),
        "prewarm_command": list(entry.get("prewarm_command") or list(profile.prewarm_command)),
        "last_checked_at": last_checked_at,
        "last_ready_at": last_ready_at,
        "last_error": last_error,
        "last_reason": last_reason,
        "last_action": str(entry.get("last_action") or ""),
        "ready_age_seconds": ready_age_seconds,
        "stale_after_seconds": stale_after_seconds,
    }

def build_box_session_name(session_id: str) -> str:
    token = str(session_id or "session").strip().replace(" ", "-") or "session"
    return f"embla-{token}"


def _resolve_boxlite_python_executable() -> Path:
    project_root = Path(__file__).resolve().parents[2]
    candidates = [
        project_root / ".venv" / "bin" / "python",
        project_root / ".venv" / "Scripts" / "python.exe",
        Path(sys.executable),
    ]
    for candidate in candidates:
        if candidate and candidate.exists():
            return candidate.absolute()
    return Path(sys.executable).absolute()


def _truncate_reason(text: str, limit: int = 300) -> str:
    normalized = str(text or "").strip().replace("\n", " | ")
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 14)] + "...(truncated)"


def _is_missing_boxlite_module(exc: Exception) -> bool:
    if isinstance(exc, ModuleNotFoundError) and getattr(exc, "name", "") == "boxlite":
        return True
    return "No module named 'boxlite'" in str(exc)


def _resolve_boxlite_network_mode(enabled: bool) -> str:
    return "bridge" if bool(enabled) else "none"


def _boxlite_readiness_cache_key(runtime: BoxLiteRuntimeSettings) -> Tuple[str, ...]:
    return (
        str(runtime.runtime_profile or "default").strip() or "default",
        str(runtime.provider or "sdk").strip().lower() or "sdk",
        str(runtime.base_url or "").strip(),
        str(runtime.image or "").strip() or "python:slim",
        str(runtime.working_dir or "/workspace").strip() or "/workspace",
        str(int(runtime.cpus)),
        str(int(runtime.memory_mib)),
        str(bool(runtime.auto_remove)).lower(),
        str(runtime.security_preset or "maximum").strip().lower() or "maximum",
        str(bool(runtime.network_enabled)).lower(),
        str(runtime.python_cmd or "python").strip() or "python",
        "|".join(str(item or "").strip() for item in tuple(runtime.prewarm_command or ("python", "-V"))),
        str(int(getattr(runtime, "ensure_timeout_seconds", 45) or 45)),
        str(int(getattr(runtime, "startup_prewarm_timeout_seconds", 45) or 45)),
    )


def _boxlite_reason(code: str, detail: Any = "") -> str:
    normalized_code = str(code or "boxlite_runtime_error").strip() or "boxlite_runtime_error"
    detail_text = _truncate_reason(str(detail or "").strip(), 240)
    if not detail_text:
        return normalized_code
    return f"{normalized_code}:{detail_text}"


def _classify_boxlite_runtime_error(error: Any) -> str:
    text = str(error or "").strip()
    lowered = text.lower()
    if not lowered:
        return "boxlite_runtime_error"
    if (
        "panicexception" in lowered
        or "pyo3_runtime.panicexception" in lowered
        or "poisonerror" in lowered
        or "wouldblock" in lowered
        or "can't start new thread" in lowered
        or "cannot start new thread" in lowered
        or "failed to spawn signal handler thread" in lowered
        or "failed to spawn tracing-appender worker thread" in lowered
    ):
        return _boxlite_reason("boxlite_runtime_panic", text)
    if "failed to acquire runtime lock" in lowered or "another boxliteruntime is already using directory" in lowered:
        return _boxlite_reason("boxlite_runtime_lock_conflict", text)
    if (
        "failed to pull image" in lowered
        or "failed to pull manifest" in lowered
        or "error sending request for url" in lowered
        or "index.docker.io" in lowered
        or "manifest unknown" in lowered
        or "name unknown" in lowered
    ):
        return _boxlite_reason("boxlite_image_pull_failed", text)
    if "network is unreachable" in lowered or "temporary failure in name resolution" in lowered or "connection refused" in lowered:
        return _boxlite_reason("boxlite_image_pull_network_failed", text)
    if "timed out" in lowered or "timeout" in lowered:
        return _boxlite_reason("boxlite_runtime_timeout", text)
    if lowered.startswith("boxlite_"):
        return _truncate_reason(text, 280)
    return _boxlite_reason("boxlite_runtime_error", text)


def _bootstrap_boxlite_sdk(runtime: BoxLiteRuntimeSettings) -> Tuple[bool, str]:
    if not bool(getattr(runtime, "auto_install_sdk", True)):
        return False, "boxlite_sdk_auto_install_disabled"

    package_spec = str(getattr(runtime, "sdk_package_spec", "boxlite") or "boxlite").strip() or "boxlite"
    python_executable = _resolve_boxlite_python_executable()
    cache_key = (str(python_executable), package_spec)
    cached = _BOXLITE_INSTALL_CACHE.get(cache_key)
    if cached is not None:
        return cached

    cmd = [
        str(python_executable),
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        package_spec,
    ]
    timeout_seconds = max(10, int(getattr(runtime, "install_timeout_seconds", 300) or 300))

    with _BOXLITE_INSTALL_LOCK:
        cached = _BOXLITE_INSTALL_CACHE.get(cache_key)
        if cached is not None:
            return cached
        logger.info("[boxlite_bootstrap] installing %s via %s", package_spec, python_executable)
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired:
            result = (False, f"boxlite_sdk_auto_install_timeout:{timeout_seconds}s")
        except Exception as exc:
            result = (False, f"boxlite_sdk_auto_install_failed:{exc}")
        else:
            if int(proc.returncode) == 0:
                importlib.invalidate_caches()
                result = (True, "")
            else:
                detail = _truncate_reason(proc.stderr or proc.stdout or "")
                suffix = f": {detail}" if detail else ""
                result = (False, f"boxlite_sdk_auto_install_failed:exit_code={proc.returncode}{suffix}")
        _BOXLITE_INSTALL_CACHE[cache_key] = result
        return result


def _run_async_sync(coro) -> tuple[bool, str]:
    def _normalize_result(value: Any) -> tuple[bool, str]:
        if isinstance(value, tuple):
            ok = bool(value[0]) if len(value) >= 1 else True
            reason = "" if len(value) < 2 or value[1] is None else str(value[1])
            return ok, reason
        if value is None:
            return True, ""
        if isinstance(value, bool):
            return value, ""
        return True, str(value)

    def _close_coro_quietly(target: Any) -> None:
        close = getattr(target, "close", None)
        if callable(close):
            try:
                close()
            except BaseException:
                pass

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        loop_running = False
    else:
        loop_running = True

    if not loop_running:
        try:
            return _normalize_result(asyncio.run(coro))
        except BaseException as exc:
            return False, _classify_boxlite_runtime_error(exc)

    result: dict[str, Any] = {}

    def _worker() -> None:
        try:
            result["value"] = asyncio.run(coro)
        except BaseException as exc:
            result["error"] = exc

    try:
        thread = threading.Thread(target=_worker, name="embla-boxlite-teardown", daemon=True)
        thread.start()
    except BaseException as exc:
        _close_coro_quietly(coro)
        return False, _classify_boxlite_runtime_error(exc)

    try:
        thread.join()
    except BaseException as exc:
        return False, _classify_boxlite_runtime_error(exc)

    if "error" in result:
        return False, _classify_boxlite_runtime_error(result["error"])
    if "value" not in result:
        return False, "boxlite_async_bridge_failed:no_result"
    return _normalize_result(result["value"])


def _running_in_event_loop() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


def _get_cached_boxlite_runtime_readiness_status(
    settings: Optional[BoxLiteRuntimeSettings] = None,
    *,
    profile_name: str | None = None,
) -> BoxLiteRuntimeStatus | None:
    runtime = _settings_for_runtime_profile(settings or load_boxlite_runtime_settings(), profile_name=profile_name)
    candidate_runtimes = _iter_runtime_candidate_settings(runtime)
    for candidate_runtime in candidate_runtimes:
        cache_key = _boxlite_readiness_cache_key(candidate_runtime)
        with _BOXLITE_READINESS_LOCK:
            cached = _BOXLITE_READINESS_CACHE.get(cache_key)
        if cached is None:
            continue
        ok, reason = cached
        return BoxLiteRuntimeStatus(
            bool(ok),
            str(reason or ""),
            candidate_runtime.mode,
            candidate_runtime.provider,
            candidate_runtime.working_dir,
            candidate_runtime.image,
            candidate_runtime.runtime_profile,
            candidate_runtime.asset_name,
        )
    return None


def build_boxlite_volume_mounts(
    *,
    workspace_host_root: str,
    working_dir: str = "/workspace",
    project_root: str = "",
) -> List[tuple[str, str, bool]]:
    workspace_root = Path(str(workspace_host_root or "")).resolve(strict=False)
    if not str(workspace_root).strip():
        raise RuntimeError("workspace_host_root is required for boxlite execution")

    resolved_working_dir = str(working_dir or "/workspace").strip() or "/workspace"
    mounts: List[tuple[str, str, bool]] = []
    seen: set[tuple[str, str]] = set()

    def _add_mount(host_path: Path, guest_path: str, *, read_only: bool) -> None:
        host_text = str(host_path.resolve(strict=False)).strip()
        guest_text = str(guest_path or "").strip()
        if not host_text or not guest_text:
            return
        key = (host_text, guest_text)
        if key in seen:
            return
        seen.add(key)
        mounts.append((host_text, guest_text, bool(read_only)))

    _add_mount(workspace_root, resolved_working_dir, read_only=False)

    project_root_path = Path(str(project_root or "")).resolve(strict=False) if str(project_root or "").strip() else None
    if project_root_path is not None:
        _add_mount(project_root_path, str(project_root_path), read_only=True)
        venv_path = project_root_path / ".venv"
        if venv_path.exists():
            workspace_venv_guest = resolved_working_dir.rstrip("/") + "/.venv"
            _add_mount(venv_path, workspace_venv_guest, read_only=True)

    return mounts


class BoxLiteManager:
    def __init__(self, settings: Optional[BoxLiteRuntimeSettings] = None) -> None:
        self.settings = settings or load_boxlite_runtime_settings()
        self._runtime = None
        self._boxes: Dict[str, Any] = {}

    def runtime_settings_for_profile(self, execution_profile: str | None = None) -> BoxLiteRuntimeSettings:
        return _settings_for_runtime_profile(self.settings, profile_name=execution_profile)

    def availability(self, *, execution_profile: str | None = None) -> BoxLiteRuntimeStatus:
        return probe_boxlite_runtime(self.runtime_settings_for_profile(execution_profile))

    async def ensure_box(
        self,
        *,
        box_name: str,
        workspace_host_root: str,
        execution_profile: str = "default",
        box_profile: str = "default",
        working_dir: str | None = None,
        project_root: str | None = None,
    ) -> tuple[Any, bool]:
        del box_profile
        runtime = self.runtime_settings_for_profile(execution_profile)
        status = probe_boxlite_runtime_readiness(runtime, project_root=project_root, force=False)
        if not status.available:
            raise RuntimeError(status.reason or "boxlite runtime unavailable")
        if str(getattr(status, "image", "") or "").strip():
            runtime = replace(runtime, image=str(getattr(status, "image", "") or runtime.image).strip() or runtime.image)
        if runtime.provider != "sdk":
            raise RuntimeError(f"unsupported boxlite provider: {runtime.provider}")

        workspace_root = Path(str(workspace_host_root or "")).resolve(strict=False)
        if not str(workspace_root).strip():
            raise RuntimeError("workspace_host_root is required for boxlite execution")

        import boxlite

        if self._runtime is None:
            try:
                self._runtime = boxlite.Boxlite.default()
            except BaseException as exc:
                raise RuntimeError(_classify_boxlite_runtime_error(exc)) from exc

        security = getattr(boxlite.SecurityOptions, str(runtime.security_preset or "maximum"), None)
        if callable(security):
            security = security()
        else:
            security = boxlite.SecurityOptions.maximum()
        try:
            security.network_enabled = bool(runtime.network_enabled)
        except Exception:
            pass

        resolved_working_dir = str(working_dir or runtime.working_dir or "/workspace")
        volumes = build_boxlite_volume_mounts(
            workspace_host_root=str(workspace_root),
            working_dir=resolved_working_dir,
            project_root=str(project_root or ""),
        )

        option_kwargs = {
            "image": runtime.image,
            "cpus": int(runtime.cpus),
            "memory_mib": int(runtime.memory_mib),
            "working_dir": resolved_working_dir,
            "auto_remove": bool(runtime.auto_remove),
            "volumes": volumes,
        }
        try:
            supported = set(inspect.signature(boxlite.BoxOptions).parameters)
        except Exception:
            supported = set()
        if "security" in supported:
            option_kwargs["security"] = security
        if "network" in supported:
            option_kwargs["network"] = _resolve_boxlite_network_mode(bool(runtime.network_enabled))
        options = boxlite.BoxOptions(**option_kwargs)
        ensure_timeout_seconds = max(5.0, float(getattr(runtime, "ensure_timeout_seconds", 45) or 45))

        async def _open_box() -> tuple[Any, bool]:
            box, created = await self._runtime.get_or_create(options, name=box_name)
            await box.__aenter__()
            return box, bool(created)

        try:
            box, created = await asyncio.wait_for(_open_box(), timeout=ensure_timeout_seconds)
        except asyncio.TimeoutError as exc:
            raise RuntimeError(_boxlite_reason("boxlite_ensure_timeout", f"{ensure_timeout_seconds:.0f}s")) from exc
        except BaseException as exc:
            raise RuntimeError(_classify_boxlite_runtime_error(exc)) from exc
        self._boxes[box_name] = box
        return box, created

    async def exec_in_box(
        self,
        *,
        box_name: str,
        workspace_host_root: str,
        execution_profile: str = "default",
        command: str,
        args: Optional[list[str]] = None,
        env: Optional[Dict[str, str]] = None,
        working_dir: str | None = None,
        timeout_seconds: float | None = None,
        project_root: str | None = None,
    ) -> Dict[str, Any]:
        try:
            box, created = await self.ensure_box(
                box_name=box_name,
                workspace_host_root=workspace_host_root,
                execution_profile=execution_profile,
                working_dir=working_dir,
                project_root=project_root,
            )
        except BaseException as exc:
            raise RuntimeError(_classify_boxlite_runtime_error(exc)) from exc
        del created
        try:
            execution = await box.exec(command, args or None, list((env or {}).items()) if env else None)
        except BaseException as exc:
            raise RuntimeError(_classify_boxlite_runtime_error(exc)) from exc
        try:
            result = await asyncio.wait_for(execution.wait(), timeout=timeout_seconds or 30)
        except asyncio.TimeoutError:
            try:
                await execution.kill()
            except BaseException:
                pass
            raise RuntimeError(_boxlite_reason("boxlite_exec_timeout", f"{timeout_seconds or 30}s")) from None
        except BaseException as exc:
            raise RuntimeError(_classify_boxlite_runtime_error(exc)) from exc
        return {
            "exit_code": int(getattr(result, "exit_code", 1)),
            "stdout": str(getattr(result, "stdout", "") or ""),
            "stderr": str(getattr(result, "stderr", "") or ""),
            "box_id": str(getattr(box, "id", "") or ""),
            "box_name": str(box_name or "").strip(),
        }

    async def teardown_box(self, box_ref: str, *, allow_runtime_init: bool = True) -> tuple[bool, str]:
        box_ref_text = str(box_ref or "").strip()
        if not box_ref_text:
            return True, ""

        runtime = self._runtime
        box = self._boxes.pop(box_ref_text, None)
        for key, cached in list(self._boxes.items()):
            if str(getattr(cached, "id", "") or "").strip() == box_ref_text:
                if box is None:
                    box = cached
                self._boxes.pop(key, None)

        if self.settings.provider != "sdk":
            return False, f"unsupported boxlite provider for teardown: {self.settings.provider}"

        try:
            if runtime is None and allow_runtime_init:
                status = self.availability()
                if not status.available:
                    return False, status.reason or "boxlite runtime unavailable"
                import boxlite
                runtime = boxlite.Boxlite.default()

            if box is None and runtime is not None:
                box = await runtime.get(box_ref_text)

            if box is not None:
                try:
                    await box.__aexit__(None, None, None)
                except BaseException:
                    pass

            remove_error: BaseException | None = None
            if runtime is not None:
                try:
                    await runtime.remove(box_ref_text, True)
                    return True, ""
                except BaseException as exc:
                    remove_error = exc

            if box is not None:
                remove_box = getattr(box, "remove", None)
                if callable(remove_box):
                    try:
                        await remove_box()
                        return True, ""
                    except BaseException as exc:
                        remove_error = exc

            if remove_error is not None:
                return False, _classify_boxlite_runtime_error(remove_error)
            return True, ""
        except BaseException as exc:  # pragma: no cover - depends on external runtime
            return False, _classify_boxlite_runtime_error(exc)


def _normalize_mode(raw: Any) -> str:
    text = str(raw or "required").strip().lower()
    aliases = {
        "": "required",
        "on": "required",
        "off": "disabled",
        "strict": "required",
    }
    text = aliases.get(text, text)
    if text not in {"disabled", "preferred", "required"}:
        raise ValueError(f"unsupported boxlite mode: {raw}")
    return text


def _load_runtime_profiles_from_config(boxlite_cfg: Any) -> Dict[str, BoxLiteRuntimeProfile]:
    fallback_profile = BoxLiteRuntimeProfile(
        name="default",
        asset_name=str(getattr(boxlite_cfg, "asset_name", "embla_py311_default") or "embla_py311_default").strip() or "embla_py311_default",
        image=str(getattr(boxlite_cfg, "image", "embla/boxlite-runtime:py311") or "embla/boxlite-runtime:py311").strip() or "embla/boxlite-runtime:py311",
        image_candidates=tuple(
            str(item or "").strip()
            for item in (
                getattr(boxlite_cfg, "image_candidates", None)
                or (getattr(boxlite_cfg, "image", "embla/boxlite-runtime:py311"), "python:slim")
            )
            if str(item or "").strip()
        )
        or ("embla/boxlite-runtime:py311", "python:slim"),
        working_dir=str(getattr(boxlite_cfg, "working_dir", "/workspace") or "/workspace").strip() or "/workspace",
        cpus=max(1, int(getattr(boxlite_cfg, "cpus", 2) or 2)),
        memory_mib=max(128, int(getattr(boxlite_cfg, "memory_mib", 1024) or 1024)),
        security_preset=str(getattr(boxlite_cfg, "security_preset", "maximum") or "maximum").strip() or "maximum",
        network_enabled=bool(getattr(boxlite_cfg, "network_enabled", False)),
        python_cmd="python",
        prewarm_command=("python", "-V"),
    )

    loaded_profiles: Dict[str, BoxLiteRuntimeProfile] = {"default": fallback_profile}
    raw_profiles = getattr(boxlite_cfg, "runtime_profiles", None)
    if isinstance(raw_profiles, Mapping):
        iterable = raw_profiles.items()
    elif isinstance(raw_profiles, dict):
        iterable = raw_profiles.items()
    else:
        iterable = []

    for raw_name, raw_profile in iterable:
        name = str(raw_name or "").strip() or "default"
        profile_source = raw_profile
        if not isinstance(profile_source, Mapping):
            profile_source = getattr(profile_source, "model_dump", lambda: {})()
        if not isinstance(profile_source, Mapping):
            profile_source = {}
        prewarm_command = profile_source.get("prewarm_command") if isinstance(profile_source, Mapping) else None
        if not isinstance(prewarm_command, Sequence) or isinstance(prewarm_command, (str, bytes)):
            prewarm_command = None
        image_candidates = profile_source.get("image_candidates") if isinstance(profile_source, Mapping) else None
        if not isinstance(image_candidates, Sequence) or isinstance(image_candidates, (str, bytes)):
            image_candidates = None
        loaded_profiles[name] = BoxLiteRuntimeProfile(
            name=name,
            asset_name=str(profile_source.get("asset_name") or fallback_profile.asset_name).strip() or fallback_profile.asset_name,
            image=str(profile_source.get("image") or fallback_profile.image).strip() or fallback_profile.image,
            image_candidates=tuple(
                str(item or "").strip()
                for item in (image_candidates or fallback_profile.image_candidates)
                if str(item or "").strip()
            )
            or fallback_profile.image_candidates,
            working_dir=str(profile_source.get("working_dir") or fallback_profile.working_dir).strip() or fallback_profile.working_dir,
            cpus=max(1, int(profile_source.get("cpus") or fallback_profile.cpus)),
            memory_mib=max(128, int(profile_source.get("memory_mib") or fallback_profile.memory_mib)),
            security_preset=str(profile_source.get("security_preset") or fallback_profile.security_preset).strip() or fallback_profile.security_preset,
            network_enabled=bool(profile_source.get("network_enabled", fallback_profile.network_enabled)),
            python_cmd=str(profile_source.get("python_cmd") or fallback_profile.python_cmd).strip() or fallback_profile.python_cmd,
            prewarm_command=tuple(str(item or "").strip() for item in (prewarm_command or fallback_profile.prewarm_command) if str(item or "").strip()) or fallback_profile.prewarm_command,
        )
    return loaded_profiles


def load_boxlite_runtime_settings() -> BoxLiteRuntimeSettings:
    cfg = get_config()
    sandbox_cfg = getattr(cfg, "sandbox", None)
    boxlite_cfg = getattr(sandbox_cfg, "boxlite", None)
    if boxlite_cfg is None:
        return BoxLiteRuntimeSettings()
    profiles = _load_runtime_profiles_from_config(boxlite_cfg)
    runtime_profile = str(getattr(boxlite_cfg, "runtime_profile", "default") or "default").strip() or "default"
    if runtime_profile not in profiles:
        runtime_profile = "default" if "default" in profiles else next(iter(profiles.keys()), "default")
    active_profile = profiles.get(runtime_profile) or BoxLiteRuntimeProfile(name=runtime_profile)
    return BoxLiteRuntimeSettings(
        enabled=bool(getattr(boxlite_cfg, "enabled", False)),
        mode=_normalize_mode(getattr(boxlite_cfg, "mode", "required")),
        provider=str(getattr(boxlite_cfg, "provider", "sdk") or "sdk").strip() or "sdk",
        base_url=str(getattr(boxlite_cfg, "base_url", "") or "").strip(),
        runtime_profile=runtime_profile,
        runtime_profiles=profiles,
        runtime_state_file=str(
            getattr(boxlite_cfg, "runtime_state_file", "scratch/runtime/boxlite_runtime_assets.json")
            or "scratch/runtime/boxlite_runtime_assets.json"
        ).strip()
        or "scratch/runtime/boxlite_runtime_assets.json",
        install_prefetch_enabled=bool(getattr(boxlite_cfg, "install_prefetch_enabled", True)),
        local_image_build_enabled=bool(getattr(boxlite_cfg, "local_image_build_enabled", True)),
        local_image_builder=str(getattr(boxlite_cfg, "local_image_builder", "auto") or "auto").strip() or "auto",
        local_image_context_dir=str(getattr(boxlite_cfg, "local_image_context_dir", "system/boxlite/runtime_image") or "system/boxlite/runtime_image").strip() or "system/boxlite/runtime_image",
        local_image_dockerfile=str(getattr(boxlite_cfg, "local_image_dockerfile", "Dockerfile") or "Dockerfile").strip() or "Dockerfile",
        auto_reconcile_enabled=bool(getattr(boxlite_cfg, "auto_reconcile_enabled", True)),
        reconcile_interval_seconds=max(60, int(getattr(boxlite_cfg, "reconcile_interval_seconds", 900) or 900)),
        reconcile_stale_after_seconds=max(300, int(getattr(boxlite_cfg, "reconcile_stale_after_seconds", 43200) or 43200)),
        core_ensure_before_spawn_enabled=bool(getattr(boxlite_cfg, "core_ensure_before_spawn_enabled", True)),
        asset_name=str(active_profile.asset_name or "embla_py311_default").strip() or "embla_py311_default",
        image=str(active_profile.image or "embla/boxlite-runtime:py311").strip() or "embla/boxlite-runtime:py311",
        image_candidates=tuple(active_profile.image_candidates or (active_profile.image, "python:slim")) or (active_profile.image, "python:slim"),
        working_dir=str(active_profile.working_dir or "/workspace").strip() or "/workspace",
        cpus=max(1, int(active_profile.cpus)),
        memory_mib=max(128, int(active_profile.memory_mib)),
        auto_remove=bool(getattr(boxlite_cfg, "auto_remove", True)),
        security_preset=str(active_profile.security_preset or "maximum").strip() or "maximum",
        network_enabled=bool(active_profile.network_enabled),
        python_cmd=str(active_profile.python_cmd or "python").strip() or "python",
        prewarm_command=tuple(active_profile.prewarm_command or ("python", "-V")) or ("python", "-V"),
        auto_install_sdk=bool(getattr(boxlite_cfg, "auto_install_sdk", True)),
        install_timeout_seconds=max(10, int(getattr(boxlite_cfg, "install_timeout_seconds", 300) or 300)),
        sdk_package_spec=str(getattr(boxlite_cfg, "sdk_package_spec", "boxlite") or "boxlite").strip() or "boxlite",
        ensure_timeout_seconds=max(5, int(getattr(boxlite_cfg, "ensure_timeout_seconds", 45) or 45)),
        startup_prewarm_enabled=bool(getattr(boxlite_cfg, "startup_prewarm_enabled", True)),
        startup_prewarm_timeout_seconds=max(5, int(getattr(boxlite_cfg, "startup_prewarm_timeout_seconds", 45) or 45)),
    )


def probe_boxlite_runtime(
    settings: Optional[BoxLiteRuntimeSettings] = None,
    *,
    profile_name: str | None = None,
) -> BoxLiteRuntimeStatus:
    runtime = _settings_for_runtime_profile(settings or load_boxlite_runtime_settings(), profile_name=profile_name)
    if not runtime.enabled:
        return BoxLiteRuntimeStatus(
            available=False,
            reason="boxlite_disabled",
            mode=runtime.mode,
            provider=runtime.provider,
            working_dir=runtime.working_dir,
            image=runtime.image,
            runtime_profile=runtime.runtime_profile,
            asset_name=runtime.asset_name,
        )

    provider = str(runtime.provider or "sdk").strip().lower() or "sdk"
    if provider not in {"sdk", "rest"}:
        return BoxLiteRuntimeStatus(False, f"unsupported_boxlite_provider:{provider}", runtime.mode, provider, runtime.working_dir, runtime.image, runtime.runtime_profile, runtime.asset_name)

    if provider == "sdk":
        try:
            importlib.import_module("boxlite")
        except BaseException as exc:
            if _is_missing_boxlite_module(exc):
                installed, install_reason = _bootstrap_boxlite_sdk(runtime)
                if not installed:
                    reason = install_reason or f"boxlite_sdk_import_failed:{exc}"
                    return BoxLiteRuntimeStatus(False, reason, runtime.mode, provider, runtime.working_dir, runtime.image, runtime.runtime_profile, runtime.asset_name)
                try:
                    importlib.import_module("boxlite")
                except BaseException as retry_exc:
                    return BoxLiteRuntimeStatus(False, f"boxlite_sdk_import_failed:{retry_exc}", runtime.mode, provider, runtime.working_dir, runtime.image, runtime.runtime_profile, runtime.asset_name)
            else:
                return BoxLiteRuntimeStatus(False, f"boxlite_sdk_import_failed:{exc}", runtime.mode, provider, runtime.working_dir, runtime.image, runtime.runtime_profile, runtime.asset_name)

        if os.name != "nt" and os.environ.get("EMBLA_BOXLITE_SKIP_KVM_CHECK", "0").strip() not in {"1", "true", "TRUE", "yes", "on"}:
            kvm_path = Path("/dev/kvm")
            if not kvm_path.exists():
                return BoxLiteRuntimeStatus(False, "boxlite_kvm_unavailable", runtime.mode, provider, runtime.working_dir, runtime.image, runtime.runtime_profile, runtime.asset_name)
            try:
                fd = os.open(str(kvm_path), os.O_RDWR | getattr(os, "O_CLOEXEC", 0))
            except OSError as exc:
                detail = _truncate_reason(getattr(exc, "strerror", "") or str(exc), 120)
                suffix = f":{detail}" if detail else ""
                return BoxLiteRuntimeStatus(False, f"boxlite_kvm_inaccessible{suffix}", runtime.mode, provider, runtime.working_dir, runtime.image, runtime.runtime_profile, runtime.asset_name)
            else:
                os.close(fd)
        return BoxLiteRuntimeStatus(True, "", runtime.mode, provider, runtime.working_dir, runtime.image, runtime.runtime_profile, runtime.asset_name)

    base_url = str(runtime.base_url or "").strip()
    if not base_url:
        return BoxLiteRuntimeStatus(False, "boxlite_rest_base_url_missing", runtime.mode, provider, runtime.working_dir, runtime.image, runtime.runtime_profile, runtime.asset_name)
    try:
        import requests
        resp = requests.get(base_url.rstrip("/") + "/health", timeout=1.5)
        if resp.status_code >= 400:
            return BoxLiteRuntimeStatus(False, f"boxlite_rest_health_http_{resp.status_code}", runtime.mode, provider, runtime.working_dir, runtime.image, runtime.runtime_profile, runtime.asset_name)
        return BoxLiteRuntimeStatus(True, "", runtime.mode, provider, runtime.working_dir, runtime.image, runtime.runtime_profile, runtime.asset_name)
    except Exception as exc:  # pragma: no cover - depends on runtime availability
        return BoxLiteRuntimeStatus(False, f"boxlite_rest_probe_failed:{exc}", runtime.mode, provider, runtime.working_dir, runtime.image, runtime.runtime_profile, runtime.asset_name)


async def _prewarm_boxlite_runtime(
    runtime: BoxLiteRuntimeSettings,
    *,
    project_root: str | Path | None = None,
    timeout_seconds: Optional[float] = None,
) -> Tuple[bool, str]:
    manager = BoxLiteManager(runtime)
    runtime = manager.runtime_settings_for_profile(runtime.runtime_profile)
    project_root_path = _resolve_project_root(project_root)
    prewarm_timeout_seconds = max(
        5.0,
        float(timeout_seconds or getattr(runtime, "startup_prewarm_timeout_seconds", 45) or 45),
    )
    box_name = f"embla-prewarm-{uuid.uuid4().hex[:10]}"
    prewarm_command = tuple(runtime.prewarm_command or ("python", "-V")) or ("python", "-V")
    command = str(prewarm_command[0] or runtime.python_cmd or "python").strip() or "python"
    args = [str(item or "").strip() for item in prewarm_command[1:] if str(item or "").strip()]

    with tempfile.TemporaryDirectory(prefix="embla-boxlite-prewarm-") as temp_dir:
        workspace_root = Path(temp_dir) / "workspace"
        workspace_root.mkdir(parents=True, exist_ok=True)
        try:
            result = await manager.exec_in_box(
                box_name=box_name,
                workspace_host_root=str(workspace_root),
                execution_profile=runtime.runtime_profile,
                command=command,
                args=args,
                timeout_seconds=prewarm_timeout_seconds,
                project_root=str(project_root_path),
            )
        except BaseException as exc:
            return False, _classify_boxlite_runtime_error(exc)
        finally:
            if box_name in manager._boxes:
                try:
                    await manager.teardown_box(box_name, allow_runtime_init=False)
                except BaseException:
                    pass

    if int(result.get("exit_code", 1)) != 0:
        return False, _classify_boxlite_runtime_error(result.get("stderr") or result.get("stdout") or "boxlite_prewarm_failed")
    return True, ""


def clear_boxlite_runtime_readiness_cache() -> None:
    with _BOXLITE_READINESS_LOCK:
        _BOXLITE_READINESS_CACHE.clear()


def get_boxlite_runtime_assets_summary(
    settings: Optional[BoxLiteRuntimeSettings] = None,
    *,
    project_root: str | Path | None = None,
) -> Dict[str, Any]:
    runtime = settings or load_boxlite_runtime_settings()
    state = _load_runtime_asset_state(runtime, project_root=project_root)
    configured_profiles = runtime.runtime_profiles or {}
    profile_entries: List[Dict[str, Any]] = []
    for name in sorted(set(configured_profiles.keys()) | set((state.get("profiles") or {}).keys())):
        entry = (state.get("profiles") or {}).get(name)
        if not isinstance(entry, Mapping):
            entry = {}
        profile_entries.append(_summarize_profile_entry(runtime, entry, profile_name=name))

    active_profile = _resolve_runtime_profile_name(runtime)
    active_entry = next((item for item in profile_entries if str(item.get("profile") or "") == active_profile), None)
    if active_entry is None:
        active_entry = _summarize_profile_entry(runtime, {}, profile_name=active_profile)
        profile_entries.append(active_entry)
    return {
        "enabled": bool(runtime.enabled),
        "provider": str(runtime.provider or "sdk"),
        "mode": str(runtime.mode or "required"),
        "active_profile": active_profile,
        "asset_name": str(active_entry.get("asset_name") or runtime.asset_name),
        "image": str(active_entry.get("image") or runtime.image),
        "requested_image": str(active_entry.get("requested_image") or runtime.image),
        "resolved_image": str(active_entry.get("resolved_image") or active_entry.get("image") or runtime.image),
        "image_candidates": list(active_entry.get("image_candidates") or list(runtime.image_candidates or (runtime.image,))),
        "working_dir": str(active_entry.get("working_dir") or runtime.working_dir),
        "status": str(active_entry.get("status") or "unknown"),
        "severity": str(active_entry.get("severity") or "unknown"),
        "reason_code": str(active_entry.get("reason_code") or ""),
        "reason_text": str(active_entry.get("reason_text") or ""),
        "runtime_state_file": str(_resolve_runtime_state_file(runtime, project_root=project_root)),
        "auto_reconcile_enabled": bool(getattr(runtime, "auto_reconcile_enabled", True)),
        "local_image_build_enabled": bool(getattr(runtime, "local_image_build_enabled", True)),
        "local_image_builder": str(getattr(runtime, "local_image_builder", "auto") or "auto"),
        "reconcile_interval_seconds": int(getattr(runtime, "reconcile_interval_seconds", 900) or 900),
        "reconcile_stale_after_seconds": int(getattr(runtime, "reconcile_stale_after_seconds", 43200) or 43200),
        "startup_prewarm_enabled": bool(getattr(runtime, "startup_prewarm_enabled", True)),
        "core_ensure_before_spawn_enabled": bool(getattr(runtime, "core_ensure_before_spawn_enabled", True)),
        "generated_at": str(state.get("generated_at") or ""),
        "profiles": profile_entries,
    }


def ensure_boxlite_runtime_profile(
    settings: Optional[BoxLiteRuntimeSettings] = None,
    *,
    profile_name: str | None = None,
    project_root: str | Path | None = None,
    force: bool = False,
    reason: str = "manual",
) -> BoxLiteRuntimeStatus:
    runtime = settings or load_boxlite_runtime_settings()
    profile_runtime = _settings_for_runtime_profile(runtime, profile_name=profile_name)
    status = probe_boxlite_runtime_readiness(
        profile_runtime,
        project_root=project_root,
        force=force,
        profile_name=profile_runtime.runtime_profile,
    )

    state = _load_runtime_asset_state(runtime, project_root=project_root)
    profiles = state.get("profiles") if isinstance(state.get("profiles"), dict) else {}
    entry = profiles.get(profile_runtime.runtime_profile)
    if not isinstance(entry, dict):
        entry = {}
    now = _utc_now_iso()
    entry.update(
        {
            "profile": profile_runtime.runtime_profile,
            "asset_name": profile_runtime.asset_name,
            "status": "ready" if bool(status.available) else "failed",
            "requested_image": profile_runtime.image,
            "resolved_image": str(getattr(status, "image", "") or profile_runtime.image),
            "image": str(getattr(status, "image", "") or profile_runtime.image),
            "image_candidates": list(profile_runtime.image_candidates or (profile_runtime.image,)),
            "working_dir": profile_runtime.working_dir,
            "cpus": int(profile_runtime.cpus),
            "memory_mib": int(profile_runtime.memory_mib),
            "network_enabled": bool(profile_runtime.network_enabled),
            "prewarm_command": list(profile_runtime.prewarm_command or ("python", "-V")),
            "last_checked_at": now,
            "last_reason": str(status.reason or ""),
            "last_action": str(reason or "manual"),
        }
    )
    if bool(status.available):
        entry["last_ready_at"] = now
        entry["last_error"] = ""
    else:
        entry["last_error"] = str(status.reason or "boxlite_runtime_unavailable")
    profiles[profile_runtime.runtime_profile] = entry
    state["profiles"] = profiles
    state["active_profile"] = _resolve_runtime_profile_name(runtime)
    state["generated_at"] = now
    with _BOXLITE_STATE_LOCK:
        _write_runtime_asset_state(runtime, state, project_root=project_root)
    return status


def build_local_boxlite_runtime_image(
    settings: Optional[BoxLiteRuntimeSettings] = None,
    *,
    profile_name: str | None = None,
    project_root: str | Path | None = None,
    image_tag: str | None = None,
) -> Dict[str, Any]:
    runtime = _settings_for_runtime_profile(settings or load_boxlite_runtime_settings(), profile_name=profile_name)
    target_image = str(image_tag or runtime.image or "").strip()
    if not target_image:
        return {"ok": False, "reason": "boxlite_local_image_build_image_missing", "image": ""}
    if not bool(getattr(runtime, "local_image_build_enabled", True)):
        return {"ok": False, "reason": "boxlite_local_image_build_disabled", "image": target_image}

    builder_cmd = _detect_container_builder(str(getattr(runtime, "local_image_builder", "auto") or "auto"))
    if not builder_cmd:
        return {"ok": False, "reason": "boxlite_local_image_builder_missing", "image": target_image}

    context_dir = _resolve_local_image_context_dir(runtime, project_root=project_root)
    dockerfile = _resolve_local_image_dockerfile(runtime, project_root=project_root)
    if not context_dir.exists():
        return {"ok": False, "reason": f"boxlite_local_image_context_missing:{context_dir}", "image": target_image}
    if not dockerfile.exists():
        return {"ok": False, "reason": f"boxlite_local_image_dockerfile_missing:{dockerfile}", "image": target_image}

    cmd = [
        *builder_cmd,
        "build",
        "-t",
        target_image,
        "-f",
        str(dockerfile),
        "--build-arg",
        f"EMBLA_RUNTIME_ASSET_NAME={runtime.asset_name}",
        str(context_dir),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800, check=False)
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "boxlite_local_image_build_timeout", "image": target_image, "builder": builder_cmd[0]}
    except Exception as exc:
        return {"ok": False, "reason": f"boxlite_local_image_build_failed:{exc}", "image": target_image, "builder": builder_cmd[0]}
    if int(proc.returncode) != 0:
        detail = _truncate_reason(proc.stderr or proc.stdout or "", 240)
        suffix = f":{detail}" if detail else ""
        return {
            "ok": False,
            "reason": f"boxlite_local_image_build_failed:exit_code={proc.returncode}{suffix}",
            "image": target_image,
            "builder": builder_cmd[0],
        }
    clear_boxlite_runtime_readiness_cache()
    return {
        "ok": True,
        "reason": "",
        "image": target_image,
        "builder": builder_cmd[0],
        "context_dir": str(context_dir),
        "dockerfile": str(dockerfile),
    }


def prepare_boxlite_runtime_installation(
    settings: Optional[BoxLiteRuntimeSettings] = None,
    *,
    profile_name: str | None = None,
    project_root: str | Path | None = None,
    force: bool = False,
    include_all_profiles: bool = False,
) -> Dict[str, Any]:
    runtime = settings or load_boxlite_runtime_settings()
    profile_names: List[str]
    if include_all_profiles:
        profile_names = sorted((runtime.runtime_profiles or {}).keys()) or [_resolve_runtime_profile_name(runtime, profile_name)]
    else:
        profile_names = [_resolve_runtime_profile_name(runtime, profile_name)]

    prepared: List[Dict[str, Any]] = []
    overall_available = True
    for name in profile_names:
        status = ensure_boxlite_runtime_profile(
            runtime,
            profile_name=name,
            project_root=project_root,
            force=force,
            reason="install_prefetch",
        )
        build_result: Dict[str, Any] | None = None
        if (
            not bool(getattr(status, "available", False))
            and str(getattr(status, "reason", "") or "").startswith("boxlite_image_pull_")
            and _is_embla_runtime_image(str(getattr(status, "image", "") or ""))
        ):
            build_result = build_local_boxlite_runtime_image(
                runtime,
                profile_name=name,
                project_root=project_root,
                image_tag=str(getattr(status, "image", "") or ""),
            )
            if bool(build_result.get("ok", False)):
                status = ensure_boxlite_runtime_profile(
                    runtime,
                    profile_name=name,
                    project_root=project_root,
                    force=True,
                    reason="install_prefetch_after_local_build",
                )
        prepared.append(
            {
                "profile": name,
                "asset_name": str(getattr(status, "asset_name", "") or ""),
                "image": str(getattr(status, "image", "") or ""),
                "available": bool(getattr(status, "available", False)),
                "reason": str(getattr(status, "reason", "") or ""),
                "local_build": dict(build_result or {}),
            }
        )
        if not bool(getattr(status, "available", False)):
            overall_available = False

    summary = get_boxlite_runtime_assets_summary(runtime, project_root=project_root)
    return {
        "ok": overall_available,
        "prepared_profiles": prepared,
        "summary": summary,
    }


def run_boxlite_runtime_reconciler(
    *,
    stop_requested,
    settings: Optional[BoxLiteRuntimeSettings] = None,
    project_root: str | Path | None = None,
) -> None:
    runtime = settings or load_boxlite_runtime_settings()
    if not bool(runtime.enabled) or not bool(getattr(runtime, "auto_reconcile_enabled", True)):
        return

    interval_seconds = max(60.0, float(getattr(runtime, "reconcile_interval_seconds", 900) or 900))
    stale_after_seconds = max(300.0, float(getattr(runtime, "reconcile_stale_after_seconds", 43200) or 43200))
    active_profile = _resolve_runtime_profile_name(runtime)

    while not stop_requested():
        try:
            summary = get_boxlite_runtime_assets_summary(runtime, project_root=project_root)
            current = next(
                (item for item in list(summary.get("profiles") or []) if str(item.get("profile") or "") == active_profile),
                None,
            ) or {}
            current_status = str(current.get("status") or "missing").strip().lower()
            ready_age_seconds = _safe_float(current.get("ready_age_seconds"), stale_after_seconds + 1, minimum=0.0)
            should_refresh = current_status in {"missing", "failed", "stale"} or ready_age_seconds >= stale_after_seconds
            if should_refresh:
                refreshed = ensure_boxlite_runtime_profile(
                    runtime,
                    profile_name=active_profile,
                    project_root=project_root,
                    force=True,
                    reason="idle_reconcile",
                )
                if refreshed.available:
                    logger.info("[boxlite_runtime_reconcile] profile=%s ready", active_profile)
                else:
                    logger.warning(
                        "[boxlite_runtime_reconcile] profile=%s unavailable: %s",
                        active_profile,
                        refreshed.reason or "unknown",
                    )
        except Exception as exc:
            logger.warning("[boxlite_runtime_reconcile] failed: %s", exc)

        slept = 0.0
        while slept < interval_seconds and not stop_requested():
            step = min(1.0, interval_seconds - slept)
            if step > 0:
                threading.Event().wait(step)
            slept += step


def probe_boxlite_runtime_readiness(
    settings: Optional[BoxLiteRuntimeSettings] = None,
    *,
    project_root: str | Path | None = None,
    force: bool = False,
    profile_name: str | None = None,
) -> BoxLiteRuntimeStatus:
    runtime = _settings_for_runtime_profile(settings or load_boxlite_runtime_settings(), profile_name=profile_name)
    base_status = probe_boxlite_runtime(runtime)
    if not base_status.available:
        return base_status

    preferred_failure_status: BoxLiteRuntimeStatus | None = None
    last_status = BoxLiteRuntimeStatus(
        False,
        "boxlite_runtime_unavailable",
        runtime.mode,
        runtime.provider,
        runtime.working_dir,
        runtime.image,
        runtime.runtime_profile,
        runtime.asset_name,
    )
    candidate_runtimes = _iter_runtime_candidate_settings(runtime)
    for candidate_runtime in candidate_runtimes:
        cache_key = _boxlite_readiness_cache_key(candidate_runtime)
        if not force:
            with _BOXLITE_READINESS_LOCK:
                cached = _BOXLITE_READINESS_CACHE.get(cache_key)
            if cached is not None:
                ok, reason = cached
                cached_status = BoxLiteRuntimeStatus(
                    ok,
                    reason,
                    candidate_runtime.mode,
                    candidate_runtime.provider,
                    candidate_runtime.working_dir,
                    candidate_runtime.image,
                    candidate_runtime.runtime_profile,
                    candidate_runtime.asset_name,
                )
                if ok:
                    return cached_status
                last_status = cached_status
                continue

        ok, reason = _run_async_sync(
            _prewarm_boxlite_runtime(
                candidate_runtime,
                project_root=project_root,
                timeout_seconds=float(getattr(candidate_runtime, "startup_prewarm_timeout_seconds", 45) or 45),
            )
        )
        normalized_reason = str(reason or "")
        if not ok and not normalized_reason.startswith("boxlite_"):
            normalized_reason = _classify_boxlite_runtime_error(normalized_reason)
        with _BOXLITE_READINESS_LOCK:
            _BOXLITE_READINESS_CACHE[cache_key] = (bool(ok), normalized_reason)
        candidate_status = BoxLiteRuntimeStatus(
            bool(ok),
            normalized_reason,
            candidate_runtime.mode,
            candidate_runtime.provider,
            candidate_runtime.working_dir,
            candidate_runtime.image,
            candidate_runtime.runtime_profile,
            candidate_runtime.asset_name,
        )
        if ok:
            return candidate_status
        if (
            preferred_failure_status is None
            and str(candidate_status.reason or "").startswith("boxlite_image_pull_")
            and _is_embla_runtime_image(str(candidate_status.image or ""))
        ):
            preferred_failure_status = candidate_status
        last_status = candidate_status

    if preferred_failure_status is not None:
        return preferred_failure_status
    return last_status


def resolve_execution_runtime_metadata(
    *,
    requested_backend: Any,
    workspace_mode: str,
    workspace_root: str,
    parent_metadata: Optional[Mapping[str, Any]] = None,
    execution_profile: str = "default",
    box_profile: str = "default",
    project_root: str | Path | None = None,
) -> Dict[str, Any]:
    cfg = get_config()
    sandbox_cfg = getattr(cfg, "sandbox", None)
    boxlite_settings = load_boxlite_runtime_settings()
    os_sandbox_policy = resolve_os_sandbox_runtime_policy(execution_profile)
    runtime_profile_settings = _settings_for_runtime_profile(boxlite_settings, profile_name=execution_profile)
    default_backend = normalize_execution_backend(getattr(sandbox_cfg, "default_execution_backend", "os_sandbox"))
    self_repo_backend = normalize_execution_backend(getattr(sandbox_cfg, "self_repo_execution_backend", default_backend))

    raw_requested = str(requested_backend or "").strip()
    if not raw_requested:
        inherited_requested = ""
        if isinstance(parent_metadata, Mapping):
            inherited_requested = str(
                parent_metadata.get("execution_backend_requested") or parent_metadata.get("execution_backend") or ""
            ).strip()
        if inherited_requested:
            raw_requested = inherited_requested
        elif str(workspace_mode or "").strip().lower() in {"worktree", "inherit"} and str(workspace_root or "").strip():
            raw_requested = self_repo_backend
        else:
            raw_requested = default_backend

    requested = normalize_execution_backend(raw_requested)
    effective = requested
    fallback_reason = ""
    runtime_status = BoxLiteRuntimeStatus(
        available=False,
        reason="boxlite_not_requested",
        mode=str(getattr(runtime_profile_settings, "mode", "required") or "required"),
        provider=str(getattr(runtime_profile_settings, "provider", "sdk") or "sdk"),
        working_dir=str(getattr(runtime_profile_settings, "working_dir", "/workspace") or "/workspace"),
        image=str(getattr(runtime_profile_settings, "image", "embla/boxlite-runtime:py311") or "embla/boxlite-runtime:py311"),
        runtime_profile=str(getattr(runtime_profile_settings, "runtime_profile", execution_profile or "default") or "default"),
        asset_name=str(getattr(runtime_profile_settings, "asset_name", "embla_py311_default") or "embla_py311_default"),
    )
    if requested == "boxlite":
        try:
            if bool(getattr(boxlite_settings, "core_ensure_before_spawn_enabled", True)):
                runtime_status = ensure_boxlite_runtime_profile(
                    boxlite_settings,
                    profile_name=execution_profile,
                    project_root=project_root,
                    force=False,
                    reason="spawn_prepare",
                )
            else:
                runtime_status = probe_boxlite_runtime_readiness(
                    boxlite_settings,
                    project_root=project_root,
                    force=False,
                    profile_name=execution_profile,
                )
        except Exception as exc:
            fallback_detail = str(exc or "").strip()
            normalized_reason = fallback_detail or "boxlite_runtime_prepare_failed"
            if not normalized_reason.startswith("boxlite_"):
                normalized_reason = _classify_boxlite_runtime_error(normalized_reason)
            runtime_status = BoxLiteRuntimeStatus(
                available=False,
                reason=normalized_reason,
                mode=str(getattr(runtime_profile_settings, "mode", "required") or "required"),
                provider=str(getattr(runtime_profile_settings, "provider", "sdk") or "sdk"),
                working_dir=str(getattr(runtime_profile_settings, "working_dir", "/workspace") or "/workspace"),
                image=str(getattr(runtime_profile_settings, "image", "embla/boxlite-runtime:py311") or "embla/boxlite-runtime:py311"),
                runtime_profile=str(getattr(runtime_profile_settings, "runtime_profile", execution_profile or "default") or "default"),
                asset_name=str(getattr(runtime_profile_settings, "asset_name", "embla_py311_default") or "embla_py311_default"),
            )
    execution_root = str(workspace_root or project_root or Path(__file__).resolve().parents[2]).strip()

    if requested == "boxlite":
        if runtime_status.available:
            execution_root = runtime_status.working_dir or "/workspace"
        else:
            effective = resolve_worktree_fallback_backend(
                workspace_mode=workspace_mode,
                workspace_root=workspace_root,
            )
            execution_root = (
                str(workspace_root or project_root or Path(__file__).resolve().parents[2]).strip()
                if effective == "os_sandbox"
                else str(project_root or Path(__file__).resolve().parents[2]).strip()
            )
            fallback_reason = runtime_status.reason or "boxlite_unavailable"

    if effective == "os_sandbox":
        sandbox_policy = os_sandbox_policy.profile_name
        network_policy = "enabled" if os_sandbox_policy.network_enabled else "disabled"
        resource_profile = os_sandbox_policy.resource_profile
    elif effective == "boxlite":
        sandbox_policy = str(getattr(runtime_status, "runtime_profile", execution_profile or "default") or "default").strip() or "default"
        box_network = bool(getattr(runtime_profile_settings, "network_enabled", False))
        network_policy = "enabled" if box_network else "disabled"
        resource_profile = f"boxlite:{sandbox_policy}"
    else:
        sandbox_policy = "host"
        network_policy = "host"
        resource_profile = "host"

    return {
        "execution_backend_requested": requested,
        "execution_backend": effective,
        "execution_root": execution_root,
        "execution_profile": str(execution_profile or "default").strip() or "default",
        "sandbox_policy": sandbox_policy,
        "network_policy": network_policy,
        "resource_profile": resource_profile,
        "box_profile": str(box_profile or "default").strip() or "default",
        "box_provider": str(runtime_status.provider or getattr(runtime_profile_settings, "provider", "sdk") or "sdk"),
        "box_mount_mode": "rw",
        "box_fallback_reason": fallback_reason,
    }


def teardown_box_session(metadata: Mapping[str, Any]) -> Tuple[bool, str]:
    box_id = str(metadata.get("box_id") or "").strip()
    box_name = str(metadata.get("box_name") or "").strip()
    box_ref = box_id or box_name
    if not box_ref:
        return True, ""
    manager = BoxLiteManager()
    return _run_async_sync(manager.teardown_box(box_ref))
