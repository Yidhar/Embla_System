"""Shared utility functions for apiserver route modules.

Extracted from api_server.py Phase 0 split. These are stateless helpers
used by multiple route modules (ops, brainstem, chat, etc.).
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def env_flag(name: str, default: bool) -> bool:
    """Parse boolean from environment variable."""
    raw = os.environ.get(str(name))
    if raw is None:
        return bool(default)
    normalized = str(raw).strip().lower()
    if not normalized:
        return bool(default)
    return normalized in {"1", "true", "yes", "on", "y"}


def env_float(name: str, default: float) -> float:
    """Parse float from environment variable."""
    raw = os.environ.get(str(name))
    if raw is None:
        return float(default)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return float(default)


def ops_utc_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ops_repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def ops_unix_path(path: Path) -> str:
    return str(path).replace("\\", "/")


def ops_status_to_severity(status: str) -> str:
    normalized = str(status or "unknown").strip().lower()
    if normalized in {"ok", "healthy", "success"}:
        return "ok"
    if normalized in {"warning", "warn"}:
        return "warning"
    if normalized in {"critical", "error", "failed", "fail"}:
        return "critical"
    return "unknown"


OPS_STATUS_RANK: Dict[str, int] = {
    "unknown": 0,
    "ok": 1,
    "warning": 2,
    "critical": 3,
}


def ops_metric_status(value: Any) -> str:
    if not isinstance(value, dict):
        return "unknown"
    return ops_status_to_severity(str(value.get("status") or "unknown"))


def ops_max_status(statuses: List[str]) -> str:
    current = "unknown"
    current_rank = OPS_STATUS_RANK[current]
    for status in statuses:
        normalized = ops_status_to_severity(status)
        rank = OPS_STATUS_RANK.get(normalized, 0)
        if rank > current_rank:
            current = normalized
            current_rank = rank
    return current


def ops_safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def ops_read_json_file(path: Path) -> Optional[Dict[str, Any]]:
    try:
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return None
        return payload
    except Exception:
        return None


def ops_parse_iso_datetime(value: Any) -> Optional[float]:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


__all__ = [
    "env_flag",
    "env_float",
    "ops_utc_iso_now",
    "ops_repo_root",
    "ops_unix_path",
    "ops_status_to_severity",
    "OPS_STATUS_RANK",
    "ops_metric_status",
    "ops_max_status",
    "ops_safe_int",
    "ops_read_json_file",
    "ops_parse_iso_datetime",
]
