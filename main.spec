# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import copy_metadata, collect_all
import os
import importlib.metadata
import py2neo
import OpenGL
import concurrent.futures
from pathlib import Path

# =============================================================================
# 1. 定义手动列表 (合并原有的 additional_packages 和 hiddenimports)
# =============================================================================

# 原有的额外包列表
manual_additional_packages = [
    # 原有依赖
    'PIL', 'redis', 'langchain_community', 'pytesseract', 'opentelemetry', 'langchain_core',
    'webbrowser', 'importlib_metadata', 'zipp', 'cloudpickle', 'prometheus_client', 'wsgiref',
    'starlette', 'uvicorn', 'anyio', 'pydantic', 'pydantic_core', 'typing_extensions',
    'timeit', 'uuid', 'email', 'xml', 'click', 'h11', 'sse_starlette', 'key_value',
    # FastMCP 核心依赖链
    'beartype', 'mcp', 'cyclopts', 'authlib', 'fastmcp',
    # MCP SDK 依赖
    'httpx_sse', 'jsonschema', 'pydantic_settings', 'typing_inspection', 'python_multipart',
    'jwt', 'cryptography',
    # FastMCP 其他依赖
    'rich', 'websockets', 'pydocket', 'pyperclip', 'platformdirs', 'dotenv',
    'openapi_pydantic', 'jsonschema_path', 'exceptiongroup',
    # py-key-value-aio[memory] 依赖
    'cachetools', 'py_key_value_shared',
    # py-key-value-aio[disk] 依赖
    'diskcache', 'pathvalidate',
]

# 原 Analysis 中的 hiddenimports 列表
manual_hidden_imports = [
    'nagaagent_core',
    'nagaagent_core.stable',
    'nagaagent_core.stable.mcp',
    'nagaagent_core.vendors',
    'nagaagent_core.vendors.agents',
    'nagaagent_core.vendors.charset_normalizer',
    'nagaagent_core.vendors.json5',
    'nagaagent_core.core',
    'nagaagent_core.api',
    'PyQt5',
    'simpleaudio',
    'pydub',
    'onnxruntime',
    'sounddevice',
    'py2neo',
    'pyautogui',
    'librosa',
    'pystray',
    'bilibili_api',
    'paho_mqtt',
    'nagaagent_core.vendors.paho_mqtt',
    'docx',
    'python_docx',
    'fastmcp',
    'tensorboard',
    'expecttest',
    'jmcomic',
    'crawl4ai',
    'langchain_community',
    'langchain_community.utilities',
    'langchain_community.utilities.searx',
    'playwright',
    'fastmcp',
    'live2d',
    'dashscope',
    'httpx',
    'redis',
    'redis.client',
    'redis.connection',
    'PIL',
    'PIL.Image',
    'PIL.ImageGrab',
    'PIL.ImageDraw',
    'PIL.ImageFont',
    'PIL.ImageFilter',
    'PIL.ImageEnhance',
    'PIL.ImageOps',
    'PIL.ImageColor',
    'PIL.ImageChops',
    'PIL.ImageStat',
    'PIL.PngImagePlugin',
    'PIL.JpegImagePlugin',
    'PIL.BmpImagePlugin',
    'PIL.GifImagePlugin',
    'PIL.TiffImagePlugin',
    'webbrowser',
    'charset_normalizer',
    'cv2',
    'numpy',
    'base64',
    'json5',
    'pytesseract',
    'pytesseract.pytesseract',
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
    # beartype 关键子模块 (动态导入)
    'beartype',
    'beartype.claw',
    'beartype.claw._ast',
    'beartype.claw._ast._clawaststar',
    'beartype.claw._clawmain',
    'beartype.cave',
    'beartype.bite',
    'beartype.door',
    'beartype.peps',
    'beartype.plug',
    'beartype.roar',
    'beartype.typing',
    'beartype.vale',
    'beartype._cave',
    'beartype._check',
    # MCP 关键子模块
    'mcp',
    'mcp.server',
    'mcp.client',
    'mcp.types',
    'mcp.server.session',
    'mcp.client.session',
    # cyclopts
    'cyclopts',
    # authlib
    'authlib',
    'authlib.oauth2',
    # key_value (py-key-value-aio) 所有子模块
    'key_value',
    'key_value.aio',
    'key_value.aio.stores',
    'key_value.aio.stores.base',
    'key_value.aio.stores.disk',
    'key_value.aio.stores.disk.store',
    'key_value.aio.stores.memory',
    'key_value.aio.stores.keyring',
    'key_value.aio.stores.simple',
    'key_value.aio.stores.null',
    'key_value.shared',
    # diskcache (DiskStore 的核心依赖)
    'diskcache',
    'diskcache.core',
    'diskcache.fanout',
    'diskcache.persistent',
    'diskcache.recipes',
    # cachetools (MemoryStore 的核心依赖)
    'cachetools',
]

extra_hiddenimports = [] # 用户可能自定义的保留变量

# =============================================================================
# 2. 自动发现项目中的所有库
# =============================================================================

discovered_packages = set()

# 黑名单：不收集的库（避免自身递归或不必要的大型构建工具）
exclude_packages = {
    'pyinstaller', 'pyinstaller-hooks-contrib', 'altgraph', 'macholib', 'pip', 
    'setuptools', 'wheel', 'uv'
}

