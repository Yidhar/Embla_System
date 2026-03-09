#!/usr/bin/env python3
"""NagaAgent — unified entry point.

Starts the API server in a daemon thread, initialises MCP & memory subsystems,
and runs a WatchdogDaemon loop on the main thread for health monitoring.
"""
# ruff: noqa: E402
from __future__ import annotations

import argparse
import asyncio
import locale
import logging
import os
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

# Suppress noisy deprecation warnings from dependencies
warnings.filterwarnings("ignore", category=DeprecationWarning, module="websockets")
warnings.filterwarnings("ignore", category=DeprecationWarning, module="uvicorn")

# Fix missing Windows socket constants
if not hasattr(socket, "EAI_ADDRFAMILY"):
    for attr, val in [
        ("EAI_ADDRFAMILY", -9), ("EAI_AGAIN", -3), ("EAI_BADFLAGS", -1),
        ("EAI_FAIL", -4), ("EAI_MEMORY", -10), ("EAI_NODATA", -5),
        ("EAI_NONAME", -2), ("EAI_OVERFLOW", -12), ("EAI_SERVICE", -8),
        ("EAI_SOCKTYPE", -7), ("EAI_SYSTEM", -11),
    ]:
        setattr(socket, attr, val)

# ---------------------------------------------------------------------------
# Logging — single unified setup for the whole process
# ---------------------------------------------------------------------------

from system.logging_setup import setup_logging

setup_logging()
logger = logging.getLogger("nagaagent")

# Quiet noisy libraries
logging.getLogger("OpenGL").setLevel(logging.WARNING)
logging.getLogger("OpenGL.acceleratesupport").setLevel(logging.WARNING)

# ---------------------------------------------------------------------------
# Local imports (after logging is ready)
# ---------------------------------------------------------------------------

from system.config import config, AI_NAME
from system.system_checker import run_system_check, run_quick_check

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


def parse_args(argv: list[str] | None = None) -> StartupOptions:
    parser = argparse.ArgumentParser(description="NagaAgent — 智能运行入口")
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
# Service initialisation
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


def _init_mcp() -> None:
    """Initialise the standard MCP client pool."""
    try:
        from agents.runtime.mcp_client import get_mcp_pool
        pool = get_mcp_pool()
        if pool:
            tools = pool.get_all_tools()
            logger.info("MCP 客户端就绪，已发现 %d 个工具", len(tools))
        else:
            logger.info("MCP 客户端: 无已配置服务器")
    except Exception as exc:
        logger.error("MCP 客户端初始化失败: %s", exc)


def _start_api_server() -> None:
    """Start the uvicorn API server in a daemon thread."""
    api_cfg = config.api_server
    if not (api_cfg.enabled and api_cfg.auto_start):
        logger.info("API 服务器已禁用，跳过")
        return

    host, port = api_cfg.host, api_cfg.port

    # Check port availability
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((host, port))
    except OSError:
        logger.error("API 服务器端口 %d 已被占用，跳过启动", port)
        return

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

    t = threading.Thread(target=_serve, name="api-server", daemon=True)
    t.start()

    # Wait for the port to become connectable (max 3s)
    for _ in range(15):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.1)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                logger.info("API 服务器就绪: http://%s:%d", host, port)
                return
        time.sleep(0.2)
    logger.warning("API 服务器启动超时（3s），可能仍在加载")

# ---------------------------------------------------------------------------
# Watchdog — replaces the old _wait_forever() sleep loop
# ---------------------------------------------------------------------------

_watchdog_state_file = Path("logs/runtime/watchdog_state.json")


def _run_watchdog(stop_event: threading.Event) -> None:
    """Run the WatchdogDaemon in the main thread.

    Monitors CPU, memory, disk usage and writes state to a JSON file.
    Exits cleanly when *stop_event* is set (e.g. via signal handler).
    """
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
        logger.warning("WatchdogDaemon 不可用，回退到简单等待循环")
        _fallback_wait(stop_event)
    except Exception as exc:
        logger.error("看门狗异常: %s，回退到简单等待循环", exc)
        _fallback_wait(stop_event)


def _fallback_wait(stop_event: threading.Event) -> None:
    """Simple wait loop when WatchdogDaemon is unavailable."""
    while not stop_event.is_set():
        stop_event.wait(timeout=5.0)

# ---------------------------------------------------------------------------
# Shutdown
# ---------------------------------------------------------------------------

def _install_signal_handlers(stop_event: threading.Event) -> None:
    """Wire SIGTERM and SIGINT to trigger clean shutdown."""
    def _handler(signum: int, frame: object) -> None:
        sig_name = signal.Signals(signum).name
        logger.info("收到 %s，正在关闭...", sig_name)
        stop_event.set()

    signal.signal(signal.SIGTERM, _handler)
    signal.signal(signal.SIGINT, _handler)

# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def _ensure_event_loop() -> None:
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


def main(argv: list[str] | None = None) -> int:
    opts = parse_args(argv)

    # Diagnostic-only mode
    diag = _run_diagnostic(opts)
    if diag is not None:
        return diag

    # Startup gate
    if not _run_startup_gate(opts):
        return 1

    logger.info("正在启动 %s...", AI_NAME)
    _ensure_event_loop()

    # Initialise subsystems
    _init_memory()
    _init_mcp()

    # Start API server
    _start_api_server()

    # Watchdog supervision loop (main thread)
    stop_event = threading.Event()
    _install_signal_handlers(stop_event)

    logger.info("所有服务已启动，进入看门狗监控循环")
    try:
        _run_watchdog(stop_event)
    except KeyboardInterrupt:
        pass

    logger.info("NagaAgent 已关闭")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
