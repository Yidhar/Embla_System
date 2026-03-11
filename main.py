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

    @property
    def effective_headless(self) -> bool:
        return bool(self.headless or not sys.stdin.isatty())


@dataclass
class RuntimeServices:
    api_thread: threading.Thread | None = None
    api_started: bool = False


def parse_args(argv: list[str] | None = None) -> StartupOptions:
    parser = argparse.ArgumentParser(description="Embla System — 统一运行入口")
    parser.add_argument("--check-env", action="store_true", help="运行系统环境检测")
    parser.add_argument("--quick-check", action="store_true", help="运行快速环境检测")
    parser.add_argument("--force-check", action="store_true", help="强制检测（忽略缓存）")
    parser.add_argument("--headless", action="store_true", help="无头模式（跳过交互提示）")
    ns = parser.parse_args(argv)
    return StartupOptions(
        check_env=bool(ns.check_env),
        quick_check=bool(ns.quick_check),
        force_check=bool(ns.force_check),
        headless=bool(ns.headless),
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
        from system.boxlite.manager import load_boxlite_runtime_settings, probe_boxlite_runtime

        settings = load_boxlite_runtime_settings()
        if not bool(getattr(settings, "enabled", False)):
            logger.info("BoxLite runtime disabled")
            return

        status = probe_boxlite_runtime(settings)
        if bool(getattr(status, "available", False)):
            logger.info("BoxLite runtime ready (%s, working_dir=%s)", getattr(status, "provider", "sdk"), getattr(status, "working_dir", "/workspace"))
        else:
            logger.warning("BoxLite runtime unavailable: %s", getattr(status, "reason", "unknown") or "unknown")
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


def _start_api_server(*, runtime_config=config) -> threading.Thread | None:
    """Start the uvicorn API server in a daemon thread."""
    api_cfg = runtime_config.api_server
    if not (api_cfg.enabled and api_cfg.auto_start):
        logger.info("API 服务器已禁用，跳过")
        return None

    host, port = str(api_cfg.host), int(api_cfg.port)

    if not _can_bind_tcp_port(host, port):
        logger.error("API 服务器端口 %d 已被占用，跳过启动", port)
        return None

    def _serve() -> None:
        try:
            import uvicorn
            from apiserver.api_server import app

            logger.info("API 服务器启动: %s:%d", host, port)
            uvicorn.run(
                app,
                host=host,
                port=port,
                log_level="warning",
                access_log=False,
                ws_ping_interval=None,
                ws_ping_timeout=None,
            )
        except Exception as exc:
            logger.error("API 服务器异常退出: %s", exc)

    thread = threading.Thread(target=_serve, name="api-server", daemon=True)
    thread.start()

    if _wait_for_tcp_ready(host, port, timeout_seconds=3.0):
        logger.info("API 服务器就绪: http://%s:%d", _resolve_probe_host(host), port)
    else:
        logger.warning("API 服务器启动超时（3s），可能仍在加载")
    return thread


# ---------------------------------------------------------------------------
# Watchdog supervision
# ---------------------------------------------------------------------------

_watchdog_state_file = Path("logs/runtime/watchdog_state.json")


def _run_idle_wait_loop(stop_event: threading.Event) -> None:
    """Keep the process alive when the watchdog backend is unavailable."""
    while not stop_event.is_set():
        stop_event.wait(timeout=5.0)


def _run_watchdog(stop_event: threading.Event) -> None:
    """Run the watchdog backend in the main thread."""
    try:
        from core.supervisor.watchdog_daemon import WatchdogDaemon, WatchdogThresholds

        _watchdog_state_file.parent.mkdir(parents=True, exist_ok=True)
        daemon = WatchdogDaemon(
            thresholds=WatchdogThresholds(),
            warn_only=True,
        )
        logger.info("看门狗已启动 (state=%s)", _watchdog_state_file)
        daemon.run_daemon(
            state_file=_watchdog_state_file,
            interval_seconds=10.0,
            stop_requested=stop_event.is_set,
        )
    except ImportError:
        logger.warning("WatchdogDaemon 不可用，进入简单等待循环")
        _run_idle_wait_loop(stop_event)
    except Exception as exc:
        logger.error("看门狗异常: %s，进入简单等待循环", exc)
        _run_idle_wait_loop(stop_event)


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

    def run_diagnostic(self) -> int | None:
        return _run_diagnostic(self.options)

    def run_startup_gate(self) -> bool:
        return _run_startup_gate(self.options)

    def initialize_services(self) -> None:
        _init_boxlite_runtime()
        _init_memory()
        _init_mcp()
        self.services.api_thread = _start_api_server(runtime_config=self.runtime_config)
        self.services.api_started = self.services.api_thread is not None

    def install_signal_handlers(self) -> None:
        _install_signal_handlers(self.stop_event)

    def run_supervision_loop(self) -> None:
        _run_watchdog(self.stop_event)

    def run(self) -> int:
        diag = self.run_diagnostic()
        if diag is not None:
            return diag

        if not self.run_startup_gate():
            return 1

        logger.info("正在启动 %s...", AI_NAME)
        _ensure_event_loop()
        self.initialize_services()
        self.install_signal_handlers()

        logger.info("默认服务已启动，进入运行监控循环")
        try:
            self.run_supervision_loop()
        except KeyboardInterrupt:
            pass

        logger.info("Embla System 已关闭")
        return 0


def main(argv: list[str] | None = None) -> int:
    runtime = EmblaRuntime(parse_args(argv))
    return runtime.run()


if __name__ == "__main__":
    raise SystemExit(main())
