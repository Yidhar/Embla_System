# -*- mode: python ; coding: utf-8 -*-
"""
NagaAgent macOS PyInstaller Spec File
生成单文件 APP 应用程序
"""

import os
import sys
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(SPECPATH).parent.parent
HOOKS_DIR = PROJECT_ROOT / 'package' / 'hooks'

# 收集所有模块
block_cipher = None

# 需要打包的数据文件
datas = [
    # 前端静态文件
    (str(PROJECT_ROOT / 'frontend'), 'frontend'),
    # UI 资源
    (str(PROJECT_ROOT / 'ui' / 'img'), 'ui/img'),
    (str(PROJECT_ROOT / 'ui' / 'styles'), 'ui/styles'),
    # 配置示例
    (str(PROJECT_ROOT / 'config.json.example'), '.'),
    # nagaagent-core 本地包
    (str(PROJECT_ROOT / 'nagaagent_core'), 'nagaagent_core'),
    # logs 目录结构
    (str(PROJECT_ROOT / 'logs'), 'logs'),
]

# 可选：游戏资源（如果存在）
if (PROJECT_ROOT / 'game').exists():
    datas.append((str(PROJECT_ROOT / 'game'), 'game'))

# 隐藏导入 - 动态导入的模块
hiddenimports = [
    # 标准库
    'sqlite3',
    'webbrowser',
    'timeit',
    'asyncio',
    'logging',
    'socket',
    'threading',
    'warnings',
    'subprocess',
    'json',
    'redis',

    # 核心依赖
    'key_value',
    'key_value.aio',
    'uvicorn',
    'uvicorn.logging',
    'uvicorn.protocols',
    'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan',
    'uvicorn.lifespan.on',
    'fastapi',
    'fastapi.middleware',
    'starlette',
    'pydantic',

    # PyQt5
    'PyQt5',
    'PyQt5.QtCore',
    'PyQt5.QtGui',
    'PyQt5.QtWidgets',
    'PyQt5.QtWebEngineWidgets',
    'PyQt5.QtWebChannel',
    'PyQt5.sip',

    # OpenGL
    'OpenGL',
    'OpenGL.GL',
    'OpenGL.GLU',
    'OpenGL.GLUT',
    'OpenGL.platform',
    'OpenGL.platform.darwin',
    'OpenGL.platform.base_platform',
    'OpenGL_accelerate',

    # Live2D
    'live2d',
    'live2d.v3',

    # 音频处理
    'sounddevice',
    'simpleaudio',
    'pydub',
    'librosa',
    'pygame',
    'pygame.mixer',

    # AI 相关
    'openai',
    'dashscope',
    'langchain',
    'langchain_openai',
    'langchain_community',

    # 网络
    'aiohttp',
    'requests',
    'httpx',
    'httpcore',
    'websockets',

    # 数据处理
    'numpy',
    'scipy',
    'onnxruntime',
    'pillow',
    'PIL',

    # 图数据库
    'neo4j',
    'py2neo',

    # MCP
    'mcp',
    'fastmcp',

    # 其他
    'pystray',
    'paho',
    'paho.mqtt',
    'paho.mqtt.client',
    'markdown',
    'emoji',
    'charset_normalizer',
    'json5',

    # 项目模块
    'apiserver',
    'apiserver.api_server',
    'agentserver',
    'agentserver.agent_server',
    'mcpserver',
    'mcpserver.mcp_server',
    'summer_memory',
    'summer_memory.memory_manager',
    'summer_memory.task_manager',
    'summer_memory.quintuple_graph',
    'system',
    'system.config',
    'system.system_checker',
    'ui',
    'ui.pyqt_chat_window',
    'ui.tray',
    'ui.tray.console_tray',
    'voice',
    'voice.output',
    'voice.output.start_voice_service',
    'mqtt_tool',
    'mqtt_tool.device_switch',
    'thinking',
    'nagaagent_core',
    'nagaagent_core.vendors',
    'nagaagent_core.vendors.PyQt5',
    'nagaagent_core.vendors.PyQt5.QtCore',
    'nagaagent_core.vendors.PyQt5.QtGui',
    'nagaagent_core.vendors.PyQt5.QtWidgets',
    'nagaagent_core.vendors.charset_normalizer',
    'nagaagent_core.vendors.json5',
    'nagaagent_core.api',
]

# 排除的模块（减小体积）
excludes = [
    'tkinter',
    'matplotlib',
    'IPython',
    'jupyter',
    'notebook',
    'test',
    'tests',
    'unittest',
    'pytest',
]

a = Analysis(
    [str(PROJECT_ROOT / 'main.py')],
    pathex=[str(PROJECT_ROOT), str(PROJECT_ROOT / 'nagaagent_core')],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[str(HOOKS_DIR)],
    hooksconfig={},
    runtime_hooks=[str(HOOKS_DIR / 'rthook-opengl.py')],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='NagaAgent',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # macOS APP 不显示控制台
    disable_windowed_traceback=False,
    argv_emulation=True,  # macOS 需要参数模拟
    target_arch=None,  # 自动检测架构 (x86_64 或 arm64)
    codesign_identity=None,
    entitlements_file=None,
    icon=str(PROJECT_ROOT / 'package' / 'resources' / 'icon.icns') if (PROJECT_ROOT / 'package' / 'resources' / 'icon.icns').exists() else None,
)

# 创建 macOS APP Bundle
app = BUNDLE(
    exe,
    name='NagaAgent.app',
    icon=str(PROJECT_ROOT / 'package' / 'resources' / 'icon.icns') if (PROJECT_ROOT / 'package' / 'resources' / 'icon.icns').exists() else None,
    bundle_identifier='com.nagaagent.app',
    info_plist={
        'CFBundleName': 'NagaAgent',
        'CFBundleDisplayName': 'NagaAgent',
        'CFBundleVersion': '4.0.0',
        'CFBundleShortVersionString': '4.0.0',
        'CFBundleIdentifier': 'com.nagaagent.app',
        'CFBundlePackageType': 'APPL',
        'CFBundleSignature': '????',
        'CFBundleExecutable': 'NagaAgent',
        'NSHighResolutionCapable': True,
        'NSRequiresAquaSystemAppearance': False,  # 支持 Dark Mode
        'LSMinimumSystemVersion': '10.13.0',
        'NSMicrophoneUsageDescription': 'NagaAgent 需要麦克风权限以支持语音输入功能',
        'NSAppleEventsUsageDescription': 'NagaAgent 需要此权限以控制其他应用',
    },
)
