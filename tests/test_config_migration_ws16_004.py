from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict

from scripts.config_migration_ws16_004 import (
    create_backup,
    load_config_payload,
    migrate_payload,
    restore_config_file,
    upgrade_config_file,
)


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _make_repo_root(prefix: str) -> Path:
    repo_root = Path("scratch") / prefix / uuid.uuid4().hex[:12]
    repo_root.mkdir(parents=True, exist_ok=True)
    return repo_root


def _cleanup_repo_root(repo_root: Path) -> None:
    shutil.rmtree(repo_root, ignore_errors=True)


def test_migrate_payload_preserves_unknown_and_maps_handoff_limits() -> None:
    original = {
        "system": {"version": "5.0.0", "custom_toggle": True},
        "handoff": {"max_loop_stream": 7, "max_loop_non_stream": 9, "show_output": False},
        "agentic_loop": {"max_rounds_stream": 111, "custom_loop_flag": "keep"},
        "unknown_root": {"nested": {"keep": "yes"}},
    }

    migrated = migrate_payload(original)

    assert "config_schema_version" not in original["system"]
    assert migrated["system"]["config_schema_version"] == 1
    assert migrated["system"]["custom_toggle"] is True
    assert migrated["unknown_root"]["nested"]["keep"] == "yes"

    # Existing value must be kept; only missing target keys are projected.
    assert migrated["agentic_loop"]["max_rounds_stream"] == 111
    assert migrated["agentic_loop"]["max_rounds_non_stream"] == 9
    assert migrated["agentic_loop"]["custom_loop_flag"] == "keep"


def test_migrate_payload_optionally_projects_server_ports() -> None:
    payload = {
        "system": {"version": "5.0.0"},
        "api_server": {"port": 8100},
        "agentserver": {"port": "8101"},
        "mcpserver": {"port": 8103},
        "tts": {"port": 5048},
        "asr": {"port": "not-a-port"},
        "server_ports": {"api_server": 9000, "custom_port_key": 42},
    }

    migrated = migrate_payload(payload, project_server_ports_flag=True)

    # Existing projection values remain untouched by default.
    assert migrated["server_ports"]["api_server"] == 9000
    assert migrated["server_ports"]["agent_server"] == 8101
    assert migrated["server_ports"]["mcp_server"] == 8103
    assert migrated["server_ports"]["tts_server"] == 5048
    assert "asr_server" not in migrated["server_ports"]
    assert migrated["server_ports"]["custom_port_key"] == 42


def test_upgrade_creates_backup_before_write_and_restore_roundtrip() -> None:
    repo_root = _make_repo_root("test_config_migration_ws16_004")
    try:
        config_path = repo_root / "config.json"
        backup_dir = repo_root / "backups"
        original_payload = {
            "system": {"version": "5.0.0"},
            "handoff": {"max_loop_stream": 5, "max_loop_non_stream": 6},
            "unknown_field": {"keep": 1},
        }
        _write_json(config_path, original_payload)

        fixed_now = datetime(2026, 2, 24, 8, 0, tzinfo=timezone.utc)
        outcome = upgrade_config_file(
            config_path,
            backup_dir=backup_dir,
            project_server_ports_flag=False,
            now=fixed_now,
        )

        assert outcome.changed is True
        assert outcome.backup_path is not None
        assert outcome.backup_path.exists() is True
        assert load_config_payload(outcome.backup_path) == original_payload

        migrated_payload = load_config_payload(config_path)
        assert migrated_payload["system"]["config_schema_version"] == 1
        assert migrated_payload["agentic_loop"]["max_rounds_stream"] == 5
        assert migrated_payload["agentic_loop"]["max_rounds_non_stream"] == 6
        assert migrated_payload["unknown_field"]["keep"] == 1

        _write_json(config_path, {"system": {"config_schema_version": 999}})
        restored_from = restore_config_file(config_path, backup_path=outcome.backup_path)
        assert restored_from == outcome.backup_path.resolve()
        assert load_config_payload(config_path) == original_payload
    finally:
        _cleanup_repo_root(repo_root)


def test_restore_uses_latest_backup_when_path_not_provided() -> None:
    repo_root = _make_repo_root("test_config_migration_ws16_004_latest")
    try:
        config_path = repo_root / "config.json"
        backup_dir = repo_root / "backups"
        payload_v1 = {"system": {"version": "5.0.0"}, "payload": 1}
        payload_v2 = {"system": {"version": "5.0.0"}, "payload": 2}

        _write_json(config_path, payload_v1)
        first_backup = create_backup(
            config_path,
            backup_dir=backup_dir,
            now=datetime(2026, 2, 24, 7, 0, tzinfo=timezone.utc),
        )

        _write_json(config_path, payload_v2)
        second_backup = create_backup(
            config_path,
            backup_dir=backup_dir,
            now=datetime(2026, 2, 24, 7, 0, tzinfo=timezone.utc) + timedelta(minutes=1),
        )

        _write_json(config_path, {"system": {"version": "5.0.0"}, "payload": 999})
        restored_from = restore_config_file(config_path, backup_dir=backup_dir)

        assert restored_from == second_backup
        assert restored_from != first_backup
        assert load_config_payload(config_path) == payload_v2
    finally:
        _cleanup_repo_root(repo_root)
