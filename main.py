#!/usr/bin/env python3
"""Embla System unified backend entry point.

Initialises runtime subsystems, starts the API server when enabled,
and keeps the process alive via the watchdog supervision loop.
"""
# ruff: noqa: E402
from __future__ import annotations

import argparse
import asyncio
import locale
import logging
import signal
import socket
import sys
import threading
import time
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


# ---------------------------------------------------------------------------
# Console encoding (must run before any output)
# ---------------------------------------------------------------------------

def _configure_console() -> None:
    """Fix Windows console encoding for non-UTF-8 codepages."""
    if sys.platform != "win32":
        return
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            continue
        try:
            is_tty = bool(getattr(stream, "isatty", lambda: False)())
            enc = (
                "utf-8"
                if not is_tty
                else (getattr(stream, "encoding", None) or locale.getpreferredencoding(False) or "utf-8")
            )
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding=enc, errors="replace")
            elif hasattr(stream, "buffer"):
                import io

                setattr(sys, name, io.TextIOWrapper(stream.buffer, encoding=enc, errors="replace"))
        except Exception:
            pass


_configure_console()

warnings.filterwarnings("ignore", category=DeprecationWarning, module="websockets")
warnings.filterwarnings("ignore", category=DeprecationWarning, module="uvicorn")

if not hasattr(socket, "EAI_ADDRFAMILY"):
    for attr, val in [
        ("EAI_ADDRFAMILY", -9),
        ("EAI_AGAIN", -3),
        ("EAI_BADFLAGS", -1),
        ("EAI_FAIL", -4),
        ("EAI_MEMORY", -10),
        ("EAI_NODATA", -5),
        ("EAI_NONAME", -2),
        ("EAI_OVERFLOW", -12),
        ("EAI_SERVICE", -8),
        ("EAI_SOCKTYPE", -7),
        ("EAI_SYSTEM", -11),
    ]:
        setattr(socket, attr, val)


# ---------------------------------------------------------------------------
# Logging — single unified setup for the whole process
# ---------------------------------------------------------------------------

from system.logging_setup import setup_logging

setup_logging()
logger = logging.getLogger("embla.main")

logging.getLogger("OpenGL").setLevel(logging.WARNING)
logging.getLogger("OpenGL.acceleratesupport").setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# Local imports (after logging is ready)
# ---------------------------------------------------------------------------

from system.config import AI_NAME, config
from system.runtime_cleanup import close_runtime_network_clients_sync
from system.system_checker import run_quick_check, run_system_check


# ---------------------------------------------------------------------------
# Args
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StartupOptions:
    check_env: bool = False
    quick_check: bool = False
    force_check: bool = False
    headless: bool = False
    prepare_runtime: bool = False
    prepare_runtime_all_profiles: bool = False
    runtime_profile: str = "default"
    force_runtime_refresh: bool = False

    @property
    def effective_headless(self) -> bool:
        return bool(self.headless or not sys.stdin.isatty())


@dataclass
class APIServerHandle:
    thread: threading.Thread
    server: object
    host: str
    port: int
    stopped_event: threading.Event
    shutdown_requested: threading.Event
    startup_complete: bool = False
    startup_failed: bool = False
    error: str = ""


@dataclass
class RuntimeServices:
    api_server: APIServerHandle | None = None
    api_started: bool = False
    boxlite_reconciler: threading.Thread | None = None


def parse_args(argv: list[str] | None = None) -> StartupOptions:
    parser = argparse.ArgumentParser(description="Embla System — 统一运行入口")
    parser.add_argument("--check-env", action="store_true", help="运行系统环境检测")
    parser.add_argument("--quick-check", action="store_true", help="运行快速环境检测")
    parser.add_argument("--force-check", action="store_true", help="强制检测（忽略缓存）")
    parser.add_argument("--headless", action="store_true", help="无头模式（跳过交互提示）")
    parser.add_argument("--prepare-runtime", action="store_true", help="预取/校验 BoxLite runtime 资产后退出")
    parser.add_argument("--prepare-runtime-all-profiles", action="store_true", help="预取所有已配置 BoxLite runtime profile 后退出")
    parser.add_argument("--runtime-profile", default="default", help="prepare-runtime 时要处理的 runtime profile 名称")
    parser.add_argument("--force-runtime-refresh", action="store_true", help="prepare-runtime 时强制刷新 runtime 资产")
    ns = parser.parse_args(argv)
    return StartupOptions(
        check_env=bool(ns.check_env),
        quick_check=bool(ns.quick_check),
        force_check=bool(ns.force_check),
        headless=bool(ns.headless),
        prepare_runtime=bool(ns.prepare_runtime),
        prepare_runtime_all_profiles=bool(ns.prepare_runtime_all_profiles),
        runtime_profile=str(ns.runtime_profile or "default").strip() or "default",
        force_runtime_refresh=bool(ns.force_runtime_refresh),
    )


# ---------------------------------------------------------------------------
# Startup checks
# ---------------------------------------------------------------------------

def _run_diagnostic(opts: StartupOptions) -> int | None:
    """Run env check if requested via CLI flags. Returns exit code or None."""
    if not opts.check_env and not opts.quick_check:
        return None
    ok = run_quick_check() if opts.quick_check else run_system_check(force_check=opts.force_check)
    return 0 if ok else 1


