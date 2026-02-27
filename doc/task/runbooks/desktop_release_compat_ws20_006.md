# WS20-006 桌面端发布兼容性验证 Runbook

文档状态：`archived_legacy_runbook`  
归档日期：`2026-02-27`  
替代入口：`python scripts/embla_core_release_compat_gate.py --strict`

## 目标
在发布前验证 Electron 桌面包在不同配置与网络场景下可稳定运行，并形成可审计报告。

## 自动化入口
1. 生成兼容报告（严格模式）
```powershell
.\.venv\Scripts\python.exe scripts/desktop_release_compat_ws20_006.py --strict
```
2. 产物路径
- `doc/task/reports/ws20_006_desktop_compat_report.json`

## 自动化检查项
- `ws20-006-dist-scripts`：`dist/dist:win/dist:mac/dist:linux` 脚本完整
- `ws20-006-electron-runtime-deps`：`electron/electron-builder/electron-updater` 依赖完整
- `ws20-006-builder-targets`：`electron-builder.yml` 含 Win/Mac/Linux 目标与 backend 资源映射
- `ws20-006-network-offline-fallback`：更新检查网络失败不阻断启动
- `ws20-006-screen-capture-permission-fallback`：录屏权限拒绝时可恢复
- `ws20-006-build-env-thresholds`：Windows 打包环境门槛校验（Python/Node）

## 场景矩阵（发布门禁）
1. `cfg-online-default`（配置）
- 使用默认配置启动，确认更新检查不影响主流程
2. `cfg-api-base-url-override`（配置）
- 设置 `VITE_API_BASE_URL` 指向指定后端，确认聊天链路可用
3. `net-offline-startup`（网络）
- 断网启动，确认应用可进入主界面且无阻塞
4. `net-proxy-restricted`（网络）
- 受限网络/代理环境启动，确认本地能力可用
5. `permission-screen-capture-denied`（权限）
- macOS 拒绝录屏权限，确认提示与设置跳转可用

## 手工验证建议
1. Windows:
```powershell
cd frontend
npm run dist:win
```
2. macOS:
```bash
cd frontend
npm run dist:mac
```
3. Linux:
```bash
cd frontend
npm run dist:linux
```

## 出场条件（M5）
- 自动化报告 `all_passed=true`
- 场景矩阵 5/5 完成并记录结果
- 不存在阻断级兼容问题（安装失败、启动阻塞、核心链路不可用）
