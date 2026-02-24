from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

from autonomous.daily_checkpoint import DailyCheckpointConfig, DailyCheckpointEngine


def _make_case_root(prefix: str) -> Path:
    root = Path("scratch") / prefix / uuid.uuid4().hex[:12]
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_case_root(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


def _write_archive(path: Path, rows: list[dict]) -> None:
    lines = [json.dumps(row, ensure_ascii=False) for row in rows]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def test_daily_checkpoint_generates_summary_and_audit() -> None:
    case_root = _make_case_root("test_daily_checkpoint_ws19_007")
    try:
        now_ts = 1_800_000_000.0
        archive = case_root / "episodic_archive.jsonl"
        _write_archive(
            archive,
            [
                {
                    "record_id": "ep1",
                    "session_id": "sess-1",
                    "source_tool": "native:run_cmd",
                    "narrative_summary": "fixed nginx restart loop after config rollback",
                    "forensic_artifact_ref": "artifact://a1",
                    "fetch_hints": ["grep:error", "line_range:120-180"],
                    "timestamp": now_ts - 60,
                },
                {
                    "record_id": "ep2",
                    "session_id": "sess-2",
                    "source_tool": "native:artifact_reader",
                    "narrative_summary": "validated policy firewall blocklist behavior",
                    "forensic_artifact_ref": "artifact://a2",
                    "fetch_hints": ["jsonpath:$..error_code"],
                    "timestamp": now_ts - 120,
                },
            ],
        )
        output = case_root / "daily_checkpoint.json"
        audit = case_root / "daily_checkpoint_audit.jsonl"
        engine = DailyCheckpointEngine(
            archive_path=archive,
            output_file=output,
            audit_file=audit,
            config=DailyCheckpointConfig(window_hours=24, top_items=5, summary_line_limit=5),
            now_fn=lambda: now_ts,
        )
        report = engine.run_once()

        assert report.total_records_in_window == 2
        assert report.top_sessions[0]["name"] == "sess-1"
        assert report.key_artifacts == ["artifact://a1", "artifact://a2"]
        assert report.recovery_card["next_actions"]
        assert output.exists()
        assert audit.exists()

        audit_rows = [json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert audit_rows[-1]["event"] == "daily_checkpoint_generated"
        assert audit_rows[-1]["total_records_in_window"] == 2
    finally:
        _cleanup_case_root(case_root)


def test_daily_checkpoint_applies_24h_window_filter() -> None:
    case_root = _make_case_root("test_daily_checkpoint_ws19_007")
    try:
        now_ts = 1_900_000_000.0
        archive = case_root / "episodic_archive.jsonl"
        _write_archive(
            archive,
            [
                {
                    "record_id": "new-1",
                    "session_id": "sess-new",
                    "source_tool": "native:run_cmd",
                    "narrative_summary": "recent incident resolution",
                    "forensic_artifact_ref": "artifact://new",
                    "fetch_hints": ["grep:timeout"],
                    "timestamp": now_ts - 3600,
                },
                {
                    "record_id": "old-1",
                    "session_id": "sess-old",
                    "source_tool": "native:run_cmd",
                    "narrative_summary": "old incident should be excluded",
                    "forensic_artifact_ref": "artifact://old",
                    "fetch_hints": [],
                    "timestamp": now_ts - (30 * 3600),
                },
            ],
        )
        engine = DailyCheckpointEngine(
            archive_path=archive,
            output_file=case_root / "daily_checkpoint.json",
            now_fn=lambda: now_ts,
        )
        report = engine.run_once()
        assert report.total_records_in_window == 1
        assert report.top_sessions[0]["name"] == "sess-new"
        assert "artifact://old" not in report.key_artifacts
    finally:
        _cleanup_case_root(case_root)


def test_daily_checkpoint_handles_missing_archive() -> None:
    case_root = _make_case_root("test_daily_checkpoint_ws19_007")
    try:
        engine = DailyCheckpointEngine(
            archive_path=case_root / "missing_archive.jsonl",
            output_file=case_root / "daily_checkpoint.json",
            now_fn=lambda: 2_000_000_000.0,
        )
        report = engine.run_once()
        assert report.total_records_in_window == 0
        assert report.day_summary == []
        assert report.recovery_card["next_actions"] == []
    finally:
        _cleanup_case_root(case_root)
