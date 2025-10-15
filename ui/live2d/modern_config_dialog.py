#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Live2D动作配置对话框 - 优雅版本
采用卡片式网格布局，提供更现代的交互体验
"""

from nagaagent_core.vendors.PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QWidget, QGridLayout, QLineEdit,
    QScrollArea, QTabWidget
)
from nagaagent_core.vendors.PyQt5.QtCore import (
    Qt, pyqtSignal, QSize, QTimer, QPoint
)
from nagaagent_core.vendors.PyQt5.QtGui import QFont
import json
import os
import logging

from ui.styles.settings_styles import (
    INPUT_STYLE,
    SCROLL_AREA_STYLE,
    SCROLL_CONTENT_STYLE,
    LABEL_STYLE,
    STATUS_LABEL_STYLE,
    SAVE_BUTTON_STYLE,
    RESET_BUTTON_STYLE,
    DIALOG_HEADER_TITLE_STYLE,
    DIALOG_HINT_LABEL_STYLE,
    DIALOG_TAB_BAR_STYLE,
    DIALOG_SEARCH_CONTAINER_STYLE,
    ACTION_CARD_WIDGET_STYLE,
)

logger = logging.getLogger("live2d.config_dialog")


class ActionCard(QWidget):
    """单个动作/表情卡片"""

    clicked = pyqtSignal(dict)  # 点击信号

    def __init__(self, action_data, parent=None):
        super().__init__(parent)
        self.action_data = action_data
        self.selected = False
        self.setObjectName("Live2DActionCard")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedSize(150, 180)
        self.setCursor(Qt.PointingHandCursor)

        self.setup_ui()
        self.setStyleSheet(ACTION_CARD_WIDGET_STYLE)
        self.update_state()

    def setup_ui(self):
        """初始化UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(6)

        self.icon_label = QLabel(self.action_data.get('icon', '🎭'))
        self.icon_label.setObjectName("Live2DActionIcon")
        self.icon_label.setAlignment(Qt.AlignCenter)
        icon_font = QFont("Segoe UI Emoji")
        if icon_font.family() != "Segoe UI Emoji":
            icon_font = QFont()
        icon_font.setPointSize(24)
        self.icon_label.setFont(icon_font)
        layout.addWidget(self.icon_label, alignment=Qt.AlignHCenter)

        display_name = self.action_data.get('display', self.action_data.get('name', ''))
        self.name_label = QLabel(display_name)
        self.name_label.setObjectName("Live2DActionName")
        self.name_label.setAlignment(Qt.AlignCenter)
        self.name_label.setWordWrap(True)
        name_font = QFont("Lucida Console")
        name_font.setPointSize(10)
        name_font.setBold(True)
        self.name_label.setFont(name_font)
        layout.addWidget(self.name_label)

        type_text = "动作" if self.action_data.get('type') == 'motion' else "表情"
        self.type_label = QLabel(type_text)
        self.type_label.setObjectName("Live2DActionType")
        self.type_label.setAlignment(Qt.AlignCenter)
        type_font = QFont("Lucida Console")
        type_font.setPointSize(9)
        self.type_label.setFont(type_font)
        layout.addWidget(self.type_label)

        layout.addStretch(1)

    def set_selected(self, selected):
        """设置选中状态"""
        if self.selected != selected:
            self.selected = selected
            self.update_state()

    def update_state(self):
        self.setProperty("selected", self.selected)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def enterEvent(self, event):
        super().enterEvent(event)

    def leaveEvent(self, event):
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        """鼠标点击"""
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.action_data)
        super().mousePressEvent(event)


