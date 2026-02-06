"""
Runtime hook for OpenGL
确保OpenGL在打包环境中正确初始化
"""

import os
import sys
import logging

# 设置OpenGL日志级别，减少噪音
logging.getLogger("OpenGL").setLevel(logging.ERROR)
logging.getLogger("OpenGL.acceleratesupport").setLevel(logging.WARNING)
logging.getLogger("OpenGL.plugins").setLevel(logging.ERROR)


def _setup_opengl_environment():
    """设置OpenGL环境变量和路径"""

    # 检查是否在PyInstaller环境中
    if getattr(sys, 'frozen', False):
        # 在PyInstaller环境中
        bundle_dir = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))

        # 对于Linux系统，设置必要的库路径
        if sys.platform.startswith('linux'):
            lib_paths = [
                '/usr/lib/x86_64-linux-gnu',
                '/usr/lib',
                '/usr/local/lib',
                bundle_dir,
            ]

            # 设置LD_LIBRARY_PATH环境变量
            current_ld_path = os.environ.get('LD_LIBRARY_PATH', '')
            new_paths = [p for p in lib_paths if os.path.exists(p) and p not in current_ld_path]

            if new_paths:
                if current_ld_path:
                    new_ld_path = ':'.join(new_paths + [current_ld_path])
                else:
                    new_ld_path = ':'.join(new_paths)
                os.environ['LD_LIBRARY_PATH'] = new_ld_path

        # 对于macOS系统
        elif sys.platform == 'darwin':
            # 确保使用正确的OpenGL框架
            os.environ.setdefault('PYOPENGL_PLATFORM', '')

        # 对于Windows系统
        elif sys.platform == 'win32':
            # 添加bundle目录到PATH
            current_path = os.environ.get('PATH', '')
            if bundle_dir not in current_path:
                os.environ['PATH'] = bundle_dir + os.pathsep + current_path

    # 设置OpenGL相关环境变量
    os.environ.setdefault('PYOPENGL_PLATFORM', '')


# 在模块导入时立即设置环境
_setup_opengl_environment()
