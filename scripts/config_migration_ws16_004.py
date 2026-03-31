#!/usr/bin/env python3
"""NGA-WS16-004: config schema migration utility with backup/restore support."""

from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable

import json5
from charset_normalizer import from_path


DEFAULT_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class MigrationOutcome:
    """Upgrade run result."""

    config_path: Path
    changed: bool
    backup_path: Path | None
    migrated_payload: Dict[str, Any]


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


def _safe_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_port(value: Any) -> int | None:
    port = _safe_int(value)
    if port is None:
        return None
    if 1 <= port <= 65535:
        return port
    return None


def load_config_payload(config_path: Path) -> Dict[str, Any]:
    """Load a JSON/JSON5 config payload."""
    if not config_path.exists():
        raise FileNotFoundError(f"config file not found: {config_path}")

    encoding = _detect_encoding(config_path)
    text = config_path.read_text(encoding=encoding, errors="replace")

    try:
        payload = json5.loads(text)
    except Exception:
        payload = json.loads(text)

    if not isinstance(payload, dict):
        raise ValueError(f"config payload must be a JSON object: {config_path}")
    return payload


def write_config_payload(config_path: Path, payload: Dict[str, Any]) -> None:
    """Atomically write config payload as canonical JSON."""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"

    fd, tmp_path = tempfile.mkstemp(dir=str(config_path.parent), prefix=".config_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(rendered)
        os.replace(tmp_path, config_path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _backup_name(config_path: Path, now: datetime | None = None) -> str:
    ts = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{config_path.name}.bak.{ts}"


def create_backup(config_path: Path, *, backup_dir: Path | None = None, now: datetime | None = None) -> Path:
    """Create a timestamped backup for a config file."""
    if not config_path.exists():
        raise FileNotFoundError(f"config file not found: {config_path}")

    target_dir = (backup_dir or config_path.parent).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    base_name = _backup_name(config_path, now=now)
    backup_path = target_dir / base_name
    suffix = 1
    while backup_path.exists():
        backup_path = target_dir / f"{base_name}.{suffix}"
        suffix += 1

    shutil.copy2(config_path, backup_path)
    return backup_path


def list_backups(config_path: Path, *, backup_dir: Path | None = None) -> list[Path]:
    """List backups sorted by timestamp (oldest -> newest)."""
    target_dir = (backup_dir or config_path.parent).resolve()
    if not target_dir.exists():
        return []

    backups: list[Path] = []
    pattern = f"{config_path.name}.bak.*"
    for candidate in target_dir.glob(pattern):
        if candidate.is_file():
            backups.append(candidate)
    backups.sort(key=lambda item: (item.stat().st_mtime, item.name))
    return backups


def restore_config_file(
    config_path: Path,
    *,
    backup_path: Path | None = None,
    backup_dir: Path | None = None,
) -> Path:
    """Restore config from an explicit backup file or latest available backup."""
    source = backup_path.resolve() if backup_path is not None else None
    if source is None:
        backups = list_backups(config_path, backup_dir=backup_dir)
        if not backups:
            raise FileNotFoundError(f"no backups found for {config_path.name}")
        source = backups[-1]

    if not source.exists():
        raise FileNotFoundError(f"backup file not found: {source}")

    config_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(config_path.parent), prefix=".config_restore_", suffix=".tmp")
    try:
        os.close(fd)
        shutil.copy2(source, tmp_path)
        os.replace(tmp_path, config_path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    return source


def _ensure_system_schema_marker(payload: Dict[str, Any], *, target_schema_version: int) -> None:
    system = payload.get("system")
    if not isinstance(system, dict):
        system = {}
        payload["system"] = system

    current = _safe_int(system.get("config_schema_version"))
    if current is None or current < target_schema_version:
        system["config_schema_version"] = target_schema_version
    elif system.get("config_schema_version") != current:
        system["config_schema_version"] = current


def _map_handoff_round_limits(payload: Dict[str, Any]) -> None:
    handoff = payload.get("handoff")
    if not isinstance(handoff, dict):
        return

    stream_rounds = handoff.get("max_loop_stream")
    non_stream_rounds = handoff.get("max_loop_non_stream")
    if stream_rounds is None and non_stream_rounds is None:
        return

    agentic_loop = payload.get("agentic_loop")
    if agentic_loop is None:
        agentic_loop = {}
        payload["agentic_loop"] = agentic_loop
    if not isinstance(agentic_loop, dict):
        return

    if "max_rounds_stream" not in agentic_loop and stream_rounds is not None:
        agentic_loop["max_rounds_stream"] = stream_rounds
    if "max_rounds_non_stream" not in agentic_loop and non_stream_rounds is not None:
        agentic_loop["max_rounds_non_stream"] = non_stream_rounds


def _ensure_tool_contract_rollout(payload: Dict[str, Any]) -> None:
    rollout = payload.get("tool_contract_rollout")
    if rollout is None:
        rollout = {}
        payload["tool_contract_rollout"] = rollout
    if not isinstance(rollout, dict):
        return

    rollout.pop("mode", None)
    rollout.pop("decommission_legacy_gate", None)

    if "emit_observability_metadata" not in rollout:
        rollout["emit_observability_metadata"] = True
    else:
        rollout["emit_observability_metadata"] = bool(rollout.get("emit_observability_metadata"))


def _iter_port_candidates(payload: Dict[str, Any]) -> Iterable[tuple[str, Any]]:
    candidates: dict[str, list[tuple[str, str]]] = {
        "api_server": [("api_server", "port")],
        "agent_server": [("agentserver", "port"), ("agent_server", "port")],
        "mcp_server": [("mcpserver", "port"), ("mcp_server", "port")],
    }

    for target_key, sources in candidates.items():
        value = None
        for section_name, field_name in sources:
            section = payload.get(section_name)
            if not isinstance(section, dict):
                continue
            if field_name not in section:
                continue
            value = section.get(field_name)
            break
        yield target_key, value


def project_server_ports(payload: Dict[str, Any], *, overwrite: bool = False) -> None:
    """Project component-specific ports into `server_ports`."""
    existing_ports = payload.get("server_ports")
    if existing_ports is None:
        port_map: Dict[str, Any] = {}
    elif isinstance(existing_ports, dict):
        port_map = existing_ports
    else:
        # Keep unknown non-object payload untouched.
        return

    for target_key, raw_value in _iter_port_candidates(payload):
        if not overwrite and target_key in port_map:
            continue
        safe_port = _safe_port(raw_value)
        if safe_port is None:
            continue
        port_map[target_key] = safe_port

    if port_map:
        payload["server_ports"] = port_map


def migrate_payload(
    payload: Dict[str, Any],
    *,
    target_schema_version: int = DEFAULT_SCHEMA_VERSION,
    project_server_ports_flag: bool = False,
) -> Dict[str, Any]:
    """Return migrated payload while preserving unknown keys."""
    if not isinstance(payload, dict):
        raise ValueError("payload must be a dict")

    migrated = copy.deepcopy(payload)
    _ensure_system_schema_marker(migrated, target_schema_version=target_schema_version)
    _map_handoff_round_limits(migrated)
    _ensure_tool_contract_rollout(migrated)
    if project_server_ports_flag:
        project_server_ports(migrated)
    return migrated


def upgrade_config_file(
    config_path: Path,
    *,
    backup_dir: Path | None = None,
    target_schema_version: int = DEFAULT_SCHEMA_VERSION,
    project_server_ports_flag: bool = False,
    dry_run: bool = False,
    now: datetime | None = None,
) -> MigrationOutcome:
    """Run in-place migration with automatic backup before write."""
    original_payload = load_config_payload(config_path)
    migrated_payload = migrate_payload(
        original_payload,
        target_schema_version=target_schema_version,
        project_server_ports_flag=project_server_ports_flag,
    )

    changed = migrated_payload != original_payload
    if dry_run or not changed:
        return MigrationOutcome(
            config_path=config_path.resolve(),
            changed=changed,
            backup_path=None,
            migrated_payload=migrated_payload,
        )

    backup_path = create_backup(config_path, backup_dir=backup_dir, now=now)
    write_config_payload(config_path, migrated_payload)
    return MigrationOutcome(
        config_path=config_path.resolve(),
        changed=True,
        backup_path=backup_path,
        migrated_payload=migrated_payload,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="NGA-WS16-004 config migration utility")
    parser.add_argument("--config", type=Path, default=Path("config.json"), help="Config file path")
    parser.add_argument("--backup-dir", type=Path, default=None, help="Backup directory (default: config directory)")
    parser.add_argument(
        "--target-schema-version",
        type=int,
        default=DEFAULT_SCHEMA_VERSION,
        help="Target schema version marker for system.config_schema_version",
    )
    parser.add_argument(
        "--project-server-ports",
        action="store_true",
        help="Populate missing `server_ports` entries from component-specific ports",
    )
    parser.add_argument("--dry-run", action="store_true", help="Do not write files; print migration result only")
    parser.add_argument("--restore", type=Path, default=None, help="Restore from explicit backup file")
    parser.add_argument(
        "--restore-latest",
        action="store_true",
        help="Restore from latest backup in --backup-dir (or config directory)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.restore is not None and args.restore_latest:
        raise SystemExit("--restore and --restore-latest are mutually exclusive")

    config_path = args.config.resolve()
    backup_dir = args.backup_dir.resolve() if args.backup_dir is not None else None

    if args.restore is not None or args.restore_latest:
        source = restore_config_file(config_path, backup_path=args.restore, backup_dir=backup_dir)
        print(f"[restore] config={config_path}")
        print(f"[restore] source={source}")
        return 0

    outcome = upgrade_config_file(
        config_path,
        backup_dir=backup_dir,
        target_schema_version=max(1, int(args.target_schema_version)),
        project_server_ports_flag=bool(args.project_server_ports),
        dry_run=bool(args.dry_run),
    )

    print(f"[upgrade] config={outcome.config_path}")
    print(f"[upgrade] changed={outcome.changed}")
    if args.dry_run:
        print("[upgrade] dry_run=true")
    elif outcome.backup_path is not None:
        print(f"[upgrade] backup={outcome.backup_path}")
    else:
        print("[upgrade] backup=(not-created)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