def _run_startup_gate(opts: StartupOptions) -> bool:
    """Run system environment check. Returns True if OK to proceed."""
    if run_system_check(force_check=opts.force_check):
        return True
    logger.warning("系统环境检测失败")
    if opts.effective_headless:
        logger.warning("无头模式：自动继续启动")
        return True
    reply = input("是否继续启动？(y/N) ")
    return reply.strip().lower() in {"y", "yes"}


def _run_prepare_runtime(opts: StartupOptions) -> int | None:
    if not bool(opts.prepare_runtime or opts.prepare_runtime_all_profiles):
        return None
    try:
        from system.boxlite.manager import load_boxlite_runtime_settings, prepare_boxlite_runtime_installation

        settings = load_boxlite_runtime_settings()
        if not bool(getattr(settings, "enabled", False)):
            logger.info("BoxLite runtime disabled; skipping prepare")
            return 0
        result = prepare_boxlite_runtime_installation(
            settings,
            profile_name=str(opts.runtime_profile or "default").strip() or "default",
            project_root=Path(__file__).resolve().parent,
            force=bool(opts.force_runtime_refresh),
            include_all_profiles=bool(opts.prepare_runtime_all_profiles),
        )
    except Exception as exc:
        logger.error("BoxLite runtime prepare failed: %s", exc)
        return 1

    prepared_profiles = list(result.get("prepared_profiles") or [])
    for item in prepared_profiles:
        local_build = item.get("local_build") if isinstance(item.get("local_build"), dict) else {}
        logger.info(
            "BoxLite runtime prepared: profile=%s asset=%s image=%s available=%s reason=%s local_build=%s",
            str(item.get("profile") or ""),
            str(item.get("asset_name") or ""),
            str(item.get("image") or ""),
            bool(item.get("available")),
            str(item.get("reason") or ""),
            str(local_build.get("builder") or "") if local_build else "",
        )
    return 0 if bool(result.get("ok", False)) else 1


# ---------------------------------------------------------------------------
# Runtime service initialization
# ---------------------------------------------------------------------------

def _init_memory() -> None:
    """Initialise the summer memory subsystem."""
    try:
        from summer_memory.memory_manager import memory_manager

        if memory_manager and memory_manager.enabled:
            logger.info("记忆系统已初始化")
        else:
            logger.info("记忆系统已禁用")
    except Exception as exc:
        logger.warning("记忆系统初始化失败: %s", exc)


def _init_boxlite_runtime() -> None:
    """Preflight BoxLite runtime and trigger first-run SDK bootstrap if needed."""
    try:
        from system.sandbox_context import normalize_execution_backend
        from system.boxlite.manager import (
            build_local_boxlite_runtime_image,
            ensure_boxlite_runtime_profile,
            load_boxlite_runtime_settings,
            probe_boxlite_runtime,
        )

        settings = load_boxlite_runtime_settings()
        if not bool(getattr(settings, "enabled", False)):
            logger.info("BoxLite runtime disabled")
            return

        sandbox_cfg = getattr(config, "sandbox", None)
        default_backend = normalize_execution_backend(getattr(sandbox_cfg, "default_execution_backend", "native"))
        self_repo_backend = normalize_execution_backend(
            getattr(sandbox_cfg, "self_repo_execution_backend", default_backend)
        )
        if default_backend != "boxlite" and self_repo_backend != "boxlite":
            logger.info(
                "BoxLite startup prewarm skipped (default_execution_backend=%s, self_repo_execution_backend=%s)",
                default_backend,
                self_repo_backend,
            )
            return

        availability = probe_boxlite_runtime(settings)
        if not bool(getattr(availability, "available", False)):
            logger.warning("BoxLite runtime unavailable: %s", getattr(availability, "reason", "unknown") or "unknown")
            return

        if not bool(getattr(settings, "startup_prewarm_enabled", True)):
            logger.info(
                "BoxLite runtime available (%s, working_dir=%s, prewarm=disabled)",
                getattr(availability, "provider", "sdk"),
                getattr(availability, "working_dir", "/workspace"),
            )
            return

        readiness = ensure_boxlite_runtime_profile(
            settings,
            profile_name=str(getattr(settings, "runtime_profile", "default") or "default").strip() or "default",
            project_root=Path(__file__).resolve().parent,
            force=True,
            reason="startup_prewarm",
        )
        if (
            not bool(getattr(readiness, "available", False))
            and str(getattr(readiness, "reason", "") or "").startswith("boxlite_image_pull_")
            and str(getattr(readiness, "image", "") or "").strip().lower().startswith("embla/")
        ):
            build_result = build_local_boxlite_runtime_image(
                settings,
                profile_name=str(getattr(settings, "runtime_profile", "default") or "default").strip() or "default",
                project_root=Path(__file__).resolve().parent,
                image_tag=str(getattr(readiness, "image", "") or "").strip() or None,
            )
            if bool(build_result.get("ok", False)):
                logger.info(
                    "BoxLite local runtime image built (profile=%s image=%s builder=%s)",
                    getattr(settings, "runtime_profile", "default"),
                    str(build_result.get("image") or ""),
                    str(build_result.get("builder") or ""),
                )
                readiness = ensure_boxlite_runtime_profile(
                    settings,
                    profile_name=str(getattr(settings, "runtime_profile", "default") or "default").strip() or "default",
                    project_root=Path(__file__).resolve().parent,
                    force=True,
                    reason="startup_prewarm_after_local_build",
                )
        if bool(getattr(readiness, "available", False)):
            logger.info(
                "BoxLite runtime ready (%s, profile=%s, working_dir=%s, image=%s, prewarmed)",
                getattr(readiness, "provider", "sdk"),
                getattr(readiness, "runtime_profile", "default"),
                getattr(readiness, "working_dir", "/workspace"),
                getattr(readiness, "image", "embla/boxlite-runtime:py311"),
            )
        else:
            logger.warning("BoxLite runtime unavailable: %s", getattr(readiness, "reason", "unknown") or "unknown")
    except Exception as exc:
        logger.warning("BoxLite runtime bootstrap failed: %s", exc)


