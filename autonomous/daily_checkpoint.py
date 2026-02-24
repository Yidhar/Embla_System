"""WS19-007 daily checkpoint archive and recovery card generator."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


def _utc_iso(ts: Optional[float] = None) -> str:
    value = time.time() if ts is None else float(ts)
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _truncate(text: str, limit: int) -> str:
    raw = _safe_text(text).strip()
    if len(raw) <= limit:
        return raw
    if limit <= 3:
        return raw[:limit]
    return raw[: limit - 3] + "..."


@dataclass(frozen=True)
class DailyCheckpointConfig:
    window_hours: int = 24
    top_items: int = 5
    summary_line_limit: int = 6
    summary_item_chars: int = 180

    def normalized(self) -> "DailyCheckpointConfig":
        return DailyCheckpointConfig(
            window_hours=max(1, int(self.window_hours)),
            top_items=max(1, int(self.top_items)),
            summary_line_limit=max(1, int(self.summary_line_limit)),
            summary_item_chars=max(40, int(self.summary_item_chars)),
        )


@dataclass(frozen=True)
class DailyCheckpointReport:
    generated_at: str
    window_start: str
    window_end: str
    archive_path: str
    total_records_in_window: int
    top_sessions: List[Dict[str, Any]] = field(default_factory=list)
    top_source_tools: List[Dict[str, Any]] = field(default_factory=list)
    key_artifacts: List[str] = field(default_factory=list)
    day_summary: List[str] = field(default_factory=list)
    recovery_card: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class DailyCheckpointEngine:
    """Generate auditable 24h summary and next-day recovery card."""

    def __init__(
        self,
        *,
        archive_path: Path,
        output_file: Path,
        audit_file: Optional[Path] = None,
        config: Optional[DailyCheckpointConfig] = None,
        now_fn: Optional[callable] = None,
    ) -> None:
        self.archive_path = Path(archive_path)
        self.output_file = Path(output_file)
        self.audit_file = Path(audit_file) if audit_file is not None else self.output_file.with_name("daily_checkpoint_audit.jsonl")
        self.config = (config or DailyCheckpointConfig()).normalized()
        self._now_fn = now_fn or time.time
        self._lock = threading.Lock()
        self.output_file.parent.mkdir(parents=True, exist_ok=True)
        self.audit_file.parent.mkdir(parents=True, exist_ok=True)

    def run_once(self) -> DailyCheckpointReport:
        now_ts = float(self._now_fn())
        window_seconds = float(self.config.window_hours * 3600)
        start_ts = now_ts - window_seconds

        records = self._load_records()
        in_window = [row for row in records if float(row.get("timestamp") or 0.0) >= start_ts and float(row.get("timestamp") or 0.0) <= now_ts]
        in_window.sort(key=lambda row: float(row.get("timestamp") or 0.0), reverse=True)

        top_sessions = self._count_by_key(in_window, "session_id")
        top_tools = self._count_by_key(in_window, "source_tool")
        artifacts = self._collect_artifacts(in_window)
        summary_lines = self._build_day_summary(in_window)
        recovery_card = self._build_recovery_card(in_window, artifacts)

        report = DailyCheckpointReport(
            generated_at=_utc_iso(now_ts),
            window_start=_utc_iso(start_ts),
            window_end=_utc_iso(now_ts),
            archive_path=str(self.archive_path),
            total_records_in_window=len(in_window),
            top_sessions=top_sessions,
            top_source_tools=top_tools,
            key_artifacts=artifacts,
            day_summary=summary_lines,
            recovery_card=recovery_card,
        )

        with self._lock:
            self.output_file.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            self._append_audit(report)
        return report

    def _load_records(self) -> List[Dict[str, Any]]:
        if not self.archive_path.exists():
            return []
        rows: List[Dict[str, Any]] = []
        for line in self.archive_path.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            rows.append(payload)
        return rows

    def _count_by_key(self, rows: Sequence[Dict[str, Any]], key: str) -> List[Dict[str, Any]]:
        counter: Dict[str, int] = {}
        for row in rows:
            value = _safe_text(row.get(key)).strip() or "unknown"
            counter[value] = counter.get(value, 0) + 1
        sorted_rows = sorted(counter.items(), key=lambda item: (-item[1], item[0]))
        return [{"name": name, "count": count} for name, count in sorted_rows[: self.config.top_items]]

    def _collect_artifacts(self, rows: Sequence[Dict[str, Any]]) -> List[str]:
        refs: List[str] = []
        for row in rows:
            ref = _safe_text(row.get("forensic_artifact_ref")).strip()
            if ref and ref not in refs:
                refs.append(ref)
            if len(refs) >= self.config.top_items:
                break
        return refs

    def _build_day_summary(self, rows: Sequence[Dict[str, Any]]) -> List[str]:
        lines: List[str] = []
        for row in rows[: self.config.summary_line_limit]:
            session_id = _safe_text(row.get("session_id")).strip() or "unknown"
            source_tool = _safe_text(row.get("source_tool")).strip() or "unknown"
            summary = _truncate(_safe_text(row.get("narrative_summary")), self.config.summary_item_chars)
            timestamp = _utc_iso(float(row.get("timestamp") or 0.0))
            lines.append(f"[{timestamp}] session={session_id} tool={source_tool} summary={summary}")
        return lines

    def _build_recovery_card(self, rows: Sequence[Dict[str, Any]], artifacts: Sequence[str]) -> Dict[str, Any]:
        next_actions: List[str] = []
        seen_actions: set[str] = set()
        for row in rows:
            hints = row.get("fetch_hints")
            if isinstance(hints, list):
                candidates = [str(item).strip() for item in hints if str(item).strip()]
            else:
                candidates = []
            for action in candidates:
                if action in seen_actions:
                    continue
                seen_actions.add(action)
                next_actions.append(action)
                if len(next_actions) >= self.config.top_items:
                    break
            if len(next_actions) >= self.config.top_items:
                break

        if not next_actions and rows:
            next_actions = [
                "review_latest_day_summary",
                "verify_top_error_sessions",
                "inspect_key_artifacts_with_artifact_reader",
            ]

        resume_query = ""
        if rows:
            latest = rows[0]
            resume_query = _truncate(_safe_text(latest.get("narrative_summary")), 220)

        return {
            "resume_query": resume_query,
            "next_actions": next_actions,
            "artifact_refs": list(artifacts),
            "generated_at": _utc_iso(),
        }

    def _append_audit(self, report: DailyCheckpointReport) -> None:
        row = {
            "ts": _utc_iso(),
            "event": "daily_checkpoint_generated",
            "output_file": str(self.output_file),
            "archive_path": str(self.archive_path),
            "total_records_in_window": report.total_records_in_window,
            "top_sessions": report.top_sessions,
        }
        with self.audit_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


__all__ = [
    "DailyCheckpointConfig",
    "DailyCheckpointReport",
    "DailyCheckpointEngine",
]