"""
print("正在自动查找项目中的所有库...")
try:
    for dist in importlib.metadata.distributions():
        name = dist.metadata.get('Name')
        if not name:
            continue
            
        if name.lower() in exclude_packages:
            continue
            
        # 添加包名
        discovered_packages.add(name)
        
        # 尝试读取 top_level.txt 获取实际导入名
        try:
            top_level = dist.read_text('top_level.txt')
            if top_level:
                for pkg in top_level.split():
                    if pkg and pkg != name:
                        discovered_packages.add(pkg)
        except Exception:
            pass
            
except Exception as e:
    print(f"警告: 自动发现包时出错: {e}")
"""
print(f"共发现 {len(discovered_packages)} 个潜在包/库。")

# =============================================================================
# 3. 合并列表并执行 collect_all
# =============================================================================

# 合并所有列表 (去重)
target_libraries = set(manual_additional_packages + manual_hidden_imports + list(discovered_packages) + extra_hiddenimports)

final_datas = []
final_binaries = []
final_hiddenimports = []

print("正在对目标库执行 collect_all 和收集 hiddenimports (使用多线程)...")

def process_package(package):
    if not package:
        return [], [], []
    try:
        # 尝试收集
        d, b, h = collect_all(package)
        return d, b, h
    except Exception:
        # 失败时返回空，外层会把 package 加入 hiddenimports
        return [], [], []

# 使用线程池并发处理
with concurrent.futures.ThreadPoolExecutor(max_workers=os.cpu_count() * 2) as executor:
    # 提交所有任务
    future_to_package = {executor.submit(process_package, pkg): pkg for pkg in target_libraries}
    
    for future in concurrent.futures.as_completed(future_to_package):
        pkg = future_to_package[future]
        try:
            tmp_datas, tmp_binaries, tmp_hiddenimports = future.result()
            final_datas.extend(tmp_datas)
            final_binaries.extend(tmp_binaries)
            final_hiddenimports.extend(tmp_hiddenimports)
        except Exception:
            pass
        finally:
             # 无论成功失败，该包本身也应作为 hiddenimport 确保被分析
            final_hiddenimports.append(pkg)

# 添加合并后的 hiddenimports 结果
# 重要：除了 collect_all 找到的，原始列表中的项也必须保留在 hiddenimports 中，
# 因为有些项是具体的模块路径 'PIL.Image'，collect_all('PIL.Image') 可能失败或不做事。
final_hiddenimports.extend(list(target_libraries))

# 去重

final_hiddenimports = list(set(final_hiddenimports))

print(f"=========================================")
print(f"总计收集到 {len(final_hiddenimports)} 个 hiddenimports")
print(f"=========================================")

# =============================================================================
# 4. 其他特定资源的收集 (copy_metadata 等)
# =============================================================================

# 收集特定包的 metadata (保留原有逻辑)
metadata_packages = ['fastmcp']
for package in metadata_packages:
    try:
        final_datas += copy_metadata(package)
    except Exception as e:
        print(f"警告: 无法复制元数据 {package}: {e}")

# 收集所有需要的资源文件
final_datas += [
    ('config.json.example', '.'),
    ('config.json', '.'),
    ('LICENSE', '.'),
    ('pyproject.toml', '.'),
    ('README.md', '.'),
    ('requirements.txt', '.'),
]

# 收集 Tree 对象
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

# 添加 py2neo VERSION
try:
    py2neo_path = py2neo.__file__
    py2neo_dir = os.path.dirname(py2neo_path)
    version_file = os.path.join(py2neo_dir, 'VERSION')
    if os.path.exists(version_file):
        final_datas.append((version_file, 'py2neo'))
except Exception as e:
    print(f"警告: 处理 py2neo 失败: {e}")

# 添加图标
icon_files = [
    'ui/img/icons/naga_chat.png',
    'ui/img/icons/love_adventure.png',
    'ui/img/icons/personality_game.png',
    'ui/img/icons/mind_map.png'
]
for icon_file in icon_files:
    if os.path.exists(icon_file):
        final_datas.append((icon_file, 'ui/img/icons'))

# 添加样式文件
final_datas.append(('ui/styles/progress.txt', 'ui/styles'))

# 收集 agent-manifest.json
for manifest_path in Path('mcpserver').rglob('agent-manifest.json'):
    final_datas.append((str(manifest_path), str(manifest_path.parent)))

# OpenGL 处理
op_datas = []
try:
    opengl_path = OpenGL.__file__
    opengl_dir = os.path.dirname(opengl_path)
    
    platform_dirs = []
    for item in os.listdir(opengl_dir):
        if item.startswith('platform') and os.path.isdir(os.path.join(opengl_dir, item)):
            platform_dirs.append(os.path.join(opengl_dir, item))
            
    def collect_opengl_platform(platform_dir):
        results = []
        for root, dirs, files in os.walk(platform_dir):
            for file in files:
                if file.endswith('.py') or file.endswith('.so') or file.endswith('.dll') or file.endswith('.dylib'):
                    src_path = os.path.join(root, file)
                    results.append((src_path, os.path.join('OpenGL', os.path.dirname(os.path.relpath(src_path, opengl_dir)))))
        return results

    if platform_dirs:
        with concurrent.futures.ThreadPoolExecutor(max_workers= min(len(platform_dirs), os.cpu_count() or 4)) as executor:
            for res in executor.map(collect_opengl_platform, platform_dirs):
                final_datas.extend(res)
except Exception as e:
    print(f"警告: 手动收集 OpenGL 失败: {e}")

# =============================================================================
# 5. Analysis
# =============================================================================

a = Analysis(
    ['main.py'],
    pathex=['/data0/code/NagaAgent'],
    binaries=final_binaries,
    datas=final_datas,
    hiddenimports=final_hiddenimports,
    hookspath=['hooks'],
    hooksconfig={},
    runtime_hooks=['hooks/rthook-opengl.py'],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

# 添加 Tree 对象
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
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None
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