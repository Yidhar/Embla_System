#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一日志管理

所有环境下均将详细日志写入 logs/details/ 文件夹，支持轮转。
"""

import sys
import logging
from pathlib import Path
from logging.handlers import RotatingFileHandler

# 是否为 PyInstaller 打包环境
IS_PACKAGED: bool = getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def _resolve_log_dir() -> Path:
    """推导日志根目录（logs/）"""
    if IS_PACKAGED:
        install_dir = Path(sys._MEIPASS).parent.parent  # type: ignore[attr-defined]
        return install_dir / "logs"
    else:
        return Path(__file__).resolve().parent.parent / "logs"


def setup_logging() -> None:
    """统一初始化日志系统，所有环境均写入文件日志"""
    log_dir = _resolve_log_dir()
    details_dir = log_dir / "details"
    details_dir.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    # 详细日志 → logs/details/naga-backend.log
    backend_handler = RotatingFileHandler(
        details_dir / "naga-backend.log",
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding="utf-8",
    )
    backend_handler.setLevel(logging.DEBUG)
    backend_handler.setFormatter(fmt)

    # OpenClaw 专用 → logs/details/openclaw.log
    openclaw_handler = RotatingFileHandler(
        details_dir / "openclaw.log",
        maxBytes=5 * 1024 * 1024,  # 5MB
        backupCount=3,
        encoding="utf-8",
    )
    openclaw_handler.setLevel(logging.DEBUG)
    openclaw_handler.setFormatter(fmt)

    # 控制台 Handler — 简洁输出
    console_handler = logging.StreamHandler(stream=sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )

    # 配置 root logger
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(backend_handler)
    root.addHandler(console_handler)

    # OpenClaw 命名空间额外写入专用日志
    logging.getLogger("agentserver.openclaw").addHandler(openclaw_handler)

    # 抑制第三方库噪音
    for name in [
        "httpcore",
        "httpx",
        "urllib3",
        "asyncio",
        "openai",
        "openai._base_client",
        "py2neo",
        "py2neo.client",
        "py2neo.client.bolt",
    ]:
        logging.getLogger(name).setLevel(logging.WARNING)

    # LiteLLM 在 provider 推断失败时会输出额外提示（如 Provider List 链接），
    # 这里强制降噪，避免污染后端控制台。
    for name in ["LiteLLM", "litellm"]:
        ll_logger = logging.getLogger(name)
        ll_logger.setLevel(logging.CRITICAL)
        ll_logger.propagate = False
        if ll_logger.handlers:
            ll_logger.handlers.clear()
