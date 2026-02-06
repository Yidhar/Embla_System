#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
API服务器相关模块
包含Flask、FastAPI、Gevent、Uvicorn等API服务器功能
"""

# 重新导出API服务器相关依赖的功能
import flask  # Flask模块 #
import gevent  # Gevent模块 #
import uvicorn  # Uvicorn模块 #

# FastAPI核心与常用对象 #
from fastapi import (
    FastAPI,
    HTTPException,
    BackgroundTasks,
    Request,
    UploadFile,
    File,
    Form,
    WebSocket,
    WebSocketDisconnect,
)  # FastAPI核心 #
from fastapi.middleware.cors import CORSMiddleware  # CORS中间件 #
from fastapi.staticfiles import StaticFiles  # 静态文件服务 #
from fastapi.responses import (
    StreamingResponse,
    JSONResponse,
    HTMLResponse,
)  # 常用响应 #

# Flask常用对象 #
from flask import (
    Flask,
    request,
    jsonify,
    send_file,
)  # Flask常用 #

__all__ = [
    # 模块
    "flask",
    "gevent",
    "uvicorn",
    # FastAPI核心
    "FastAPI",
    "HTTPException",
    "BackgroundTasks",
    "Request",
    "UploadFile",
    "File",
    "Form",
    "WebSocket",
    "WebSocketDisconnect",
    "CORSMiddleware",
    "StaticFiles",
    "StreamingResponse",
    "JSONResponse",
    "HTMLResponse",
    # Flask常用
    "Flask",
    "request",
    "jsonify",
    "send_file",
]
