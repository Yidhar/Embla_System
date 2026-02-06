"""
PyInstaller hook for onnxruntime
确保ONNX Runtime相关模块被正确打包
"""

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_dynamic_libs

# 收集onnxruntime的所有子模块
hiddenimports = collect_submodules('onnxruntime')

# 收集数据文件
datas = collect_data_files('onnxruntime')

# 收集动态库（包括CUDA等加速库）
binaries = collect_dynamic_libs('onnxruntime')
