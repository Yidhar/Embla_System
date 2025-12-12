"""
Runtime hook for OpenGL
确保OpenGL在打包环境中正确初始化
"""

import os
import sys
import logging

# 设置OpenGL日志级别，减少噪音
logging.getLogger("OpenGL").setLevel(logging.ERROR)
logging.getLogger("OpenGL.acceleratesupport").setLevel(logging.WARNING)  # 改为WARNING，显示加速模块状态
logging.getLogger("OpenGL.plugins").setLevel(logging.ERROR)

def _setup_opengl_environment():
    """设置OpenGL环境变量和路径"""
    
    # 对于Linux系统，设置必要的库路径
    if sys.platform.startswith('linux'):
        # 添加常见的库路径
        lib_paths = [
            '/usr/lib/x86_64-linux-gnu',
            '/usr/lib',
            '/usr/local/lib',
        ]
        
        # 检查是否在PyInstaller环境中
        if getattr(sys, 'frozen', False):
            # 在PyInstaller环境中，添加_internal目录到库路径
            internal_path = os.path.join(sys._MEIPASS, '_internal')
            if os.path.exists(internal_path):
                lib_paths.append(internal_path)
        
        # 设置LD_LIBRARY_PATH环境变量
        current_ld_path = os.environ.get('LD_LIBRARY_PATH', '')
        new_paths = [p for p in lib_paths if os.path.exists(p) and p not in current_ld_path]
        
        if new_paths:
            if current_ld_path:
                new_ld_path = ':'.join(new_paths + [current_ld_path])
            else:
                new_ld_path = ':'.join(new_paths)
            os.environ['LD_LIBRARY_PATH'] = new_ld_path
    
    # 设置OpenGL相关环境变量
    os.environ['PYOPENGL_PLATFORM'] = os.environ.get('PYOPENGL_PLATFORM', '')
    
    # 尝试禁用EGL（如果导致问题）
    if 'OpenGL.platform.egl' in sys.modules:
        try:
            # 强制使用基础平台
            import OpenGL.platform
            OpenGL.platform.use(OpenGL.platform.base_platform.BasePlatform)
        except:
            pass

# 在模块导入时立即设置环境
_setup_opengl_environment()