from __future__ import annotations

import json
import time
from pathlib import Path

from autonomous.gc_pipeline import GCPipelineConfig, run_gc_pipeline


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n"
    path.write_text(content, encoding="utf-8")


def test_gc_pipeline_compacts_archive_by_retention_and_session_cap(tmp_path: Path) -> None:
    now = time.time()
    archive = tmp_path / "episodic_archive.jsonl"
    _write_jsonl(
        archive,
        [
            {"record_id": "r1", "session_id": "s1", "timestamp": now - 1000, "narrative_summary": "old"},
            {"record_id": "r2", "session_id": "s2", "timestamp": now - 10, "narrative_summary": "keep-1"},
            {"record_id": "r3", "session_id": "s2", "timestamp": now - 9, "narrative_summary": "keep-2"},
            {"record_id": "r4", "session_id": "s2", "timestamp": now - 8, "narrative_summary": "drop-session-cap"},
        ],
    )

    report = run_gc_pipeline(
        archive_path=archive,
        output_path=tmp_path / "gc_report.json",
        config=GCPipelineConfig(
            retention_seconds=120.0,
            max_records_per_session=2,
            max_total_records=10,
            dry_run=False,
        ),
    )
    assert report["passed"] is True
    assert report["stats"]["original_count"] == 4
    assert report["stats"]["retained_count"] == 2
    assert report["stats"]["deleted_count"] == 2

    rows = [json.loads(line) for line in archive.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) == 2
    assert {row["record_id"] for row in rows} == {"r3", "r4"}
