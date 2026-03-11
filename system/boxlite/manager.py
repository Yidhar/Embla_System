from __future__ import annotations

import asyncio
import importlib
import inspect
import logging
import os
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from system.config import get_config
from system.sandbox_context import normalize_execution_backend


logger = logging.getLogger(__name__)
_BOXLITE_INSTALL_LOCK = threading.Lock()
_BOXLITE_INSTALL_CACHE: Dict[Tuple[str, str], Tuple[bool, str]] = {}


@dataclass(frozen=True)
class BoxLiteRuntimeSettings:
    enabled: bool = True
    mode: str = "required"
    provider: str = "sdk"
    base_url: str = ""
    image: str = "python:slim"
    working_dir: str = "/workspace"
    cpus: int = 2
    memory_mib: int = 1024
    auto_remove: bool = True
    security_preset: str = "maximum"
    network_enabled: bool = False
    auto_install_sdk: bool = True
    install_timeout_seconds: int = 300
    sdk_package_spec: str = "boxlite"


@dataclass(frozen=True)
class BoxLiteRuntimeStatus:
    available: bool
    reason: str = ""
    mode: str = "required"
    provider: str = "sdk"
    working_dir: str = "/workspace"
    image: str = "python:slim"


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
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        loop_running = False
    else:
        loop_running = True

    if not loop_running:
        try:
            return asyncio.run(coro)
        except Exception as exc:
            return False, str(exc)

    import threading

    result: dict[str, Any] = {}

    def _worker() -> None:
        try:
            result["value"] = asyncio.run(coro)
        except Exception as exc:
            result["error"] = str(exc)

    thread = threading.Thread(target=_worker, name="embla-boxlite-teardown", daemon=True)
    thread.start()
    thread.join()
    if "error" in result:
        return False, str(result["error"])
    return tuple(result.get("value") or (True, ""))