def _init_mcp() -> None:
    """Initialise the official MCP client pool/runtime registry."""
    try:
        from agents.runtime.mcp_client import reload_global_mcp_pool

        loop = asyncio.get_event_loop()
        summary = loop.run_until_complete(reload_global_mcp_pool())
        configured_servers = int(summary.get("configured_servers") or 0)
        connected_servers = int(summary.get("connected_servers") or 0)
        if configured_servers > 0:
            logger.info(
                "官方 MCP 运行时已初始化: configured=%d connected=%d",
                configured_servers,
                connected_servers,
            )
        else:
            logger.info("官方 MCP 运行时: 无已配置服务器")
    except Exception as exc:
        logger.error("MCP 客户端初始化失败: %s", exc)


def _start_boxlite_runtime_reconciler(stop_requested: Callable[[], bool]) -> threading.Thread | None:
    try:
        from system.boxlite.manager import load_boxlite_runtime_settings, run_boxlite_runtime_reconciler

        settings = load_boxlite_runtime_settings()
        if not bool(getattr(settings, "enabled", False)) or not bool(getattr(settings, "auto_reconcile_enabled", True)):
            return None

        thread = threading.Thread(
            target=run_boxlite_runtime_reconciler,
            kwargs={
                "stop_requested": stop_requested,
                "settings": settings,
                "project_root": Path(__file__).resolve().parent,
            },
            name="boxlite-runtime-reconciler",
            daemon=True,
        )
        thread.start()
        logger.info(
            "BoxLite runtime reconciler started (profile=%s interval=%ss)",
            getattr(settings, "runtime_profile", "default"),
            getattr(settings, "reconcile_interval_seconds", 900),
        )
        return thread
    except Exception as exc:
        logger.warning("BoxLite runtime reconciler failed to start: %s", exc)
        return None


def _resolve_probe_host(host: str) -> str:
    normalized = str(host or "").strip()
    if normalized in {"", "0.0.0.0", "::", "[::]"}:
        return "127.0.0.1"
    return normalized


def _iter_tcp_addresses(host: str, port: int, *, passive: bool = False):
    flags = socket.AI_PASSIVE if passive else 0
    try:
        return socket.getaddrinfo(host, int(port), family=socket.AF_UNSPEC, type=socket.SOCK_STREAM, flags=flags)
    except socket.gaierror:
        fallback_family = socket.AF_INET6 if ":" in str(host or "") else socket.AF_INET
        return [(fallback_family, socket.SOCK_STREAM, 0, "", (host, int(port)))]


def _can_bind_tcp_port(host: str, port: int) -> bool:
    for family, socktype, proto, _, sockaddr in _iter_tcp_addresses(host, port, passive=True):
        try:
            with socket.socket(family, socktype, proto) as sock:
                try:
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                except OSError:
                    pass
                sock.bind(sockaddr)
                return True
        except OSError:
            continue
    return False


def _wait_for_tcp_ready(host: str, port: int, *, timeout_seconds: float = 3.0) -> bool:
    deadline = time.time() + max(0.1, float(timeout_seconds))
    probe_host = _resolve_probe_host(host)
    while time.time() < deadline:
        for family, socktype, proto, _, sockaddr in _iter_tcp_addresses(probe_host, port, passive=False):
            try:
                with socket.socket(family, socktype, proto) as sock:
                    sock.settimeout(0.1)
                    if sock.connect_ex(sockaddr) == 0:
                        return True
            except OSError:
                continue
        time.sleep(0.2)
    return False


def _wait_for_tcp_release(host: str, port: int, *, timeout_seconds: float = 3.0) -> bool:
    deadline = time.time() + max(0.1, float(timeout_seconds))
    while time.time() < deadline:
        if _can_bind_tcp_port(host, port):
            return True
        time.sleep(0.1)
    return _can_bind_tcp_port(host, port)