class SearchBar(QWidget):
    """搜索栏"""

    search_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Live2DSearchContainer")
        self.setStyleSheet(DIALOG_SEARCH_CONTAINER_STYLE)
        self.setup_ui()

    def setup_ui(self):
        """初始化UI"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # 搜索图标
        icon_label = QLabel("🔍")
        icon_label.setStyleSheet(
            "color: rgba(255, 255, 255, 180); font: 12pt 'Lucida Console'; padding: 0 6px;"
        )
        layout.addWidget(icon_label)

        # 搜索输入框
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜索动作或表情...")
        self.search_input.setStyleSheet(INPUT_STYLE)
        self.search_input.textChanged.connect(self.search_changed)
        layout.addWidget(self.search_input, 1)

        # 清除按钮
        self.clear_btn = QPushButton("✕")
        self.clear_btn.setFixedSize(30, 30)
        self.clear_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: rgba(255, 255, 255, 160);
                border: none;
                font: 11pt 'Lucida Console';
                border-radius: 15px;
            }
            QPushButton:hover {
                color: #fff;
            }
        """)
        self.clear_btn.setCursor(Qt.PointingHandCursor)
        self.clear_btn.clicked.connect(self.clear_search)
        self.clear_btn.setVisible(False)
        layout.addWidget(self.clear_btn)

        # 监听文本变化
        self.search_input.textChanged.connect(self.on_text_changed)

    def on_text_changed(self, text):
        """文本变化处理"""
        self.clear_btn.setVisible(bool(text))

    def clear_search(self):
        """清除搜索"""
        self.search_input.clear()