def build_boxlite_volume_mounts(
    *,
    workspace_host_root: str,
    working_dir: str = "/workspace",
    project_root: str = "",
) -> List[tuple[str, str, str]]:
    workspace_root = Path(str(workspace_host_root or "")).resolve(strict=False)
    if not str(workspace_root).strip():
        raise RuntimeError("workspace_host_root is required for boxlite execution")

    resolved_working_dir = str(working_dir or "/workspace").strip() or "/workspace"
    mounts: List[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()

    def _add_mount(host_path: Path, guest_path: str, mode: str) -> None:
        host_text = str(host_path.resolve(strict=False)).strip()
        guest_text = str(guest_path or "").strip()
        if not host_text or not guest_text:
            return
        key = (host_text, guest_text)
        if key in seen:
            return
        seen.add(key)
        mounts.append((host_text, guest_text, mode))

    _add_mount(workspace_root, resolved_working_dir, "rw")

    project_root_path = Path(str(project_root or "")).resolve(strict=False) if str(project_root or "").strip() else None
    if project_root_path is not None:
        _add_mount(project_root_path, str(project_root_path), "ro")
        venv_path = project_root_path / ".venv"
        if venv_path.exists():
            workspace_venv_guest = resolved_working_dir.rstrip("/") + "/.venv"
            _add_mount(venv_path, workspace_venv_guest, "ro")

    return mounts


class BoxLiteManager:
    def __init__(self, settings: Optional[BoxLiteRuntimeSettings] = None) -> None:
        self.settings = settings or load_boxlite_runtime_settings()
        self._runtime = None
        self._boxes: Dict[str, Any] = {}

    def availability(self) -> BoxLiteRuntimeStatus:
        return probe_boxlite_runtime(self.settings)

    async def ensure_box(
        self,
        *,
        box_name: str,
        workspace_host_root: str,
        box_profile: str = "default",
        working_dir: str | None = None,
        project_root: str | None = None,
    ) -> tuple[Any, bool]:
        del box_profile
        status = self.availability()
        if not status.available:
            raise RuntimeError(status.reason or "boxlite runtime unavailable")
        if self.settings.provider != "sdk":
            raise RuntimeError(f"unsupported boxlite provider: {self.settings.provider}")

        workspace_root = Path(str(workspace_host_root or "")).resolve(strict=False)
        if not str(workspace_root).strip():
            raise RuntimeError("workspace_host_root is required for boxlite execution")

        import boxlite

        if self._runtime is None:
            self._runtime = boxlite.Boxlite.default()

        security = getattr(boxlite.SecurityOptions, str(self.settings.security_preset or "maximum"), None)
        if callable(security):
            security = security()
        else:
            security = boxlite.SecurityOptions.maximum()
        try:
            security.network_enabled = bool(self.settings.network_enabled)
        except Exception:
            pass

        resolved_working_dir = str(working_dir or self.settings.working_dir or "/workspace")
        volumes = build_boxlite_volume_mounts(
            workspace_host_root=str(workspace_root),
            working_dir=resolved_working_dir,
            project_root=str(project_root or ""),
        )

        option_kwargs = {
            "image": self.settings.image,
            "cpus": int(self.settings.cpus),
            "memory_mib": int(self.settings.memory_mib),
            "working_dir": resolved_working_dir,
            "auto_remove": bool(self.settings.auto_remove),
            "volumes": volumes,
        }
        try:
            supported = set(inspect.signature(boxlite.BoxOptions).parameters)
        except Exception:
            supported = set()
        if "security" in supported:
            option_kwargs["security"] = security
        if "network" in supported:
            option_kwargs["network"] = bool(self.settings.network_enabled)
        options = boxlite.BoxOptions(**option_kwargs)
        box, created = await self._runtime.get_or_create(options, name=box_name)
        await box.__aenter__()
        self._boxes[box_name] = box
        return box, bool(created)

    async def exec_in_box(
        self,
        *,
        box_name: str,
        workspace_host_root: str,
        command: str,
        args: Optional[list[str]] = None,
        env: Optional[Dict[str, str]] = None,
        working_dir: str | None = None,
        timeout_seconds: float | None = None,
        project_root: str | None = None,
    ) -> Dict[str, Any]:
        box, created = await self.ensure_box(
            box_name=box_name,
            workspace_host_root=workspace_host_root,
            working_dir=working_dir,
            project_root=project_root,
        )
        del created
        execution = await box.exec(command, args or None, list((env or {}).items()) if env else None)
        try:
            result = await asyncio.wait_for(execution.wait(), timeout=timeout_seconds or 30)
        except asyncio.TimeoutError:
            try:
                await execution.kill()
            except Exception:
                pass
            raise
        return {
            "exit_code": int(getattr(result, "exit_code", 1)),
            "stdout": str(getattr(result, "stdout", "") or ""),
            "stderr": str(getattr(result, "stderr", "") or ""),
            "box_id": str(getattr(box, "id", "") or ""),
            "box_name": str(box_name or "").strip(),
        }

    async def teardown_box(self, box_ref: str) -> tuple[bool, str]:
        box_ref_text = str(box_ref or "").strip()
        if not box_ref_text:
            return True, ""

        status = self.availability()
        if not status.available:
            return False, status.reason or "boxlite runtime unavailable"

        if self.settings.provider != "sdk":
            return False, f"unsupported boxlite provider for teardown: {self.settings.provider}"

        try:
            import boxlite
            runtime = self._runtime or boxlite.Boxlite.default()
            box = await runtime.get(box_ref_text)
            if box is not None:
                try:
                    await box.__aexit__(None, None, None)
                except Exception:
                    pass
            try:
                await runtime.remove(box_ref_text, True)
            except Exception:
                if box is not None:
                    try:
                        await box.remove()
                    except Exception:
                        pass
            self._boxes.pop(box_ref_text, None)
            for key, cached in list(self._boxes.items()):
                if str(getattr(cached, "id", "") or "").strip() == box_ref_text:
                    self._boxes.pop(key, None)
            return True, ""
        except Exception as exc:  # pragma: no cover - depends on external runtime
            return False, str(exc)


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


def load_boxlite_runtime_settings() -> BoxLiteRuntimeSettings:
    cfg = get_config()
    sandbox_cfg = getattr(cfg, "sandbox", None)
    boxlite_cfg = getattr(sandbox_cfg, "boxlite", None)
    if boxlite_cfg is None:
        return BoxLiteRuntimeSettings()
    return BoxLiteRuntimeSettings(
        enabled=bool(getattr(boxlite_cfg, "enabled", False)),
        mode=_normalize_mode(getattr(boxlite_cfg, "mode", "required")),
        provider=str(getattr(boxlite_cfg, "provider", "sdk") or "sdk").strip() or "sdk",
        base_url=str(getattr(boxlite_cfg, "base_url", "") or "").strip(),
        image=str(getattr(boxlite_cfg, "image", "python:slim") or "python:slim").strip() or "python:slim",
        working_dir=str(getattr(boxlite_cfg, "working_dir", "/workspace") or "/workspace").strip() or "/workspace",
        cpus=max(1, int(getattr(boxlite_cfg, "cpus", 2) or 2)),
        memory_mib=max(128, int(getattr(boxlite_cfg, "memory_mib", 1024) or 1024)),
        auto_remove=bool(getattr(boxlite_cfg, "auto_remove", True)),
        security_preset=str(getattr(boxlite_cfg, "security_preset", "maximum") or "maximum").strip() or "maximum",
        network_enabled=bool(getattr(boxlite_cfg, "network_enabled", False)),
        auto_install_sdk=bool(getattr(boxlite_cfg, "auto_install_sdk", True)),
        install_timeout_seconds=max(10, int(getattr(boxlite_cfg, "install_timeout_seconds", 300) or 300)),
        sdk_package_spec=str(getattr(boxlite_cfg, "sdk_package_spec", "boxlite") or "boxlite").strip() or "boxlite",
    )


def probe_boxlite_runtime(settings: Optional[BoxLiteRuntimeSettings] = None) -> BoxLiteRuntimeStatus:
    runtime = settings or load_boxlite_runtime_settings()
    if not runtime.enabled:
        return BoxLiteRuntimeStatus(
            available=False,
            reason="boxlite_disabled",
            mode=runtime.mode,
            provider=runtime.provider,
            working_dir=runtime.working_dir,
            image=runtime.image,
        )

    provider = str(runtime.provider or "sdk").strip().lower() or "sdk"
    if provider not in {"sdk", "rest"}:
        return BoxLiteRuntimeStatus(False, f"unsupported_boxlite_provider:{provider}", runtime.mode, provider, runtime.working_dir, runtime.image)

    if provider == "sdk":
        try:
            importlib.import_module("boxlite")
        except Exception as exc:
            if _is_missing_boxlite_module(exc):
                installed, install_reason = _bootstrap_boxlite_sdk(runtime)
                if not installed:
                    reason = install_reason or f"boxlite_sdk_import_failed:{exc}"
                    return BoxLiteRuntimeStatus(False, reason, runtime.mode, provider, runtime.working_dir, runtime.image)
                try:
                    importlib.import_module("boxlite")
                except Exception as retry_exc:
                    return BoxLiteRuntimeStatus(False, f"boxlite_sdk_import_failed:{retry_exc}", runtime.mode, provider, runtime.working_dir, runtime.image)
            else:
                return BoxLiteRuntimeStatus(False, f"boxlite_sdk_import_failed:{exc}", runtime.mode, provider, runtime.working_dir, runtime.image)

        if os.name != "nt" and os.environ.get("EMBLA_BOXLITE_SKIP_KVM_CHECK", "0").strip() not in {"1", "true", "TRUE", "yes", "on"}:
            kvm_path = Path("/dev/kvm")
            if not kvm_path.exists():
                return BoxLiteRuntimeStatus(False, "boxlite_kvm_unavailable", runtime.mode, provider, runtime.working_dir, runtime.image)
            try:
                fd = os.open(str(kvm_path), os.O_RDWR | getattr(os, "O_CLOEXEC", 0))
            except OSError as exc:
                detail = _truncate_reason(getattr(exc, "strerror", "") or str(exc), 120)
                suffix = f":{detail}" if detail else ""
                return BoxLiteRuntimeStatus(False, f"boxlite_kvm_inaccessible{suffix}", runtime.mode, provider, runtime.working_dir, runtime.image)
            else:
                os.close(fd)
        return BoxLiteRuntimeStatus(True, "", runtime.mode, provider, runtime.working_dir, runtime.image)

    base_url = str(runtime.base_url or "").strip()
    if not base_url:
        return BoxLiteRuntimeStatus(False, "boxlite_rest_base_url_missing", runtime.mode, provider, runtime.working_dir, runtime.image)
    try:
        import requests
        resp = requests.get(base_url.rstrip("/") + "/health", timeout=1.5)
        if resp.status_code >= 400:
            return BoxLiteRuntimeStatus(False, f"boxlite_rest_health_http_{resp.status_code}", runtime.mode, provider, runtime.working_dir, runtime.image)
        return BoxLiteRuntimeStatus(True, "", runtime.mode, provider, runtime.working_dir, runtime.image)
    except Exception as exc:  # pragma: no cover - depends on runtime availability
        return BoxLiteRuntimeStatus(False, f"boxlite_rest_probe_failed:{exc}", runtime.mode, provider, runtime.working_dir, runtime.image)


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
    default_backend = normalize_execution_backend(getattr(sandbox_cfg, "default_execution_backend", "boxlite"))
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
    runtime_status = probe_boxlite_runtime()
    execution_root = str(workspace_root or project_root or Path(__file__).resolve().parents[2]).strip()

    if requested == "boxlite":
        if runtime_status.available:
            execution_root = runtime_status.working_dir or "/workspace"
        else:
            if runtime_status.mode == "required":
                raise RuntimeError(f"boxlite runtime required but unavailable: {runtime_status.reason or 'unknown'}")
            effective = "native"
            fallback_reason = runtime_status.reason or "boxlite_unavailable"

    return {
        "execution_backend_requested": requested,
        "execution_backend": effective,
        "execution_root": execution_root,
        "execution_profile": str(execution_profile or "default").strip() or "default",
        "box_profile": str(box_profile or "default").strip() or "default",
        "box_provider": runtime_status.provider if requested == "boxlite" else str(runtime_status.provider or "sdk"),
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
