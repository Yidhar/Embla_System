#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pytesseract 统一入口（上层建议 import nagaagent_core.vendors.pytesseract as pytesseract）"""

import pytesseract as _pytesseract  # 原始模块 #

globals().update({k: getattr(_pytesseract, k) for k in dir(_pytesseract)})  # 简单转发 #


