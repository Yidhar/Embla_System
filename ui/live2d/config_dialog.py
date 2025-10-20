#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Live2D动作配置对话框
重定向到新的现代化配置对话框，保留旧版本作为备份
"""

import logging

logger = logging.getLogger("live2d.config_dialog")

# 尝试导入新的现代化配置对话框
try:
    from .modern_config_dialog import (
        ModernLive2DConfigDialog as Live2DConfigDialog,
        ActionCard,
        SearchBar
    )
    logger.info("使用现代化的Live2D配置对话框")

except ImportError as e:
    logger.warning(f"无法导入现代化配置对话框: {e}")
    logger.info("回退到经典配置对话框")

    # 回退到经典实现
    from nagaagent_core.vendors.PyQt5.QtWidgets import (
        QDialog, QVBoxLayout, QHBoxLayout, QListWidget,
        QListWidgetItem, QPushButton, QLabel, QCheckBox,
        QDialogButtonBox, QSplitter, QGroupBox
    )
    from nagaagent_core.vendors.PyQt5.QtCore import Qt, pyqtSignal
    import json
    import os


    class Live2DConfigDialog(QDialog):
        """Live2D动作配置对话框 - 经典版本（备份）"""

        config_updated = pyqtSignal(dict)  # 配置更新信号

        def __init__(self, available_actions=None, current_config=None, parent=None):
            super().__init__(parent)
            self.available_actions = available_actions or {"motions": [], "expressions": []}
            self.current_config = current_config or []
            self.setWindowTitle("配置Live2D动作")
            self.setModal(True)
            self.resize(700, 500)

            # 设置窗口透明属性
            self.setAttribute(Qt.WA_TranslucentBackground)

            self._init_ui()
            self._load_available_actions()
            self._load_current_config()

        def _init_ui(self):
            """初始化UI"""
            layout = QVBoxLayout(self)

            # 标题
            title_label = QLabel("选择要显示的动作和表情（最多8个）")
            title_label.setStyleSheet("""
                font-size: 14px;
                font-weight: bold;
                padding: 10px;
                color: white;
                background: transparent;
            """)
            layout.addWidget(title_label)

            # 分割器
            splitter = QSplitter(Qt.Horizontal)

            # 可用动作组
            available_group = QGroupBox("可用动作")
            available_layout = QVBoxLayout(available_group)

            # 动作列表
            self.motions_list = QListWidget()
            self.motions_list.setSelectionMode(QListWidget.MultiSelection)
            available_layout.addWidget(QLabel("动作:"))
            available_layout.addWidget(self.motions_list)

            # 表情列表
            self.expressions_list = QListWidget()
            self.expressions_list.setSelectionMode(QListWidget.MultiSelection)
            available_layout.addWidget(QLabel("表情:"))
            available_layout.addWidget(self.expressions_list)

            splitter.addWidget(available_group)

            # 已选择组
            selected_group = QGroupBox("已选择（按顺序显示）")
            selected_layout = QVBoxLayout(selected_group)

            self.selected_list = QListWidget()
            self.selected_list.setDragDropMode(QListWidget.InternalMove)  # 支持拖拽排序
            selected_layout.addWidget(self.selected_list)

            # 操作按钮
            btn_layout = QHBoxLayout()
            self.add_btn = QPushButton("添加 →")
            self.add_btn.clicked.connect(self._add_selected)
            self.remove_btn = QPushButton("← 移除")
            self.remove_btn.clicked.connect(self._remove_selected)
            self.clear_btn = QPushButton("清空")
            self.clear_btn.clicked.connect(self._clear_selected)

            btn_layout.addWidget(self.add_btn)
            btn_layout.addWidget(self.remove_btn)
            btn_layout.addWidget(self.clear_btn)
            selected_layout.addLayout(btn_layout)

            splitter.addWidget(selected_group)
            layout.addWidget(splitter)

            # 对话框按钮
            button_box = QDialogButtonBox(
                QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
                Qt.Horizontal,
                self
            )
            button_box.accepted.connect(self._save_config)
            button_box.rejected.connect(self.reject)
            layout.addWidget(button_box)

            # 简化的样式
            self.setStyleSheet("""
                QDialog {
                    background: rgba(25, 25, 25, 180);
                    color: white;
                    border-radius: 20px;
                }
                QLabel {
                    color: white;
                    background: transparent;
                }
                QGroupBox {
                    color: white;
                    font-weight: bold;
                    border: 1px solid rgba(255, 255, 255, 30);
                    border-radius: 10px;
                    margin-top: 15px;
                    padding-top: 15px;
                    background: rgba(255, 255, 255, 8);
                }
                QGroupBox::title {
                    color: white;
                    subcontrol-origin: margin;
                    left: 15px;
                    padding: 0 10px 0 10px;
                    background: rgba(25, 25, 25, 180);
                    border-radius: 5px;
                }
                QListWidget {
                    background: rgba(17, 17, 17, 100);
                    color: white;
                    border: 1px solid rgba(255, 255, 255, 20);
                    border-radius: 8px;
                    padding: 8px;
                    outline: none;
                }
                QListWidget::item {
                    color: white;
                    padding: 8px;
                    margin: 2px;
                    border: none;
                    border-radius: 5px;
                    background: transparent;
                }
                QListWidget::item:hover {
                    background: rgba(255, 255, 255, 15);
                    border: 1px solid rgba(255, 255, 255, 30);
                }
                QListWidget::item:selected {
                    background: rgba(100, 200, 255, 50);
                    border: 1px solid rgba(100, 200, 255, 100);
                }
                QPushButton {
                    background: rgba(255, 255, 255, 10);
                    color: white;
                    border: 1px solid rgba(255, 255, 255, 40);
                    border-radius: 8px;
                    padding: 8px 16px;
                    min-width: 80px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background: rgba(255, 255, 255, 20);
                    border: 1px solid rgba(255, 255, 255, 60);
                }
                QPushButton:pressed {
                    background: rgba(255, 255, 255, 30);
                    border: 1px solid rgba(255, 255, 255, 80);
                }
            """)

        def _load_available_actions(self):
            """加载可用动作"""
            # 加载动作
            for motion in self.available_actions.get("motions", []):
                item = QListWidgetItem(f"{motion.get('icon', '🎭')} {motion.get('display', motion.get('name'))}")
                item.setData(Qt.UserRole, {
                    "type": "motion",
                    "name": motion.get("name"),
                    "display": motion.get("display"),
                    "icon": motion.get("icon", "🎭")
                })
                self.motions_list.addItem(item)

            # 加载表情
            for expression in self.available_actions.get("expressions", []):
                item = QListWidgetItem(f"{expression.get('icon', '😀')} {expression.get('display', expression.get('name'))}")
                item.setData(Qt.UserRole, {
                    "type": "expression",
                    "name": expression.get("name"),
                    "display": expression.get("display"),
                    "icon": expression.get("icon", "😀")
                })
                self.expressions_list.addItem(item)

        def _load_current_config(self):
            """加载当前配置"""
            for action in self.current_config:
                item = QListWidgetItem(f"{action.get('icon', '')} {action.get('display', action.get('name'))}")
                item.setData(Qt.UserRole, action)
                self.selected_list.addItem(item)

        def _add_selected(self):
            """添加选中的动作"""
            if self.selected_list.count() >= 8:
                logger.warning("最多只能选择8个动作")
                return

            # 从动作列表添加
            for item in self.motions_list.selectedItems():
                if self.selected_list.count() >= 8:
                    break
                data = item.data(Qt.UserRole)
                # 检查是否已存在
                exists = False
                for i in range(self.selected_list.count()):
                    if self.selected_list.item(i).data(Qt.UserRole)["name"] == data["name"]:
                        exists = True
                        break
                if not exists:
                    new_item = QListWidgetItem(item.text())
                    new_item.setData(Qt.UserRole, data)
                    self.selected_list.addItem(new_item)

            # 从表情列表添加
            for item in self.expressions_list.selectedItems():
                if self.selected_list.count() >= 8:
                    break
                data = item.data(Qt.UserRole)
                # 检查是否已存在
                exists = False
                for i in range(self.selected_list.count()):
                    if self.selected_list.item(i).data(Qt.UserRole)["name"] == data["name"]:
                        exists = True
                        break
                if not exists:
                    new_item = QListWidgetItem(item.text())
                    new_item.setData(Qt.UserRole, data)
                    self.selected_list.addItem(new_item)

            # 清除选择
            self.motions_list.clearSelection()
            self.expressions_list.clearSelection()

        def _remove_selected(self):
            """移除选中的项"""
            for item in self.selected_list.selectedItems():
                self.selected_list.takeItem(self.selected_list.row(item))

        def _clear_selected(self):
            """清空已选择"""
            self.selected_list.clear()

        def _save_config(self):
            """保存配置"""
            config = []
            for i in range(self.selected_list.count()):
                item = self.selected_list.item(i)
                config.append(item.data(Qt.UserRole))

            self.config_updated.emit({"selected_actions": config})
            self.accept()

        def get_config(self):
            """获取配置"""
            config = []
            for i in range(self.selected_list.count()):
                item = self.selected_list.item(i)
                config.append(item.data(Qt.UserRole))
            return config

# 兼容性导出
__all__ = ['Live2DConfigDialog']