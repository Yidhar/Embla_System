from __future__ import annotations

import json
from pathlib import Path

from system.config import EmblaSystemConfig, normalize_runtime_config_payload
from system.config_manager import ConfigManager


def test_normalize_runtime_config_payload_drops_unknown_root_keys() -> None:
    payload = {
        "system": {"version": "5.0.0"},
        "unknown_portal": {"portal_url": "https://unknown.example.com/", "username": "u"},
    }

    normalized = normalize_runtime_config_payload(payload)

    assert "unknown_portal" not in normalized
    assert "embla_portal" not in normalized

    config = EmblaSystemConfig(**normalized)
    assert config.embla_portal.portal_url == ""


def test_config_manager_save_drops_unknown_root_keys(tmp_path: Path) -> None:
    manager = ConfigManager()
    config_path = tmp_path / "config.json"

    assert manager._save_config_file(
        str(config_path),
        {"system": {"version": "5.0.0"}, "unknown_portal": {"portal_url": "https://unknown.example.com/"}},
    )

    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert "unknown_portal" not in saved
    assert "embla_portal" not in saved


def test_config_manager_save_preserves_canonical_embla_portal(tmp_path: Path) -> None:
    manager = ConfigManager()
    config_path = tmp_path / "config.json"

    assert manager._save_config_file(
        str(config_path),
        {"system": {"version": "5.0.0"}, "embla_portal": {"portal_url": "https://embla.example.com/"}},
    )

    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["embla_portal"]["portal_url"] == "https://embla.example.com/"
    assert "unknown_portal" not in saved


def test_normalize_runtime_config_payload_drops_unknown_nested_keys() -> None:
    payload = {
        "system": {"version": "5.0.0"},
        "autonomous": {"enabled": True, "removed_toggle": True},
    }

    normalized = normalize_runtime_config_payload(payload)

    assert normalized["autonomous"]["enabled"] is True
    assert "removed_toggle" not in normalized["autonomous"]


def test_config_manager_save_drops_unknown_nested_keys(tmp_path: Path) -> None:
    manager = ConfigManager()
    config_path = tmp_path / "config.json"

    assert manager._save_config_file(
        str(config_path),
        {"system": {"version": "5.0.0"}, "autonomous": {"enabled": True, "removed_toggle": True}},
    )

    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["autonomous"]["enabled"] is True
    assert "removed_toggle" not in saved["autonomous"]
