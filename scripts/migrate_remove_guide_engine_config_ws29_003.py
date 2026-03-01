#!/usr/bin/env python3
"""WS29-003: remove retired guide_engine config keys from local config.json."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import json5
from charset_normalizer import from_path


DEFAULT_OUTPUT = Path("scratch/reports/ws29_config_guide_engine_retirement_ws29_003.json")


def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_unix_path(path: Path) -> str:
    return str(path).replace("\\", "/")


def _detect_encoding(path: Path) -> str:
    try:
        result = from_path(str(path))
        if result:
            best = result.best()
            if best and best.encoding:
                return str(best.encoding)
    except Exception:
        pass
    return "utf-8"


def _load_payload(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"config file not found: {path}")
    encoding = _detect_encoding(path)
    text = path.read_text(encoding=encoding, errors="replace")
    try:
        payload = json5.loads(text)
    except Exception:
        payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError(f"config payload must be an object: {path}")
    return payload


def _write_payload(path: Path, payload: Dict[str, Any]) -> None:
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), prefix=".cfg_ws29_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(rendered)
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _create_backup(path: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = path.with_name(f"{path.name}.bak.ws29_003.{timestamp}")
    backup.write_bytes(path.read_bytes())
    return backup


def migrate_payload(payload: Dict[str, Any]) -> Tuple[Dict[str, Any], bool, List[str]]:
    migrated = dict(payload)
    removed_keys: List[str] = []

    if "guide_engine" in migrated:
        migrated.pop("guide_engine", None)
        removed_keys.append("guide_engine")

    changed = len(removed_keys) > 0
    return migrated, changed, removed_keys


def run_migration(
    *,
    config_path: Path,
    action: str,
    output_file: Path,
    dry_run: bool = False,
) -> Dict[str, Any]:
    payload = _load_payload(config_path)
    migrated, changed, removed_keys = migrate_payload(payload)

    backup_path: Path | None = None
    write_applied = False
    if action == "apply" and changed and not dry_run:
        backup_path = _create_backup(config_path)
        _write_payload(config_path, migrated)
        write_applied = True

    if action == "check":
        passed = not changed
    else:
        passed = True

    report: Dict[str, Any] = {
        "task_id": "NGA-WS29-003",
        "scenario": "config_guide_engine_retirement",
        "generated_at": _utc_iso_now(),
        "action": action,
        "passed": bool(passed),
        "changed": bool(changed),
        "dry_run": bool(dry_run),
        "write_applied": bool(write_applied),
        "config_path": _to_unix_path(config_path.resolve()),
        "removed_keys": removed_keys,
        "backup_path": _to_unix_path(backup_path.resolve()) if backup_path is not None else "",
    }

    output_path = output_file.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report["output_file"] = _to_unix_path(output_path)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="WS29-003 remove retired guide_engine config keys")
    parser.add_argument("--config", type=Path, default=Path("config.json"), help="Config file path")
    parser.add_argument("--action", choices=["check", "apply"], default="check", help="Run mode")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Output report path",
    )
    parser.add_argument("--dry-run", action="store_true", help="Do not write config file in apply mode")
    parser.add_argument("--strict", action="store_true", help="Return non-zero if check fails")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_migration(
        config_path=args.config.resolve(),
        action=str(args.action),
        output_file=args.output,
        dry_run=bool(args.dry_run),
    )
    print(
        json.dumps(
            {
                "passed": bool(report.get("passed")),
                "changed": bool(report.get("changed")),
                "removed_keys": list(report.get("removed_keys") or []),
                "output": str(report.get("output_file") or ""),
            },
            ensure_ascii=False,
        )
    )
    if args.strict and not bool(report.get("passed")):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
