#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pyautogui 统一入口（上层建议 import nagaagent_core.vendors.pyautogui as pyautogui）"""

import pyautogui as _pyautogui  # 原始模块 #

globals().update({k: getattr(_pyautogui, k) for k in dir(_pyautogui)})  # 简单转发 #