def _start_api_server(*, runtime_config=config) -> APIServerHandle | None:
    """Start the uvicorn API server in a managed thread."""
    api_cfg = runtime_config.api_server
    if not (api_cfg.enabled and api_cfg.auto_start):
        logger.info("API 服务器已禁用，跳过")
        return None

    host, port = str(api_cfg.host), int(api_cfg.port)

    if not _can_bind_tcp_port(host, port):
        logger.error("API 服务器端口 %d 已被占用，跳过启动", port)
        return None

    import uvicorn
    from apiserver.api_server import app

    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host=host,
            port=port,
            log_level="warning",
            access_log=False,
            ws_ping_interval=None,
            ws_ping_timeout=None,
        )
    )
    server.install_signal_handlers = lambda: None  # type: ignore[method-assign]
    stopped_event = threading.Event()
    shutdown_requested = threading.Event()
    handle = APIServerHandle(
        thread=threading.Thread(),
        server=server,
        host=host,
        port=port,
        stopped_event=stopped_event,
        shutdown_requested=shutdown_requested,
    )

    def _serve() -> None:
        try:
            logger.info("API 服务器启动: %s:%d", host, port)
            server.run()
        except BaseException as exc:
            handle.error = str(exc or "unknown")
            if isinstance(exc, SystemExit):
                logger.error("API 服务器退出: %s", handle.error)
            else:
                logger.exception("API 服务器异常退出: %s", exc)
        finally:
            if not handle.startup_complete and not shutdown_requested.is_set():
                handle.startup_failed = True
                if not handle.error:
                    handle.error = "startup_failed"
            stopped_event.set()

    thread = threading.Thread(target=_serve, name="api-server", daemon=False)
    handle.thread = thread
    thread.start()

    deadline = time.time() + 3.0
    while time.time() < deadline:
        if bool(getattr(server, "started", False)):
            handle.startup_complete = True
            logger.info("API 服务器就绪: http://%s:%d", _resolve_probe_host(host), port)
            return handle
        if stopped_event.wait(timeout=0.05):
            break

    if bool(getattr(server, "started", False)) or _wait_for_tcp_ready(host, port, timeout_seconds=0.2):
        handle.startup_complete = True
        logger.info("API 服务器就绪: http://%s:%d", _resolve_probe_host(host), port)
    elif handle.startup_failed or stopped_event.is_set():
        reason = handle.error or "startup_failed"
        logger.error("API 服务器启动失败: %s", reason)
        handle.startup_failed = True
    else:
        logger.warning("API 服务器启动超时（3s），可能仍在加载")
    return handle


# ---------------------------------------------------------------------------
# Watchdog supervision
# ---------------------------------------------------------------------------

_watchdog_state_file = Path("logs/runtime/watchdog_state.json")


def _run_idle_wait_loop(stop_requested: Callable[[], bool]) -> None:
    """Keep the process alive when the watchdog backend is unavailable."""
    while not stop_requested():
        time.sleep(0.25)


def _run_watchdog(stop_requested: Callable[[], bool]) -> None:
    """Run the watchdog backend in the main thread."""
    try:
        from core.event_bus.event_store import EventStore
        from core.supervisor.watchdog_actuator import WatchdogActuator
        from core.supervisor.watchdog_daemon import WatchdogDaemon, WatchdogThresholds
        from system.config import get_embla_system_config

        _watchdog_state_file.parent.mkdir(parents=True, exist_ok=True)

        event_store = EventStore(file_path=Path("logs/autonomous/events.jsonl"))

        warn_only = bool(get_embla_system_config().get("runtime", {}).get("watchdog_warn_only", True))

        actuator = WatchdogActuator(event_emitter=event_store)
        daemon = WatchdogDaemon(
            thresholds=WatchdogThresholds(),
            event_emitter=event_store,
            warn_only=warn_only,
            actuator_callback=actuator.handle_action,
        )
        logger.info("看门狗已启动 (state=%s, warn_only=%s)", _watchdog_state_file, warn_only)

        # Register production-safe IncidentConsumer (append-only JSONL)
        try:
            from core.event_bus.consumers import register_incident_consumer

            register_incident_consumer(event_store=event_store, repo_root=Path(__file__).resolve().parent)
            logger.info("IncidentConsumer 已注册到事件总线")
        except Exception as exc:
            logger.warning(f"IncidentConsumer 注册失败（降级为无事件消费）: {exc}")

        # Start DLQ auto-retry daemon alongside the watchdog
        _start_dlq_auto_retry(event_store)

        daemon.run_daemon(
            state_file=_watchdog_state_file,
            interval_seconds=10.0,
            stop_requested=stop_requested,
        )
    except ImportError:
        logger.warning("WatchdogDaemon 不可用，进入简单等待循环")
        _run_idle_wait_loop(stop_requested)
    except Exception as exc:
        logger.error("看门狗异常: %s，进入简单等待循环", exc)
        _run_idle_wait_loop(stop_requested)


def _start_dlq_auto_retry(event_store: object) -> None:
    """Start the DLQ auto-retry daemon using the event store's topic bus."""
    try:
        import asyncio

        from core.event_bus.dlq_auto_retry import DLQAutoRetryDaemon

        topic_bus = getattr(event_store, "topic_bus", None)
        if topic_bus is None:
            logger.debug("DLQ auto-retry: event_store has no topic_bus, skipping")
            return

        dlq_daemon = DLQAutoRetryDaemon(topic_bus)

        def _run_dlq_loop() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(dlq_daemon.start())
                loop.run_forever()
            except Exception:
                logger.debug("DLQ auto-retry loop exited")
            finally:
                loop.close()

        dlq_thread = threading.Thread(target=_run_dlq_loop, name="dlq-auto-retry", daemon=True)
        dlq_thread.start()
        logger.info("DLQ 自动重试守护进程已启动")
    except ImportError:
        logger.debug("DLQAutoRetryDaemon not available, skipping")
    except Exception as exc:
        logger.warning("DLQ auto-retry daemon failed to start: %s", exc)


# ---------------------------------------------------------------------------
# Shutdown / runtime orchestrator
# ---------------------------------------------------------------------------

def _install_signal_handlers(stop_event: threading.Event) -> None:
    """Wire SIGTERM and SIGINT to trigger clean shutdown."""

    def _handler(signum: int, frame: object) -> None:
        del frame
        sig_name = signal.Signals(signum).name
        logger.info("收到 %s，正在关闭...", sig_name)
        stop_event.set()

    signal.signal(signal.SIGTERM, _handler)
    signal.signal(signal.SIGINT, _handler)


