from __future__ import annotations

import json
from pathlib import Path

from scripts.migrate_remove_guide_engine_config_ws29_003 import migrate_payload, run_migration


def test_migrate_payload_removes_guide_engine_key() -> None:
    payload = {
        "system": {"ai_name": "Embla"},
        "guide_engine": {"enabled": True},
        "embedding": {"model": "text-embedding-v4"},
    }
    migrated, changed, removed = migrate_payload(payload)
    assert changed is True
    assert removed == ["guide_engine"]
    assert "guide_engine" not in migrated
    assert migrated["system"]["ai_name"] == "Embla"


def test_migrate_payload_no_change_when_key_absent() -> None:
    payload = {"system": {"ai_name": "Embla"}, "embedding": {"model": "text-embedding-v4"}}
    migrated, changed, removed = migrate_payload(payload)
    assert changed is False
    assert removed == []
    assert migrated == payload


def test_run_migration_apply_writes_backup_and_config(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    output_path = tmp_path / "report.json"
    config_path.write_text(
        json.dumps({"system": {"ai_name": "Embla"}, "guide_engine": {"enabled": True}}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    report = run_migration(
        config_path=config_path,
        action="apply",
        output_file=output_path,
        dry_run=False,
    )
    assert report["passed"] is True
    assert report["changed"] is True
    assert report["write_applied"] is True
    assert report["removed_keys"] == ["guide_engine"]
    assert report["backup_path"]

    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert "guide_engine" not in saved


def test_run_migration_check_fails_when_residual_key_exists(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    output_path = tmp_path / "report.json"
    config_path.write_text(
        json.dumps({"system": {"ai_name": "Embla"}, "guide_engine": {"enabled": True}}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    report = run_migration(
        config_path=config_path,
        action="check",
        output_file=output_path,
        dry_run=False,
    )
    assert report["passed"] is False
    assert report["changed"] is True
    assert report["removed_keys"] == ["guide_engine"]


def test_run_migration_check_passes_when_clean(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    output_path = tmp_path / "report.json"
    config_path.write_text(json.dumps({"system": {"ai_name": "Embla"}}, ensure_ascii=False, indent=2), encoding="utf-8")

    report = run_migration(
        config_path=config_path,
        action="check",
        output_file=output_path,
        dry_run=False,
    )
    assert report["passed"] is True
    assert report["changed"] is False
    assert report["removed_keys"] == []
