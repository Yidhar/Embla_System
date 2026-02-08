#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PyQt5 命名空间转发（保持 from ... import 路径兼容）"""

from importlib import import_module  # 导入 #

# 动态转发常用子模块 #
for _sub in ("QtWidgets", "QtCore", "QtGui"):
    globals()[_sub] = import_module(f"PyQt5.{_sub}")

__all__ = ["QtWidgets", "QtCore", "QtGui"]  # 导出 #


