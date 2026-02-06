#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PyQt 统一导入口（上层只需 from nagaagent_core.qt import QtCore, QtGui, QtWidgets）"""

# 对中文友好：统一从此处导入，避免直接依赖第三方包名  #
from .vendors.PyQt5 import QtCore, QtGui, QtWidgets  # 统一出口 #

__all__ = [
    "QtCore",
    "QtGui",
    "QtWidgets",
]


