# 🎨 UI样式模块

## 📋 模块概述

本模块将PyQt界面中的UI组件样式从主界面代码中解耦出来，提供统一的样式管理、按钮创建接口和进度显示组件。

## 📁 文件结构

```
ui/styles/
├── __init__.py              # 模块初始化文件
├── button_styles.py         # 按钮样式配置
├── button_factory.py        # 按钮工厂类
├── progress_widget.py       # 进度显示组件
├── progress.txt             # 进度相关配置文件
└── README.md               # 本说明文档
```

## 🔧 使用方法

### 1. 创建操作按钮

```python
from ui.styles.button_factory import ButtonFactory

# 创建上传文档按钮
upload_btn = ButtonFactory.create_action_button("upload", parent)

# 创建心智云图按钮
mind_map_btn = ButtonFactory.create_action_button("mind_map", parent)
```

### 2. 创建文档操作按钮

```python
# 创建文档操作按钮（如"分析文档"、"生成摘要"等）
action_btn = ButtonFactory.create_document_action_button("🔍 分析文档", parent)
```

### 3. 创建取消按钮

```python
# 创建取消按钮
cancel_btn = ButtonFactory.create_cancel_button("取消", parent)
```

### 4. 使用进度显示组件

```python
from ui.styles.progress_widget import EnhancedProgressWidget

# 创建增强版进度组件
progress_widget = EnhancedProgressWidget(parent)

# 设置思考模式
progress_widget.set_thinking_mode()

# 更新进度
progress_widget.update_progress(50, "正在处理...")

# 停止加载
progress_widget.stop_loading()
```

## 🎨 样式配置

### 支持的操作按钮类型

| 按钮类型 | 图标 | 工具提示 | 大小 |
|----------|------|----------|------|
| upload | 📄 | 上传文档 | 44x44px |
| mind_map | 🔐 | 心智云图 | 44x44px |

### 样式特点

1. **操作按钮**: 蓝色渐变背景，圆角设计，悬停效果
2. **文档操作按钮**: 蓝色背景，圆角设计，适合对话框
3. **取消按钮**: 灰色背景，简洁设计

### 进度组件特点

1. **基础进度组件**: 支持加载动画、进度条、状态显示
2. **增强进度组件**: 在基础组件上添加取消按钮和多种模式
3. **动画效果**: 淡入淡出动画、脉冲文字动画、GIF动画支持
4. **多种模式**: 思考模式、生成模式、处理模式
5. **配置文件**: progress.txt用于存储进度相关的配置信息

## 🔄 扩展新按钮

### 1. 在 `button_styles.py` 中添加新配置

```python
# 新增按钮样式
NEW_BUTTON_STYLE = """
QPushButton {
    background: rgba(100, 200, 255, 150);
    border: 1px solid rgba(100, 200, 255, 200);
    border-radius: 22px;
    color: #fff;
    font: 14pt;
    font-weight: bold;
}
"""

# 在 BUTTON_CONFIGS 中添加配置
BUTTON_CONFIGS = {
    # ... 现有配置
    "new_button": {
        "icon": "🆕",
        "tooltip": "新功能",
        "size": (44, 44),
        "style": NEW_BUTTON_STYLE
    }
}
```

### 2. 使用新按钮

```python
new_btn = ButtonFactory.create_action_button("new_button", parent)
```

## ✅ 优势

1. **解耦**: 样式与业务逻辑分离
2. **统一**: 所有UI组件样式统一管理
3. **可维护**: 修改样式只需修改配置文件
4. **可扩展**: 轻松添加新的组件类型
5. **复用**: 样式可以在多个界面中复用
6. **模块化**: 按钮、进度组件等独立管理

## 🚀 迁移完成

原有的内联样式代码已被替换为工厂模式和组件化设计，代码更加简洁和可维护。 