class ModernLive2DConfigDialog(QDialog):
    """现代化的Live2D动作配置对话框"""

    config_updated = pyqtSignal(dict)  # 配置更新信号

    def __init__(self, available_actions=None, current_config=None, parent=None):
        super().__init__(parent)
        self.available_actions = available_actions or {"motions": [], "expressions": []}
        self.current_config = current_config or []
        self.selected_actions = []  # 已选择的动作列表
        self.action_items = []  # 所有动作/表情数据

        logger.info(
            "初始化 Live2D 配置对话框: motions=%d, expressions=%d, current=%d",
            len(self.available_actions.get("motions", [])),
            len(self.available_actions.get("expressions", [])),
            len(self.current_config),
        )

        self.setWindowTitle("配置 Live2D 动作")
        self.setModal(True)
        self.resize(900, 650)

        # 设置窗口样式
        self.setStyleSheet(self.get_dialog_style())
        self.setAttribute(Qt.WA_TranslucentBackground)

        self.setup_ui()
        self.load_actions()
        self.load_current_config()
        # 移除这个延迟调用，因为现在已经在 load_current_config 中正确调用了
        # QTimer.singleShot(100, self.update_card_display)

    def get_dialog_style(self):
        """获取对话框样式"""
        return (
            LABEL_STYLE
            + DIALOG_TAB_BAR_STYLE
            + """
QDialog {
    background: rgba(22, 22, 28, 235);
    border-radius: 24px;
}

QTabWidget::tab-bar {
    alignment: center;
}

QScrollArea {
    background: transparent;
    border: none;
}

QScrollBar:vertical {
    background: rgba(255, 255, 255, 18);
    width: 8px;
    border-radius: 4px;
}

QScrollBar::handle:vertical {
    background: rgba(255, 255, 255, 60);
    border-radius: 4px;
    min-height: 32px;
}

QScrollBar::handle:vertical:hover {
    background: rgba(255, 255, 255, 80);
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0px;
}
            """
        )

    def setup_ui(self):
        """初始化UI"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 24, 24, 24)
        main_layout.setSpacing(16)

        # 标题区域
        self.create_header(main_layout)

        # 搜索栏
        self.search_bar = SearchBar()
        self.search_bar.search_changed.connect(self.filter_actions)
        main_layout.addWidget(self.search_bar)

        # 内容区域 - 使用标签页
        self.tab_widget = QTabWidget()
        self.tab_widget.setDocumentMode(True)
        self.tab_widget.setStyleSheet(DIALOG_TAB_BAR_STYLE)

        # 所有动作标签页
        self.all_tab, self.all_layout = self.create_actions_tab()
        self.tab_widget.addTab(self.all_tab, "全部")

        # 动作标签页
        self.motions_tab, self.motions_layout = self.create_actions_tab()
        self.tab_widget.addTab(self.motions_tab, "动作")

        # 表情标签页
        self.expressions_tab, self.expressions_layout = self.create_actions_tab()
        self.tab_widget.addTab(self.expressions_tab, "表情")

        # 已选择标签页
        self.selected_tab = self.create_selected_tab()
        self.tab_widget.addTab(self.selected_tab, f"已选择 (0/8)")

        main_layout.addWidget(self.tab_widget)

        # 底部按钮
        self.create_buttons(main_layout)

    def create_header(self, parent_layout):
        """创建标题区域"""
        header_layout = QHBoxLayout()

        # 标题
        title_label = QLabel("Live2D 动作配置")
        title_label.setStyleSheet(DIALOG_HEADER_TITLE_STYLE)
        header_layout.addWidget(title_label)

        header_layout.addStretch()

        # 提示文本
        hint_label = QLabel("选择最多 8 个动作或表情")
        hint_label.setStyleSheet(DIALOG_HINT_LABEL_STYLE)
        hint_label.setContentsMargins(12, 0, 0, 0)
        header_layout.addWidget(hint_label)

        parent_layout.addLayout(header_layout)

    def create_actions_tab(self):
        """创建动作标签页"""
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setStyleSheet(SCROLL_AREA_STYLE)

        content_widget = QWidget()
        content_widget.setStyleSheet(SCROLL_CONTENT_STYLE)
        grid_layout = QGridLayout()
        grid_layout.setSpacing(12)
        grid_layout.setContentsMargins(12, 12, 12, 12)
        content_widget.setLayout(grid_layout)

        scroll_area.setWidget(content_widget)
        return scroll_area, grid_layout

    def create_selected_tab(self):
        """创建已选择标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # 提示信息
        self.selected_hint = QLabel("暂无选择")
        self.selected_hint.setStyleSheet(DIALOG_HINT_LABEL_STYLE)
        self.selected_hint.setAlignment(Qt.AlignCenter)
        self.selected_hint.setContentsMargins(0, 16, 0, 16)
        layout.addWidget(self.selected_hint)

        # 已选择的网格
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setStyleSheet(SCROLL_AREA_STYLE)

        self.selected_content = QWidget()
        self.selected_content.setStyleSheet(SCROLL_CONTENT_STYLE)
        self.selected_grid = QGridLayout(self.selected_content)
        self.selected_grid.setSpacing(12)
        self.selected_grid.setContentsMargins(12, 12, 12, 12)

        scroll_area.setWidget(self.selected_content)
        layout.addWidget(scroll_area)

        # 清空按钮
        clear_btn = QPushButton("清空所有选择")
        clear_btn.setStyleSheet(RESET_BUTTON_STYLE)
        clear_btn.setCursor(Qt.PointingHandCursor)
        clear_btn.clicked.connect(self.clear_all_selections)
        layout.addWidget(clear_btn, 0, Qt.AlignCenter)

        return widget

    def create_buttons(self, parent_layout):
        """创建底部按钮"""
        button_layout = QHBoxLayout()
        button_layout.setSpacing(12)
        button_layout.setContentsMargins(0, 12, 0, 0)

        # 统计标签
        self.count_label = QLabel("已选择: 0 / 8")
        self.count_label.setStyleSheet(STATUS_LABEL_STYLE)
        button_layout.addWidget(self.count_label)

        button_layout.addStretch()

        # 取消按钮
        cancel_btn = QPushButton("取消")
        cancel_btn.setFixedSize(100, 40)
        cancel_btn.setStyleSheet(RESET_BUTTON_STYLE)
        cancel_btn.setCursor(Qt.PointingHandCursor)
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        # 确定按钮
        self.ok_btn = QPushButton("确定")
        self.ok_btn.setFixedSize(100, 40)
        self.ok_btn.setStyleSheet(SAVE_BUTTON_STYLE)
        self.ok_btn.setCursor(Qt.PointingHandCursor)
        self.ok_btn.clicked.connect(self.save_config)
        button_layout.addWidget(self.ok_btn)

        parent_layout.addLayout(button_layout)

    def load_actions(self):
        """加载所有动作"""
        # 重置动作项缓存
        self.action_items = []

        # 加载动作
        for motion in self.available_actions.get("motions", []):
            card_data = {
                "type": "motion",
                "name": motion.get("name"),
                "display": motion.get("display", motion.get("name")),
                "icon": motion.get("icon", "🎭")
            }
            self.action_items.append(card_data)

        # 加载表情
        for expression in self.available_actions.get("expressions", []):
            card_data = {
                "type": "expression",
                "name": expression.get("name"),
                "display": expression.get("display", expression.get("name")),
                "icon": expression.get("icon", "😀")
            }
            self.action_items.append(card_data)

        logger.info(
            "Live2D 配置对话框加载动作: motions=%d, expressions=%d, total=%d",
            len(self.available_actions.get("motions", [])),
            len(self.available_actions.get("expressions", [])),
            len(self.action_items),
        )
        # 注意：这里先不调用 update_card_display，等 load_current_config 完成后统一调用

    def load_current_config(self):
        """加载当前配置"""
        for action in self.current_config:
            matching = next(
                (item for item in self.action_items if item.get("name") == action.get("name")),
                None,
            )
            if matching and matching not in self.selected_actions:
                self.selected_actions.append(matching)

        logger.info(f"加载了 {len(self.selected_actions)} 个已选择的动作")

        self.update_selection_display()
        # 现在在这里调用 update_card_display，确保选中状态能正确显示
        self.update_card_display()

    def update_card_display(self):
        """更新卡片显示"""
        # 清理所有网格
        for layout in (self.all_layout, self.motions_layout, self.expressions_layout):
            self.clear_layout(layout)

        # 根据搜索文本过滤
        search_text = self.search_bar.search_input.text().lower()

        # 分类卡片
        all_items = []
        motion_items = []
        expression_items = []

        for item in self.action_items:
            if not item.get("name"):
                continue

            if search_text:
                display = (item.get("display") or "").lower()
                raw_name = (item.get("name") or "").lower()
                if search_text not in display and search_text not in raw_name:
                    continue

            all_items.append(item)

            if item.get("type") == "motion":
                motion_items.append(item)
            else:
                expression_items.append(item)

        # 添加到对应的标签页
        self.add_cards_to_grid(self.all_layout, all_items)
        self.add_cards_to_grid(self.motions_layout, motion_items)
        self.add_cards_to_grid(self.expressions_layout, expression_items)

        logger.info(
            "Live2D 对话框刷新卡片: all=%d, motions=%d, expressions=%d, filter='%s'",
            len(all_items),
            len(motion_items),
            len(expression_items),
            search_text,
        )
        logger.info(
            "布局统计: all_layout=%d, motions_layout=%d, expressions_layout=%d",
            self.all_layout.count(),
            self.motions_layout.count(),
            self.expressions_layout.count(),
        )

    def add_cards_to_grid(self, layout, items):
        """将卡片添加到网格布局"""
        if layout is None:
            logger.warning("布局对象为空，无法添加卡片")
            return

        # 如果没有项目，显示空状态提示
        if not items:
            empty_label = QLabel("暂无可用项目")
            empty_label.setStyleSheet("""
                QLabel {
                    color: rgba(255, 255, 255, 100);
                    font: 11pt 'Lucida Console';
                    padding: 32px;
                }
            """)
            empty_label.setAlignment(Qt.AlignCenter)
            layout.addWidget(empty_label, 0, 0, 1, 5, Qt.AlignCenter)
            logger.info("显示空状态提示")
            return

        logger.info("开始添加 %d 个卡片到布局", len(items))
        col_count = 5  # 每行5个卡片
        for i, item in enumerate(items):
            row = i // col_count
            col = i % col_count
            try:
                card = self.create_card_widget(item)
                if card is None:
                    logger.error("create_card_widget 返回了 None: item=%s", item)
                    continue
                layout.addWidget(card, row, col, Qt.AlignTop)
                logger.debug(
                    "成功添加卡片到布局: name=%s type=%s row=%d col=%d",
                    item.get("name"),
                    item.get("type"),
                    row,
                    col,
                )
            except Exception as e:
                logger.error("添加卡片失败: item=%s, error=%s", item, e, exc_info=True)

        # 添加拉伸项
        layout.setRowStretch(layout.rowCount(), 1)
        logger.info("完成添加卡片，布局控件数量: %d", layout.count())

    def clear_layout(self, layout):
        """清空布局中的所有控件"""
        if layout is None:
            return

        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                logger.debug("移除旧卡片: %s", getattr(widget, "action_data", {}))
                widget.setParent(None)

    def create_card_widget(self, item):
        """根据数据创建卡片控件"""
        logger.debug("创建卡片: name=%s, display=%s, icon=%s, type=%s",
                    item.get("name"), item.get("display"),
                    item.get("icon"), item.get("type"))
        card = ActionCard(dict(item))
        is_selected = any(sel.get("name") == item.get("name") for sel in self.selected_actions)
        card.set_selected(is_selected)
        card.clicked.connect(self.on_card_clicked)
        logger.debug("卡片创建成功: %s, 选中状态=%s", item.get("name"), is_selected)
        return card  # 返回创建的卡片

    def filter_actions(self, text):
        """过滤动作"""
        self.update_card_display()

    def on_card_clicked(self, action_data):
        """卡片点击处理"""
        # 切换选中状态
        name = action_data.get("name")
        if not name:
            return

        if any(item.get("name") == name for item in self.selected_actions):
            self.selected_actions = [a for a in self.selected_actions if a.get("name") != name]
        else:
            if len(self.selected_actions) >= 8:
                self.show_limit_hint()
                return
            matching = next(
                (item for item in self.action_items if item.get("name") == name),
                action_data,
            )
            self.selected_actions.append(matching)

        self.update_selection_display()
        self.update_card_display()

    def show_limit_hint(self):
        """显示数量限制提示"""
        # 创建临时提示标签
        hint = QLabel("最多只能选择 8 个项目", self)
        hint.setStyleSheet("""
            background: rgba(255, 120, 120, 220);
            color: #fff;
            padding: 8px 18px;
            border-radius: 18px;
            border: 1px solid rgba(255, 180, 180, 200);
            font: 10pt 'Lucida Console';
        """)
        hint.setAlignment(Qt.AlignCenter)

        # 计算位置（居中显示）
        hint.adjustSize()
        x = (self.width() - hint.width()) // 2
        y = self.height() - 100
        hint.move(x, y)
        hint.show()

        # 2秒后自动隐藏
        QTimer.singleShot(2000, hint.deleteLater)

    def update_selection_display(self):
        """更新选择显示"""
        count = len(self.selected_actions)

        # 更新统计标签
        self.count_label.setText(f"已选择: {count} / 8")

        # 更新标签页标题
        self.tab_widget.setTabText(3, f"已选择 ({count}/8)")

        # 更新已选择标签页内容
        if count == 0:
            self.selected_hint.setVisible(True)
            self.selected_hint.setText("暂无选择")
        else:
            self.selected_hint.setVisible(False)

        # 清空已选择网格
        while self.selected_grid.count():
            item = self.selected_grid.takeAt(0)
            if item.widget():
                item.widget().setParent(None)

        # 添加已选择的卡片副本
        col_count = 5
        for i, action in enumerate(self.selected_actions):
            card = self.create_card_widget(action)
            card.set_selected(True)
            row = i // col_count
            col = i % col_count
            self.selected_grid.addWidget(card, row, col, Qt.AlignTop)

    def clear_all_selections(self):
        """清空所有选择"""
        # 清空选择列表
        self.selected_actions.clear()

        # 更新显示
        self.update_selection_display()
        self.update_card_display()  # 刷新所有卡片的选中状态

    def save_config(self):
        """保存配置"""
        # 发送配置更新信号
        self.config_updated.emit({"selected_actions": self.selected_actions})
        self.accept()

    def get_config(self):
        """获取配置"""
        return self.selected_actions


# 导出新的对话框类，替代旧的
Live2DConfigDialog = ModernLive2DConfigDialog
