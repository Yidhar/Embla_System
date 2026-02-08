#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""httpx 统一出口（为上层项目提供稳定导入路径）"""

import httpx as _httpx  # 内部别名 #

# 直接暴露模块对象，便于 mypy/类型提示  #
__all__ = [
    "__version__",
    "Client",
    "AsyncClient",
    "Limits",
    "Timeout",
    "HTTPStatusError",
    "Response",
    "Request",
    "Headers",
]

__version__ = getattr(_httpx, "__version__", "")  # 版本 #

Client = _httpx.Client  #
AsyncClient = _httpx.AsyncClient  #
Limits = _httpx.Limits  #
Timeout = _httpx.Timeout  #
HTTPStatusError = _httpx.HTTPStatusError  #
Response = _httpx.Response  #
Request = _httpx.Request  #
Headers = _httpx.Headers  #

# 附带整个模块，支持命名空间访问（如 httpx.get）  #
globals().update({k: getattr(_httpx, k) for k in dir(_httpx) if not k.startswith("_")})  #


