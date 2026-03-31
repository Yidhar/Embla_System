#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unified logging setup."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

IS_PACKAGED: bool = getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def _resolve_log_dir() -> Path:
    """Resolve root log directory (`logs/`)."""
    if IS_PACKAGED:
        install_dir = Path(sys._MEIPASS).parent.parent  # type: ignore[attr-defined]
        return install_dir / "logs"
    return Path(__file__).resolve().parent.parent / "logs"


def setup_logging() -> None:
    """Initialize process-wide logging."""
    log_dir = _resolve_log_dir()
    details_dir = log_dir / "details"
    details_dir.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    backend_handler = RotatingFileHandler(
        details_dir / "embla-backend.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    backend_handler.setLevel(logging.DEBUG)
    backend_handler.setFormatter(fmt)

    console_handler = logging.StreamHandler(stream=sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(backend_handler)
    root.addHandler(console_handler)

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

    for name in ["LiteLLM", "litellm"]:
        ll_logger = logging.getLogger(name)
        ll_logger.setLevel(logging.CRITICAL)
        ll_logger.propagate = False
        if ll_logger.handlers:
            ll_logger.handlers.clear()
