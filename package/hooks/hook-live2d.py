"""
PyInstaller hook for live2d
确保Live2D相关模块被正确打包
"""

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_dynamic_libs

# 收集live2d的所有子模块
hiddenimports = collect_submodules('live2d')

# 收集数据文件
datas = collect_data_files('live2d')

# 收集动态库
binaries = collect_dynamic_libs('live2d')
