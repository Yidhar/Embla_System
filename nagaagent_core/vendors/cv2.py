#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OpenCV 统一入口（上层建议 import nagaagent_core.vendors.cv2 as cv2）"""

import cv2 as _cv2  # 原始模块 #

# 将原始模块导出为本模块的公开接口 #
globals().update({k: getattr(_cv2, k) for k in dir(_cv2)})  # 简单转发 #


