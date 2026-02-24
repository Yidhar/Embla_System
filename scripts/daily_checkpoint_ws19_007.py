"""Run WS19-007 daily checkpoint generation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from autonomous.daily_checkpoint import DailyCheckpointConfig, DailyCheckpointEngine


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate daily checkpoint summary and recovery card.")
    parser.add_argument(
        "--archive",
        default="logs/episodic_memory/episodic_archive.jsonl",
        help="Episodic archive path",
    )
    parser.add_argument(
        "--output",
        default="logs/autonomous/daily_checkpoint/latest_checkpoint.json",
        help="Checkpoint output path",
    )
    parser.add_argument(
        "--audit",
        default="logs/autonomous/daily_checkpoint/daily_checkpoint_audit.jsonl",
        help="Audit output path",
    )
    parser.add_argument("--window-hours", type=int, default=24, help="Window size in hours")
    parser.add_argument("--top-items", type=int, default=5, help="Top N items in summary sections")
    parser.add_argument("--summary-lines", type=int, default=6, help="Summary line count")
    args = parser.parse_args()

    cfg = DailyCheckpointConfig(
        window_hours=args.window_hours,
        top_items=args.top_items,
        summary_line_limit=args.summary_lines,
    )
    engine = DailyCheckpointEngine(
        archive_path=Path(args.archive),
        output_file=Path(args.output),
        audit_file=Path(args.audit),
        config=cfg,
    )
    report = engine.run_once()
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
