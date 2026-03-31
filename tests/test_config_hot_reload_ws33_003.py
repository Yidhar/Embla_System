"""配置热更新测试 — ws33-003

验证:
1. hot_reload_config() 检测配置变更并记录变化的顶层字段
2. watchfiles 不可用时，ConfigManager 回退到轮询模式
"""
from __future__ import annotations

import importlib
import json
import logging
import os
import sys
import threading
import time
import types
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# 项目路径
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _write_config(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. hot_reload_config 检测变更并记录 diff
# ---------------------------------------------------------------------------


def test_hot_reload_config_logs_changed_keys(tmp_path: Path, caplog):
    """hot_reload_config() 应在日志中记录发生变化的顶层字段名。"""
    config_path = tmp_path / "config.json"
    _write_config(config_path, {"system": {"version": "5.0.0", "debug": False}, "ui": {"user_name": "Alice"}})

    # 用 tmp_path 下的 config.json 来驱动 load_config
    from system import config as config_mod

    original_load = config_mod.load_config

    call_count = 0

    def _fake_load():
        nonlocal call_count
        call_count += 1
        if call_count <= 1:
            # 第一次调用已由模块初始化完成，但 hot_reload_config 内部再调用时
            # 返回一个修改过 ui 的配置
            return config_mod.EmblaSystemConfig(
                ui=config_mod.UIConfig(user_name="Alice"),
            )
        else:
            # 后续调用返回不同的 ui
            return config_mod.EmblaSystemConfig(
                ui=config_mod.UIConfig(user_name="Bob"),
            )

    with patch.object(config_mod, "load_config", side_effect=_fake_load):
        # 先把 old_config 设为 call_count=1 的版本
        config_mod.config = _fake_load()
        call_count = 1  # 重置，使下次 load_config 返回 "Bob"

        with caplog.at_level(logging.INFO, logger="system.config"):
            result = config_mod.hot_reload_config()

    # 验证日志中包含变更字段
    combined = " ".join(caplog.messages)
    assert "ui" in combined, f"Expected 'ui' in log messages, got: {caplog.messages}"
    assert "changed keys" in combined.lower() or "changed" in combined.lower()


# ---------------------------------------------------------------------------
# 2. _diff_top_level_keys 基础行为
# ---------------------------------------------------------------------------


def test_diff_top_level_keys_no_change():
    """完全相同的配置应返回空列表。"""
    from system.config import EmblaSystemConfig, _diff_top_level_keys

    a = EmblaSystemConfig()
    b = EmblaSystemConfig()
    assert _diff_top_level_keys(a, b) == []


def test_diff_top_level_keys_detects_change():
    """修改一个顶层字段后应出现在 diff 中。"""
    from system.config import EmblaSystemConfig, UIConfig, _diff_top_level_keys

    a = EmblaSystemConfig()
    b = EmblaSystemConfig(ui=UIConfig(user_name="changed_name"))
    changed = _diff_top_level_keys(a, b)
    assert "ui" in changed


# ---------------------------------------------------------------------------
# 3. ConfigManager 回退轮询模式 (watchfiles 不可用)
# ---------------------------------------------------------------------------


def test_config_watcher_falls_back_to_polling_when_watchfiles_unavailable(tmp_path: Path, caplog):
    """当 watchfiles 不可用时，_watch_config_file 应使用轮询模式。"""
    config_path = tmp_path / "config.json"
    _write_config(config_path, {"system": {"version": "5.0.0"}})

    from system.config_manager import ConfigManager

    mgr = ConfigManager()

    # 模拟 watchfiles 不可导入：让 _watch_config_file_watchfiles 的 import 失败
    original_watch = mgr._watch_config_file_watchfiles

    def _fake_watch_with_import_error(config_file, watchfiles_mod):
        raise ImportError("mocked: watchfiles not available")

    # 替换 _watch_config_file，让 watchfiles import 抛错
    def _patched_watch(config_file: str):
        """模拟 watchfiles 不可用"""
        try:
            raise ImportError("mocked: no watchfiles")
        except ImportError:
            mgr._watch_config_file_polling(config_file)

    with caplog.at_level(logging.INFO):
        # 直接调用 polling 方法，在后台线程中运行并快速停止
        mgr._stop_watching = False
        mgr._stop_event.clear()

        polling_called = threading.Event()
        original_polling = mgr._watch_config_file_polling

        def _short_polling(config_file):
            polling_called.set()
            # 立即停止，只验证日志
            mgr._stop_watching = True

        mgr._watch_config_file_polling = _short_polling

        with patch.object(mgr, "_watch_config_file_watchfiles", side_effect=ImportError("mocked")):
            t = threading.Thread(target=mgr._watch_config_file, args=(str(config_path),), daemon=True)
            t.start()
            polling_called.wait(timeout=5)
            t.join(timeout=2)

    assert polling_called.is_set(), "Polling fallback was not invoked"


# ---------------------------------------------------------------------------
# 4. ConfigManager watchfiles 路径启动确认
# ---------------------------------------------------------------------------


def test_config_watcher_uses_watchfiles_when_available(tmp_path: Path, caplog):
    """当 watchfiles 可用时，应选择 watchfiles 事件驱动路径。"""
    config_path = tmp_path / "config.json"
    _write_config(config_path, {"system": {"version": "5.0.0"}})

    from system.config_manager import ConfigManager

    mgr = ConfigManager()

    watchfiles_called = threading.Event()

    def _fake_watchfiles_watch(config_file, watchfiles_mod):
        watchfiles_called.set()
        # 不真正监视，直接返回

    with patch.object(mgr, "_watch_config_file_watchfiles", side_effect=_fake_watchfiles_watch):
        t = threading.Thread(target=mgr._watch_config_file, args=(str(config_path),), daemon=True)
        t.start()
        watchfiles_called.wait(timeout=5)
        mgr._stop_watching = True
        mgr._stop_event.set()
        t.join(timeout=2)

    assert watchfiles_called.is_set(), "watchfiles path was not taken"


# ---------------------------------------------------------------------------
# 5. 轮询模式检测文件变化并触发 hot_reload
# ---------------------------------------------------------------------------


def test_polling_detects_file_change_and_triggers_reload(tmp_path: Path):
    """轮询模式应在文件 mtime 变化后调用 hot_reload_config()。"""
    config_path = tmp_path / "config.json"
    _write_config(config_path, {"system": {"version": "5.0.0"}})

    from system.config_manager import ConfigManager

    mgr = ConfigManager()

    reload_called = threading.Event()

    with patch("system.config_manager.hot_reload_config", side_effect=lambda: reload_called.set()):
        mgr._stop_watching = False
        t = threading.Thread(target=mgr._watch_config_file_polling, args=(str(config_path),), daemon=True)
        t.start()

        # 等第一次扫描通过（它会因为 last_modified=0 < mtime 就触发一次）
        reload_called.wait(timeout=5)
        assert reload_called.is_set(), "Initial mtime detection should trigger reload"

        # 重置，再修改文件触发第二次
        reload_called.clear()
        time.sleep(1.2)  # 确保 mtime 不同（文件系统精度）
        _write_config(config_path, {"system": {"version": "5.0.1"}})
        reload_called.wait(timeout=5)

        mgr._stop_watching = True
        t.join(timeout=2)

    assert reload_called.is_set(), "Polling did not detect file change"
