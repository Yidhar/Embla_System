# Game Guide 接入测试指南

本文用于测试以下两项能力：

1. `game_guide` MCP 服务已成功注册并可调用。
2. 攻略调用默认自动截图注入（无需用户上传图片）。

## 1. 测试前准备

- Python 3.11
- 安装依赖（推荐）：`uv sync`
- 若不使用 `uv`：`pip install -r requirements.txt`

说明：

- 若机器无图形桌面或无可用显示器，自动截图可能失败。
- 截图失败不会让服务崩溃，会在返回 `metadata.auto_screenshot_error` 中体现。

## 2. 配置检查

确认 `config.json` 中存在 `guide_engine` 配置段（可参考 `config.json.example`）。

关键项：

- `guide_engine.enabled`: `true`
- `guide_engine.auto_screenshot_on_guide`: `true`
- `guide_engine.screenshot_monitor_index`: `1`

## 3. 用例一：MCP 注册验证

执行：

```bash
uv run python -c "from mcpserver.mcp_registry import auto_register_mcp, get_registered_services; auto_register_mcp(); print(get_registered_services())"
```

预期：

- 输出列表中包含 `game_guide`。

## 4. 用例二：默认自动截图（核心）

执行：

```bash
uv run python - <<'PY'
import asyncio, json
from mcpserver.mcp_registry import auto_register_mcp, get_service_instance

auto_register_mcp()
agent = get_service_instance("game_guide")

async def main():
    payload = {
        "tool_name": "ask_guide",
        "game_id": "arknights",
        "query": "这关怎么打"
    }
    result = await agent.handle_handoff(payload)
    print(result)

asyncio.run(main())
PY
```

预期：

- 返回 JSON 的 `status` 为 `ok`。
- `metadata` 中包含以下之一：
  - `auto_screenshot`（截图成功）
  - `auto_screenshot_error`（截图失败但流程不中断）

## 5. 用例三：关闭自动截图

执行：

```bash
uv run python - <<'PY'
import asyncio, json
from mcpserver.mcp_registry import auto_register_mcp, get_service_instance

auto_register_mcp()
agent = get_service_instance("game_guide")

async def main():
    payload = {
        "tool_name": "ask_guide",
        "game_id": "arknights",
        "query": "这关怎么打",
        "auto_screenshot": False
    }
    result = await agent.handle_handoff(payload)
    print(result)

asyncio.run(main())
PY
```

预期：

- 返回 `status=ok`。
- `metadata` 不应包含 `auto_screenshot` 字段。

## 6. 用例四：伤害计算入口

执行：

```bash
uv run python - <<'PY'
import asyncio
from mcpserver.mcp_registry import auto_register_mcp, get_service_instance

auto_register_mcp()
agent = get_service_instance("game_guide")

async def main():
    payload = {
        "tool_name": "calculate_damage",
        "game_id": "arknights",
        "query": "缪尔赛思S3M3打800防DPS"
    }
    result = await agent.handle_handoff(payload)
    print(result)

asyncio.run(main())
PY
```

预期：

- 返回 `status=ok`。
- 返回字段中包含 `query_mode`，且通常为 `calculation`。

## 7. 回归检查点

- 天气/时间与应用启动 MCP 服务仍可注册并调用。
- `/chat/stream` 正常返回，不因新增 `game_guide` 规则报错。
- `config.json` 热更新不影响 `guide_engine` 字段解析。
