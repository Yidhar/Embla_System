"""
PyInstaller hook for PyQt5
确保PyQt5相关模块和资源被正确打包
"""

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# 收集PyQt5的所有子模块
hiddenimports = collect_submodules('PyQt5')

# 确保包含关键模块
hiddenimports.extend([
    'PyQt5.QtCore',
    'PyQt5.QtGui',
    'PyQt5.QtWidgets',
    'PyQt5.QtWebEngineWidgets',
    'PyQt5.QtWebChannel',
    'PyQt5.QtNetwork',
    'PyQt5.QtPrintSupport',
    'PyQt5.sip',
])

# 收集PyQt5数据文件
datas = collect_data_files('PyQt5')
