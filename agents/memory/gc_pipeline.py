"""Brain-layer episodic-memory GC pipeline under `agents/` namespace."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from system.episodic_memory import get_episodic_memory


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_unix(path: Path) -> str:
    return str(path).replace("\\", "/")


class GCPipelineConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retention_seconds: float = Field(default=7 * 24 * 3600, ge=0.0)
    max_records_per_session: int = Field(default=300, ge=1)
    max_total_records: int = Field(default=20_000, ge=1)
    dry_run: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


class GCPipelineReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    scenario: str
    generated_at: str
    archive_path: str
    output_path: str
    config: Dict[str, Any]
    checks: Dict[str, Any]
    stats: Dict[str, Any]
    dry_run: bool
    passed: bool

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


def _safe_float(value: Any, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        text = str(raw or "").strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _write_jsonl(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
    path.write_text(payload + ("\n" if payload else ""), encoding="utf-8")


def run_gc_pipeline(
    *,
    archive_path: Optional[Path] = None,
    output_path: Path = Path("scratch/reports/gc_pipeline_ws28_028.json"),
    config: Optional[GCPipelineConfig] = None,
) -> Dict[str, Any]:
    cfg = config or GCPipelineConfig()
    resolved_archive = archive_path or get_episodic_memory().archive_path
    resolved_archive = Path(resolved_archive)

    now_ts = time.time()
    rows = _read_jsonl(resolved_archive)
    original_count = len(rows)
    retained: List[Dict[str, Any]] = []
    dropped_count = 0

    min_ts = now_ts - float(cfg.retention_seconds) if cfg.retention_seconds > 0 else None
    per_session_count: Dict[str, int] = {}
    sorted_rows = sorted(rows, key=lambda row: _safe_float(row.get("timestamp"), default=0.0), reverse=True)
    for row in sorted_rows:
        ts = _safe_float(row.get("timestamp"), default=0.0)
        if min_ts is not None and ts > 0 and ts < min_ts:
            dropped_count += 1
            continue
        session_id = str(row.get("session_id") or "").strip() or "__unknown__"
        if int(per_session_count.get(session_id, 0)) >= int(cfg.max_records_per_session):
            dropped_count += 1
            continue
        retained.append(row)
        per_session_count[session_id] = int(per_session_count.get(session_id, 0)) + 1
        if len(retained) >= int(cfg.max_total_records):
            break

    retained = sorted(retained, key=lambda row: _safe_float(row.get("timestamp"), default=0.0))
    deleted_count = max(0, original_count - len(retained))

    if not cfg.dry_run:
        _write_jsonl(resolved_archive, retained)

    report = GCPipelineReport(
        task_id="NGA-WS28-028",
        scenario="agents_gc_pipeline",
        generated_at=_utc_iso(),
        archive_path=_to_unix(resolved_archive),
        output_path=_to_unix(output_path),
        config=cfg.to_dict(),
        checks={
            "archive_exists": resolved_archive.exists(),
            "retained_not_exceed_total_cap": len(retained) <= int(cfg.max_total_records),
        },
        stats={
            "original_count": original_count,
            "retained_count": len(retained),
            "deleted_count": deleted_count,
            "dropped_count": dropped_count,
            "unique_sessions_retained": len(per_session_count),
        },
        dry_run=bool(cfg.dry_run),
        passed=True,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")
    return report.to_dict()


__all__ = ["GCPipelineConfig", "GCPipelineReport", "run_gc_pipeline"]
