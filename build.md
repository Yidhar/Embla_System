# Windows 打包说明

## 概述

当前发布主链已切换到 `Embla_core`（Next.js）+ Python 后端。  
旧 `frontend/`（Electron + Vue）已退役，不再参与构建链。

## 一键构建（推荐）

在 Windows 环境执行：

```bash
python scripts/build-win.py
```

常用参数：

- `--backend-only`：仅构建后端（默认行为）

## 构建流程

`scripts/build-win.py` 会自动执行：

1. 检查 Python / uv 环境
2. `uv sync --group build`
3. 使用 PyInstaller 构建后端

## 产物校验

后端构建完成后，检查以下关键文件：

- `dist/backend-dist/naga-backend/naga-backend.exe`

## 运行时验证

在一台全新 Windows 机器上安装并启动，预期：

- 应用可正常启动
- 后端服务可达：`http://127.0.0.1:8000/health`
- Agent 服务可达：`http://127.0.0.1:8001/health`
