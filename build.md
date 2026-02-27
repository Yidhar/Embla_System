# Windows 打包说明

## 概述

当前发布主链已切换到 `Embla_core`（Next.js）+ Python 后端。  
`frontend/`（Electron + Vue）已归档为 `archived` 兼容路径，不再作为默认发布链。

## 一键构建（推荐）

在 Windows 环境执行：

```bash
python scripts/build-win.py
```

常用参数：

- `--backend-only`：仅构建后端（默认主链）
- `--legacy-electron`：启用 archived Electron 打包（`frontend/`）
- `--debug`：archived Electron 安装后启动时弹出后端日志终端

## 构建流程

`scripts/build-win.py` 会自动执行：

1. 检查 Python / uv 环境（`--legacy-electron` 时额外检查 Node.js / npm；该路径为 archived）
2. `uv sync --group build`
3. 使用 PyInstaller 构建后端
4. 仅在 `--legacy-electron` 模式下，使用 electron-builder 生成 Windows 安装包（archived 路径）

## 产物校验

后端构建完成后，检查以下关键文件：

- `dist/backend-dist/naga-backend/naga-backend.exe`

若启用了 `--legacy-electron`，安装包输出目录为：`frontend/release/`

## 运行时验证

在一台全新 Windows 机器上安装并启动，预期：

- 应用可正常启动
- 后端服务可达：`http://127.0.0.1:8000/health`
- Agent 服务可达：`http://127.0.0.1:8001/health`
