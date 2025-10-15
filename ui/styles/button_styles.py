"""
按钮样式配置文件
将PyQt按钮样式从主界面代码中解耦出来
"""

# 文档上传按钮样式
UPLOAD_BUTTON_STYLE = """
QPushButton {
    background: rgba(100, 200, 255, 150);
    border: 1px solid rgba(100, 200, 255, 200);
    border-radius: 22px;
    color: #fff;
    font: 14pt;
    font-weight: bold;
}
QPushButton:hover {
    background: rgba(120, 220, 255, 180);
    border: 1px solid rgba(120, 220, 255, 220);
}
QPushButton:pressed {
    background: rgba(80, 180, 255, 200);
}
"""

# 心智云图按钮样式（与上传按钮相同）
MIND_MAP_BUTTON_STYLE = UPLOAD_BUTTON_STYLE

# 实时语音按钮样式
VOICE_REALTIME_BUTTON_STYLE = """
QPushButton {
    background: rgba(255, 100, 100, 150);
    border: 1px solid rgba(255, 100, 100, 200);
    border-radius: 22px;
    color: #fff;
    font: 14pt;
    font-weight: bold;
}
QPushButton:hover {
    background: rgba(255, 120, 120, 180);
    border: 1px solid rgba(255, 120, 120, 220);
}
QPushButton:pressed {
    background: rgba(255, 80, 80, 200);
}
QPushButton[recording="true"] {
    background: rgba(255, 50, 50, 200);
    border: 2px solid rgba(255, 150, 150, 255);
}
QPushButton[ai_speaking="true"] {
    background: rgba(100, 255, 100, 150);
    border: 2px solid rgba(100, 255, 100, 255);
}
"""

# Live2D按钮样式
LIVE2D_BUTTON_STYLE = """
QPushButton {
    background: rgba(255, 100, 255, 150);
    border: 1px solid rgba(255, 100, 255, 200);
    border-radius: 22px;
    color: #fff;
    font: 14pt;
    font-weight: bold;
}
QPushButton:hover {
    background: rgba(255, 120, 255, 180);
    border: 1px solid rgba(255, 120, 255, 220);
}
QPushButton:pressed {
    background: rgba(255, 80, 255, 200);
}
QPushButton[live2d_active="true"] {
    background: rgba(255, 50, 255, 200);
    border: 2px solid rgba(255, 150, 255, 255);
}
"""
# 文档操作按钮样式
DOCUMENT_ACTION_BUTTON_STYLE = """
QPushButton {
    background-color: #3498db;
    color: white;
    border: none;
    border-radius: 8px;
    font-size: 14px;
    font-weight: bold;
    padding: 10px;
}
QPushButton:hover {
    background-color: #2980b9;
}
QPushButton:pressed {
    background-color: #21618c;
}
"""

# 取消按钮样式
CANCEL_BUTTON_STYLE = """
QPushButton {
    background-color: #95a5a6;
    color: white;
    border: none;
    border-radius: 6px;
    font-size: 13px;
}
QPushButton:hover {
    background-color: #7f8c8d;
}
"""

# 按钮配置
BUTTON_CONFIGS = {
    "upload": {
        "icon": "📄",
        "tooltip": "上传文档",
        "size": (44, 44),
        "style": UPLOAD_BUTTON_STYLE
    },
    "mind_map": {
        "icon": "🔐", 
        "tooltip": "心智云图",
        "size": (44, 44),
        "style": MIND_MAP_BUTTON_STYLE
    },
    "self_game": {  # 自我博弈入口 #
        "icon": "🎮",
        "tooltip": "自我博弈",
        "size": (44, 44),
        "style": UPLOAD_BUTTON_STYLE
    },
    "voice_realtime": {  # 实时语音按钮 #
        "icon": "🎤",
        "tooltip": "实时语音对话",
        "size": (44, 44),
        "style": VOICE_REALTIME_BUTTON_STYLE
    },
    "live2d": {  # Live2D切换按钮 #
        "icon": "🎭",
        "tooltip": "切换Live2D/图片模式",
        "size": (44, 44),
        "style": LIVE2D_BUTTON_STYLE
    }
} 
