# -*- mode: python ; coding: utf-8 -*-

# pyproject.toml requires python >=3.11,<3.12

# 导入必要的模块
from PyInstaller.utils.hooks import copy_metadata
import os

# 收集包的 metadata
metadata_packages = ['fastmcp']
datas = []
for package in metadata_packages:
    try:
        datas += copy_metadata(package)
    except Exception as e:
        print(f"Warning: Could not copy metadata for {package}: {e}")

# 收集所有需要的资源文件
# (source_path, destination_in_bundle)
datas += [
    ('config.json.example', '.'),
    ('config.json', '.'),
    ('LICENSE', '.'),
    ('pyproject.toml', '.'),
    ('README.md', '.'),
    ('requirements.txt', '.'),
]

# 收集需要包含的目录
# Tree 对象需要在 Analysis 中单独处理
trees = [
    Tree('agentserver', prefix='agentserver'),
    Tree('apiserver', prefix='apiserver'),
    Tree('game', prefix='game'),
    Tree('logs', prefix='logs'),
    Tree('mcpserver', prefix='mcpserver'),
    Tree('mqtt_tool', prefix='mqtt_tool'),
    Tree('summer_memory', prefix='summer_memory'),
    Tree('system', prefix='system'),
    Tree('ui', prefix='ui'),
    Tree('voice', prefix='voice'),
]

# 添加py2neo包的VERSION文件到数据文件
import py2neo
py2neo_path = py2neo.__file__
py2neo_dir = os.path.dirname(py2neo_path)
version_file = os.path.join(py2neo_dir, 'VERSION')
if os.path.exists(version_file):
    datas.append((version_file, 'py2neo'))

# 添加图标文件到数据文件
icon_files = [
    'ui/img/icons/naga_chat.png',
    'ui/img/icons/love_adventure.png',
    'ui/img/icons/personality_game.png',
    'ui/img/icons/mind_map.png'
]
for icon_file in icon_files:
    if os.path.exists(icon_file):
        datas.append((icon_file, 'ui/img/icons'))

# 添加样式文件到数据文件
datas.append(('ui/styles/progress.txt', 'ui/styles'))

# 收集所有 agent-manifest.json 文件
from pathlib import Path
for manifest_path in Path('mcpserver').rglob('agent-manifest.json'):
    datas.append((str(manifest_path), str(manifest_path.parent)))

# 添加OpenGL相关的数据文件
import OpenGL
opengl_path = OpenGL.__file__
opengl_dir = os.path.dirname(opengl_path)

# 收集OpenGL平台文件
platform_dirs = []
for item in os.listdir(opengl_dir):
    if item.startswith('platform') and os.path.isdir(os.path.join(opengl_dir, item)):
        platform_dirs.append(os.path.join(opengl_dir, item))

for platform_dir in platform_dirs:
    for root, dirs, files in os.walk(platform_dir):
        for file in files:
            if file.endswith('.py') or file.endswith('.so') or file.endswith('.dll') or file.endswith('.dylib'):
                src_path = os.path.join(root, file)
                dst_path = os.path.relpath(src_path, opengl_dir)
                datas.append((src_path, 'OpenGL'))

a = Analysis(
    ['main.py'],
    pathex=['/data0/code/NagaAgent'],
    binaries=[],
    datas=datas,
    hiddenimports=[
        'nagaagent_core',
        'pyqt5',
        'simpleaudio',
        'pydub',
        'onnxruntime',
        'sounddevice',
        'py2neo',
        'pyautogui',
        'librosa',
        'pystray',
        'bilibili-api',
        'paho-mqtt',
        'docx',
        'python-docx',
        'fastmcp',
        'tensorboard',
        'expecttest',
        'jmcomic',
        'crawl4ai',
        'nagaagent_core.vendors.agents',
        'langchain_community',
        'playwright',
        'langchain_community.utilities',
        'fastmcp',
        'live2d',
        'dashscope',
        # OpenGL相关导入
        'OpenGL',
        'OpenGL.GL',
        'OpenGL.GLU',
        'OpenGL.GLUT',
        'OpenGL.EGL',
        'OpenGL.platform',
        'OpenGL.platform.egl',
        'OpenGL.platform.base_platform',
        'OpenGL.arrays',
        'OpenGL.arrays.arraydatatype',
        'OpenGL.arrays.numpymodule',
        'OpenGL.arrays.vbo',
        'OpenGL.raw',
        'OpenGL.raw.GL',
        'OpenGL.raw.GLU',
        'OpenGL.raw.GLUT',
        'OpenGL.raw.EGL',
        'OpenGL_accelerate',
    ],
    hookspath=['hooks'],
    hooksconfig={},
    runtime_hooks=['hooks/rthook-opengl.py'],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

# 添加 Tree 对象到分析结果
for tree in trees:
    a.datas += tree

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='NagaAgent',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False, # 不使用UPX，保证速度和兼容性
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None # 您可以指定一个图标路径, e.g., icon='ui/img/icon.ico'
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='main',
)