# Windows 打包说明

## 概述

当前打包流程仅构建 NagaAgent 后端与 Electron 前端，不再依赖外置或内嵌的 Node 运行时代理组件。

## 一键构建（推荐）

在 Windows 环境执行：

```bash
python scripts/build-win.py
```

常用参数：

- `--backend-only`：仅构建后端，不打包 Electron
- `--debug`：安装后启动时弹出后端日志终端

## 构建流程

`scripts/build-win.py` 会自动执行：

1. 检查 Python / uv / Node.js / npm 环境
2. `uv sync --group build`
3. 使用 PyInstaller 构建后端
4. 使用 electron-builder 生成 Windows 安装包

## 产物校验

安装包构建完成后，检查以下关键文件：

- `frontend/backend-dist/naga-backend/naga-backend.exe`

Electron 安装包输出目录：`frontend/release/`

## 运行时验证

在一台全新 Windows 机器上安装并启动，预期：

- 应用可正常启动
- 后端服务可达：`http://127.0.0.1:8000/health`
- Agent 服务可达：`http://127.0.0.1:8001/health`