def _ensure_event_loop() -> None:
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


class EmblaRuntime:
    """Thin service orchestrator for the current default backend entrypoint."""

    def __init__(self, options: StartupOptions, *, runtime_config=config) -> None:
        self.options = options
        self.runtime_config = runtime_config
        self.stop_event = threading.Event()
        self.services = RuntimeServices()
        self._exit_code = 0
        self._brainstem_supervisor: object | None = None
        self._process_guard: object | None = None
        self._process_guard_thread: threading.Thread | None = None
        self._sdlc_orchestrator: object | None = None
        self._chronos_scheduler: object | None = None
        self._stop_config_watcher: Callable | None = None

    def run_diagnostic(self) -> int | None:
        return _run_diagnostic(self.options)

    def run_startup_gate(self) -> bool:
        return _run_startup_gate(self.options)

    def _init_supervisor(self) -> None:
        """Initialise BrainstemSupervisor and ProcessGuardDaemon."""
        try:
            from core.supervisor.brainstem_supervisor import BrainstemServiceSpec, BrainstemSupervisor

            state_file = Path("scratch/runtime/brainstem_supervisor_state.json")
            supervisor = BrainstemSupervisor(state_file=state_file)

            api_cfg = self.runtime_config.api_server
            supervisor.register_service(
                BrainstemServiceSpec(
                    service_name="api_server",
                    command=[sys.executable, "-m", "uvicorn", "apiserver.api_server:app",
                             "--host", str(api_cfg.host), "--port", str(api_cfg.port)],
                    working_dir=str(Path(__file__).resolve().parent),
                    restart_policy="on-failure",
                    max_restarts=3,
                )
            )
            self._brainstem_supervisor = supervisor
            logger.info("BrainstemSupervisor 已初始化 (state=%s)", state_file)
        except Exception as exc:
            logger.warning("BrainstemSupervisor 初始化失败: %s", exc)

        try:
            from core.supervisor.process_guard import ProcessGuardDaemon

            guard = ProcessGuardDaemon()
            guard_state_file = Path("scratch/runtime/process_guard_state.json")

            def _run_guard() -> None:
                try:
                    guard.run_daemon(
                        state_file=guard_state_file,
                        interval_seconds=10.0,
                        max_ticks=1_000_000_000,
                    )
                except Exception as exc:
                    logger.warning("ProcessGuardDaemon 异常退出: %s", exc)

            thread = threading.Thread(target=_run_guard, name="process-guard", daemon=True)
            thread.start()
            self._process_guard = guard
            self._process_guard_thread = thread
            logger.info("ProcessGuardDaemon 已启动 (state=%s)", guard_state_file)
        except Exception as exc:
            logger.warning("ProcessGuardDaemon 初始化失败: %s", exc)

    def _init_chronos_scheduler(self) -> None:
        try:
            from core.scheduler.chronos import get_default_scheduler
            scheduler = get_default_scheduler()
            scheduler.start()
            self._chronos_scheduler = scheduler
            logger.info("Chronos 调度引擎已启动")
        except Exception as exc:
            logger.warning(f"Chronos 调度引擎启动失败（降级为无调度）: {exc}")
            self._chronos_scheduler = None

    def _run_daily_checkpoint(self) -> None:
        """Generate a daily runtime summary snapshot."""
        import json
        from datetime import datetime, timezone
        summary = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "type": "daily_checkpoint",
            "services": {
                "api_server": "running" if self.services.api_server else "stopped",
                "supervisor": "running" if self._brainstem_supervisor else "stopped",
                "chronos": "running" if self._chronos_scheduler else "stopped",
                "sdlc": "running" if self._sdlc_orchestrator and self._sdlc_orchestrator.enabled else "stopped",
            },
        }
        output = Path("scratch/runtime") / f"daily_checkpoint_{datetime.now(timezone.utc).strftime('%Y%m%d')}.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"Daily Checkpoint 已生成: {output}")

    def _register_scheduled_jobs(self) -> None:
        """Register all Chronos scheduled jobs per doc/12 §6 spec."""
        scheduler = self._chronos_scheduler
        if not scheduler:
            return

        jobs = [
            # doc/12:612 — 健康检查 每5分钟
            ("health_check", "*/5 * * * *", self._run_health_check),
            # doc/12:610 — 巡检 每6小时
            ("patrol", "0 */6 * * *", self._run_patrol),
            # doc/12:611 — 备份(daily checkpoint) 每天3点
            ("daily_checkpoint", "0 3 * * *", self._run_daily_checkpoint),
            # 自进化评估 每小时
            ("evolution_eval", "0 * * * *", self._run_evolution_eval),
            # agent 自唤醒 每30分钟检查待处理任务
            ("agent_wakeup", "*/30 * * * *", self._run_agent_wakeup),
            # worktree GC 每6小时清理孤儿/过期 worktree
            ("worktree_gc", "30 */6 * * *", self._run_worktree_gc),
        ]
        for job_id, cron_expr, func in jobs:
            try:
                scheduler.add_cron_job(job_id=job_id, func=func, cron_expr=cron_expr)
                logger.info(f"定时任务已注册: {job_id} ({cron_expr})")
            except Exception as exc:
                logger.warning(f"定时任务注册失败 {job_id}: {exc}")

    def _run_health_check(self) -> None:
        """5-minute health check — verify core services are alive."""
        import json
        from datetime import datetime, timezone
        status = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "type": "health_check",
            "api_server": "running" if self.services.api_server and not self.services.api_server.startup_failed else "down",
            "supervisor": "running" if self._brainstem_supervisor else "stopped",
            "chronos": "running" if self._chronos_scheduler and self._chronos_scheduler.is_running else "stopped",
        }
        output = Path("scratch/runtime/health_check_latest.json")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
        # Emit event for dashboard
        try:
            from core.event_bus.event_store import EventStore
            store = EventStore(file_path=Path("logs/autonomous/events.jsonl"))
            severity = "info" if status["api_server"] == "running" else "critical"
            store.emit("HealthCheckCompleted", status, source="chronos.health_check", severity=severity)
        except Exception:
            pass

    def _run_patrol(self) -> None:
        """6-hour patrol — comprehensive system inspection."""
        import json
        from datetime import datetime, timezone
        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "type": "patrol",
            "checks": {},
        }
        # Check DNA integrity
        try:
            from core.security.immutable_dna import ImmutableDNALoader
            loader = ImmutableDNALoader(
                root_dir=Path("system/prompts"),
                manifest_path=Path("system/prompts/immutable_dna_manifest.spec"),
            )
            result = loader.verify()
            report["checks"]["dna_integrity"] = {"ok": result.ok, "reason": result.reason}
        except Exception as exc:
            report["checks"]["dna_integrity"] = {"ok": False, "reason": str(exc)}
        # Check audit ledger
        try:
            ledger_path = Path("scratch/runtime/audit_ledger.jsonl")
            report["checks"]["audit_ledger"] = {"exists": ledger_path.exists(), "size_bytes": ledger_path.stat().st_size if ledger_path.exists() else 0}
        except Exception:
            report["checks"]["audit_ledger"] = {"exists": False}
        # Check event bus
        try:
            from core.event_bus.event_store import EventStore
            store = EventStore(file_path=Path("logs/autonomous/events.jsonl"))
            topics = store.list_topics(limit=50)
            report["checks"]["event_bus"] = {"topic_count": len(topics), "status": "ok"}
        except Exception as exc:
            report["checks"]["event_bus"] = {"status": "error", "error": str(exc)}

        output = Path("scratch/runtime") / f"patrol_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"巡检完成: {output}")

    def _run_evolution_eval(self) -> None:
        """Hourly evolution evaluation — perceive → attribute → propose → execute → verify."""
        try:
            from agents.evolution.evolution_trigger import EvolutionTrigger
            from agents.evolution.evolution_orchestrator import EvolutionOrchestrator
            from core.event_bus.event_store import EventStore

            store = EventStore(file_path=Path("logs/autonomous/events.jsonl"))

            # Load self_evolution config
            evo_config: dict = {}
            try:
                from system.config import get_embla_system_config
                sys_cfg = get_embla_system_config()
                evo_config = dict(
                    (sys_cfg.get("autonomous", {}) or {}).get("self_evolution", {}) or {}
                )
            except Exception:
                pass

            if not evo_config.get("enabled", True):
                logger.debug("进化评估: disabled in config")
                return

            trigger_threshold = int(evo_config.get("trigger_threshold", 3))
            max_per_day = int(evo_config.get("max_evolutions_per_day", 5))

            trigger = EvolutionTrigger(
                episodic_dir=Path("memory/episodic"),
                trigger_threshold=trigger_threshold,
                max_per_day=max_per_day,
                event_emitter=store,
            )
            decision = trigger.evaluate()

            if not decision.should_evolve:
                logger.debug(f"进化评估: {decision.reason}")
                return

            logger.info(f"进化触发: {decision.reason}")
            store.emit("EvolutionEvalTriggered", {
                "reason": decision.reason,
                "signal_count": len(decision.signals),
                "top_task_type": decision.signals[0].task_type if decision.signals else "",
            }, source="chronos.evolution_eval", severity="info")

            # Run the full evolution cycle: attribute → propose → execute/queue → verify
            orchestrator = EvolutionOrchestrator(
                episodic_dir=Path("memory/episodic"),
                project_root=Path("."),
                config=evo_config,
                event_emitter=store,
            )
            cycle_result = orchestrator.run_cycle(decision.signals)

            if cycle_result.acted:
                logger.info(
                    "进化周期完成: applied=%d, queued=%d, skipped=%d, errors=%d",
                    cycle_result.applied_count, cycle_result.queued_count,
                    cycle_result.skipped_count, len(cycle_result.errors),
                )
            elif cycle_result.queued_count > 0:
                logger.info(
                    "进化提案已排队: queued=%d (auto_approve=false)",
                    cycle_result.queued_count,
                )
            else:
                reasons = [a.category for a in cycle_result.attributions]
                logger.info("进化评估完成但未操作: attributions=%s", reasons or "none")

        except Exception as exc:
            logger.debug(f"进化评估失败: {exc}", exc_info=True)

    def _run_agent_wakeup(self) -> None:
        """30-minute agent wakeup — check for pending/blocked tasks and trigger recovery."""
        try:
            from agents.runtime.agent_session import AgentSessionStore, AgentStatus
            store = AgentSessionStore(db_path="scratch/runtime/agent_sessions.db")
            waiting_sessions = []
            blocked_sessions = []
            for session in store.list_sessions():
                metadata = session.metadata or {}
                if session.status == AgentStatus.WAITING:
                    pending_jobs = metadata.get("core_job_recovery_state", {}).get("pending_job_ids", [])
                    if pending_jobs:
                        waiting_sessions.append({
                            "session_id": session.session_id,
                            "role": session.role,
                            "pending_jobs": len(pending_jobs),
                        })
                # Detect blocked Core sessions eligible for recovery
                heartbeat_level = str(metadata.get("heartbeat_last_stale_level") or "").strip()
                if heartbeat_level == "blocked" and str(session.role or "").strip().lower() == "core":
                    blocked_sessions.append({
                        "session_id": session.session_id,
                        "role": session.role,
                        "blocked_task": str(metadata.get("heartbeat_blocked_task_id") or ""),
                    })

            signal_payload = {}
            if waiting_sessions:
                logger.info(f"Agent 唤醒检查: {len(waiting_sessions)} 个会话有待处理任务")
                signal_payload["waiting_count"] = len(waiting_sessions)
                signal_payload["sessions"] = waiting_sessions[:5]
            if blocked_sessions:
                logger.info(f"Agent 唤醒检查: {len(blocked_sessions)} 个 Core 会话处于 blocked 状态，触发恢复")
                signal_payload["blocked_count"] = len(blocked_sessions)
                signal_payload["blocked_sessions"] = blocked_sessions[:5]

            if signal_payload:
                try:
                    from core.event_bus.event_store import EventStore
                    evt_store = EventStore(file_path=Path("logs/autonomous/events.jsonl"))
                    evt_store.emit("AgentWakeupSignal", signal_payload, source="chronos.agent_wakeup", severity="info")
                except Exception:
                    pass

            # Trigger Core job manager recovery for blocked sessions
            if blocked_sessions:
                try:
                    from apiserver.api_server import _get_core_job_manager
                    job_manager = _get_core_job_manager()
                    for bs in blocked_sessions:
                        job_manager._recover_shell_state(str(bs.get("session_id") or ""))
                except Exception:
                    logger.debug("Core blocked session recovery trigger failed", exc_info=True)

            store.close()
        except Exception as exc:
            logger.debug(f"Agent 唤醒检查失败: {exc}")

    def _run_worktree_gc(self) -> None:
        """6-hour worktree garbage collection — remove orphaned/stale agent worktrees."""
        try:
            from agents.runtime.agent_session import AgentSessionStore
            from system.git_worktree_sandbox import gc_sweep_stale_worktrees

            store = AgentSessionStore(db_path="scratch/runtime/agent_sessions.db")
            active_ids = {s.session_id for s in store.list_sessions()}
            store.close()

            result = gc_sweep_stale_worktrees(
                active_session_ids=active_ids,
                max_age_hours=2.0,
                dry_run=False,
            )

            cleaned = result.get("cleaned", [])
            errors = result.get("errors", [])
            logger.info(
                "Worktree GC 完成: cleaned=%d skipped=%d errors=%d",
                len(cleaned),
                len(result.get("skipped", [])),
                len(errors),
            )

            try:
                from core.event_bus.event_store import EventStore
                evt_store = EventStore(file_path=Path("logs/autonomous/events.jsonl"))
                evt_store.emit(
                    "WorktreeGCCompleted",
                    {
                        "cleaned_count": len(cleaned),
                        "error_count": len(errors),
                        "cleaned_owners": cleaned[:10],
                    },
                    source="chronos.worktree_gc",
                    severity="info" if not errors else "warning",
                )
            except Exception:
                pass
        except Exception as exc:
            logger.debug(f"Worktree GC 失败: {exc}", exc_info=True)

    def _init_sdlc_orchestrator(self) -> None:
        """Initialise the SDLC orchestrator if autonomous_runtime.yaml enables it."""
        try:
            import yaml

            from core.sdlc.orchestrator import SDLCOrchestrator

            config_path = Path("config/autonomous_runtime.yaml")
            sdlc_cfg: dict = {}
            sdlc_enabled = False
            if config_path.exists():
                try:
                    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
                    autonomous = cfg.get("autonomous") or {}
                    sdlc_cfg = autonomous.get("sdlc") or {}
                    sdlc_enabled = bool(sdlc_cfg.get("enabled", False))
                except Exception:
                    pass

            project_root = Path(__file__).resolve().parent
            event_emitter = None
            try:
                from core.event_bus.event_store import EventStore

                event_emitter = EventStore(file_path=Path("logs/autonomous/events.jsonl"))
            except Exception:
                pass

            orchestrator = SDLCOrchestrator(
                project_root=project_root,
                event_emitter=event_emitter,
                enabled=sdlc_enabled,
                stages=sdlc_cfg.get("stages"),
                auto_advance=bool(sdlc_cfg.get("auto_advance", False)),
            )
            orchestrator.start()
            self._sdlc_orchestrator = orchestrator
            logger.info("SDLC 编排器初始化完成 (enabled=%s)", sdlc_enabled)
        except Exception as exc:
            logger.warning("SDLC 编排器初始化失败: %s", exc)

    def _start_config_watcher(self) -> None:
        """Start the config file watcher daemon thread."""
        try:
            from system.config_manager import start_config_watcher, stop_config_watcher

            start_config_watcher()
            self._stop_config_watcher = stop_config_watcher
            logger.info("配置文件监控已启动")
        except Exception as exc:
            logger.warning("配置文件监控启动失败: %s", exc)

    def initialize_services(self) -> None:
        _init_boxlite_runtime()
        self.services.boxlite_reconciler = _start_boxlite_runtime_reconciler(self._should_stop_supervision)
        _init_memory()
        _init_mcp()
        self._init_supervisor()
        self._init_chronos_scheduler()
        self._register_scheduled_jobs()
        self._init_sdlc_orchestrator()
        self._start_config_watcher()
        self.services.api_server = _start_api_server(runtime_config=self.runtime_config)
        self.services.api_started = bool(self.services.api_server and self.services.api_server.startup_complete)
        if self.services.api_server and self.services.api_server.startup_failed:
            raise RuntimeError(self.services.api_server.error or "api_startup_failed")

    def install_signal_handlers(self) -> None:
        _install_signal_handlers(self.stop_event)

    def _should_stop_supervision(self) -> bool:
        if self.stop_event.is_set():
            return True
        handle = self.services.api_server
        if handle and handle.startup_complete and handle.stopped_event.is_set() and not handle.shutdown_requested.is_set():
            self._exit_code = 1
            self.stop_event.set()
            logger.error("API 服务器意外退出: %s", handle.error or "unknown")
            return True
        return False

    def run_supervision_loop(self) -> None:
        _run_watchdog(self._should_stop_supervision)

    def shutdown_services(self) -> None:
        thread = self.services.boxlite_reconciler
        if thread is not None:
            thread.join(timeout=2.0)
            if thread.is_alive():
                logger.warning("BoxLite runtime reconciler did not exit within 2s")
            self.services.boxlite_reconciler = None

        handle = self.services.api_server
        if handle is not None:
            logger.info("正在关闭 API 服务器: %s:%d", handle.host, handle.port)
            handle.shutdown_requested.set()
            try:
                setattr(handle.server, "should_exit", True)
            except Exception:
                pass
            if handle.thread.is_alive():
                handle.thread.join(timeout=5.0)
            if handle.thread.is_alive():
                logger.warning("API 服务器未在 5s 内退出，尝试强制关闭")
                try:
                    setattr(handle.server, "force_exit", True)
                except Exception:
                    pass
                handle.thread.join(timeout=1.0)
            if handle.thread.is_alive():
                logger.error("API 服务器线程仍未退出，端口可能仍被占用: %s:%d", handle.host, handle.port)
            elif handle.startup_complete:
                released = _wait_for_tcp_release(handle.host, handle.port, timeout_seconds=2.0)
                if released:
                    logger.info("API 服务器端口已释放: %s:%d", handle.host, handle.port)
                else:
                    logger.warning("API 服务器线程已退出，但端口仍未确认释放: %s:%d", handle.host, handle.port)
            self.services.api_server = None
            self.services.api_started = False

        # Cleanup BrainstemSupervisor and ProcessGuardDaemon
        if self._process_guard_thread is not None:
            self._process_guard_thread.join(timeout=2.0)
            if self._process_guard_thread.is_alive():
                logger.warning("ProcessGuardDaemon 线程未在 2s 内退出")
            self._process_guard_thread = None
            self._process_guard = None

        self._brainstem_supervisor = None

        # Cleanup Chronos scheduler
        if self._chronos_scheduler:
            try:
                self._chronos_scheduler.shutdown()
            except Exception as exc:
                logger.warning("Chronos 调度引擎关闭异常: %s", exc)
            self._chronos_scheduler = None

        # Cleanup SDLC orchestrator
        if self._sdlc_orchestrator is not None:
            try:
                self._sdlc_orchestrator.shutdown()
            except Exception as exc:
                logger.warning("SDLC 编排器关闭异常: %s", exc)
            self._sdlc_orchestrator = None

        # Cleanup config watcher
        if self._stop_config_watcher is not None:
            try:
                self._stop_config_watcher()
            except Exception as exc:
                logger.warning("配置文件监控关闭异常: %s", exc)
            self._stop_config_watcher = None

        cleanup_report = close_runtime_network_clients_sync()
        litellm_error = str(((cleanup_report.get("litellm") or {}).get("error")) or "").strip()
        mcp_error = str(((cleanup_report.get("mcp_pool") or {}).get("error")) or "").strip()
        if litellm_error or mcp_error:
            logger.warning(
                "运行时网络客户端关闭存在异常: litellm=%s mcp_pool=%s",
                litellm_error or "ok",
                mcp_error or "ok",
            )

    def run(self) -> int:
        diag = self.run_diagnostic()
        if diag is not None:
            return diag
        runtime_prepare = _run_prepare_runtime(self.options)
        if runtime_prepare is not None:
            return runtime_prepare

        if not self.run_startup_gate():
            return 1

        logger.info("正在启动 %s...", AI_NAME)
        _ensure_event_loop()
        try:
            self.initialize_services()
            self.install_signal_handlers()
        except Exception as exc:
            logger.error("服务初始化失败: %s", exc)
            self._exit_code = 1
            self.stop_event.set()
            self.shutdown_services()
            return self._exit_code

        logger.info("默认服务已启动，进入运行监控循环")
        try:
            self.run_supervision_loop()
        except KeyboardInterrupt:
            self.stop_event.set()
        finally:
            self.shutdown_services()

        logger.info("Embla System 已关闭")
        return self._exit_code


def main(argv: list[str] | None = None) -> int:
    runtime = EmblaRuntime(parse_args(argv))
    return runtime.run()


if __name__ == "__main__":
    raise SystemExit(main())
