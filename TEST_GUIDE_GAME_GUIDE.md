# Game Guide 从零配置与测试指南

本文面向测试同学，目标是从零开始完成环境准备、配置、验证，并覆盖核心能力：

1. `game_guide` MCP 服务可注册并调用。
2. 攻略调用默认自动截图注入（无需用户上传图片）。
3. `guide_engine` 配置可生效（包含默认模型、Neo4j 配置与开关项）。

## 1. 测试环境要求

- Python 3.11
- 推荐使用 `uv`（已在项目中使用）
- 若要验证自动截图成功，机器需有图形桌面和可用显示器

说明：

- 无桌面环境（如纯 SSH 服务器）时，自动截图可能失败。
- 截图失败不会导致服务崩溃，返回里会出现 `metadata.auto_screenshot_error`。
- 测试环境可用 `TEST_PIC_PATH` 指定本地图片，触发“以图代截屏”模式。

## 2. 从零开始：安装与初始化

### 2.1 安装依赖

推荐：

```bash
uv sync
```

备选：

```bash
pip install -r requirements.txt
```

### 2.2 准备配置文件

如果当前目录没有 `config.json`，先复制：

```bash
cp config.json.example config.json
```

说明：

- `config.json.example` 已是 UTF-8。
- 配置文件支持注释（按 JSON5 解析），可保留 `//` 注释。

### 2.3 最小必填配置（建议）

请至少确认以下配置：

```jsonc
{
  "api": {
    "base_url": "你的模型网关地址",
    "api_key": "你的模型密钥",
    "model": "你的模型名"
  },
  "guide_engine": {
    "enabled": true,
    "chroma_persist_dir": "./data/chroma",
    "embedding_api_base_url": "https://你的网关/v1",
    "embedding_api_key": "你的Embedding密钥",
    "embedding_api_model": "text-embedding-3-small",
    "vision_api_base_url": "https://你的视觉网关/v1",
    "vision_api_key": "你的视觉模型密钥",
    "vision_api_model": "qwen-vl-plus",
    "prompt_dir": "./guide_engine/game_prompts",
    "neo4j_uri": "bolt://127.0.0.1:7687",
    "neo4j_user": "neo4j",
    "neo4j_password": "your_password",
    "screenshot_monitor_index": 1,
    "auto_screenshot_on_guide": true
  }
}
```

字段说明：

- 向量嵌入统一走 OpenAI 兼容 API，不再使用本地 `sentence-transformers`。
- `embedding_api_base_url` 与 `embedding_api_key` 必须可用。
- `embedding_api_model` 建议填写专用 embedding 模型。
- 截图识图支持单独配置视觉模型：`vision_api_base_url`、`vision_api_key`、`vision_api_model`。
- 若视觉配置留空，会回退到 `api.base_url`、`api.api_key`、`api.model`。
- `neo4j_uri` 建议优先 `bolt://127.0.0.1:7687`。

### 2.4 使用 OpenAI 兼容外部向量 API（必需）

当前版本已默认使用外部向量服务，示例：

```jsonc
"guide_engine": {
  "embedding_api_base_url": "https://你的网关/v1",
  "embedding_api_key": "你的Embedding密钥",
  "embedding_api_model": "text-embedding-3-small"
}
```

说明：

- 该接口需兼容 OpenAI SDK `embeddings.create`。
- 若 `embedding_api_base_url` 或 `embedding_api_key` 为空，会回退到 `api.base_url`、`api.api_key`。
- `embedding_api_model` 建议单独配置，不要复用聊天模型名。

### 2.5 测试图片替代截图（可选）

当设置环境变量 `TEST_PIC_PATH` 时，`ask_guide` 自动截图流程不会抓屏，而是读取该路径图片并注入模型。

Linux/macOS：

```bash
export TEST_PIC_PATH="/绝对路径/测试图.png"
```

Windows PowerShell：

```powershell
$env:TEST_PIC_PATH="C:\\path\\to\\test.png"
```

预期：

- 返回 `metadata.auto_screenshot.source=env:TEST_PIC_PATH`。
- 若路径不存在或格式不支持，会返回 `metadata.auto_screenshot_error`。

## 3. 依赖与服务：Neo4j 与 Embedding API

### 3.1 Neo4j（建议启动）

可用 Docker 快速启动：

```bash
docker run -d --name neo4j \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/your_password \
  neo4j:5
```

若不启动 Neo4j：

- 服务仍可调用，但图谱相关检索会降级或为空。

自动导入说明：

- 系统在检测到指定游戏图谱为空时，会自动尝试导入一次基础数据。
- 默认会在以下路径查找种子数据文件：
  - `data/`
  - `../guide_engine_backend/backend/app/data/`
- 明日方舟使用 `arknights_cn_operators.json`，舰C使用 `kantai-collection_start2.json`。

### 3.2 Embedding API（必需）

请确认外部 Embedding API 满足 OpenAI SDK `embeddings.create` 接口。

## 4. 快速自检（语法级）

```bash
uv run --no-sync python -m compileall system/config.py guide_engine mcpserver/agent_game_guide
```

预期：无报错。

## 5. 功能测试用例

### 用例一：MCP 注册验证

```bash
uv run python -c "from mcpserver.mcp_registry import auto_register_mcp, get_registered_services; auto_register_mcp(); print(get_registered_services())"
```

预期：输出列表包含 `game_guide`。

### 用例二：默认自动截图（核心）

```bash
uv run python - <<'PY'
import asyncio
from mcpserver.mcp_registry import auto_register_mcp, get_service_instance

auto_register_mcp()
agent = get_service_instance("game_guide")

async def main() -> None:
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
- `metadata` 包含以下之一：
  - `auto_screenshot`（截图成功或使用 `TEST_PIC_PATH` 成功）
  - `auto_screenshot_error`（截图失败但流程不中断）

### 用例三：关闭自动截图

```bash
uv run python - <<'PY'
import asyncio
from mcpserver.mcp_registry import auto_register_mcp, get_service_instance

auto_register_mcp()
agent = get_service_instance("game_guide")

async def main() -> None:
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
- `metadata` 不包含 `auto_screenshot` 字段。

### 用例四：伤害计算入口

```bash
uv run python - <<'PY'
import asyncio
from mcpserver.mcp_registry import auto_register_mcp, get_service_instance

auto_register_mcp()
agent = get_service_instance("game_guide")

async def main() -> None:
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
- 返回字段中有 `query_mode`，通常为 `calculation`。

### 用例五：OpenAI 兼容向量 API 验证（可选）

前置：已正确配置 `embedding_api_base_url`、`embedding_api_key`、`embedding_api_model`。

```bash
uv run python - <<'PY'
import asyncio
from guide_engine.chroma_service import ChromaService

async def main() -> None:
    service = ChromaService()
    vec = await service._embed_query("明日方舟 7-18 怎么打")
    print(type(vec), len(vec), round(float(sum(x * x for x in vec)), 4))

asyncio.run(main())
PY
```

预期：

- 输出类型为 `list`，长度大于 0。
- 最后一项（向量范数平方）接近 `1.0`（系统会做归一化）。

## 6. 结果判定标准

- P0 通过：`game_guide` 可注册 + `ask_guide` 返回 `status=ok`。
- P1 通过：默认自动截图路径触发（成功或错误字段二选一都算路径有效）。
- P2 通过：`calculate_damage` 可走通且返回 `query_mode`。

## 7. 常见问题与排查

- `ModuleNotFoundError`：依赖未安装，先执行 `uv sync`。
- `chromadb 未安装`：确认已安装 `chromadb`。
- embedding 调用失败：检查 `embedding_api_base_url`、`embedding_api_key`、`embedding_api_model` 是否正确。
- Neo4j 连接失败：检查 `guide_engine.neo4j_uri/user/password` 与端口 `7687`。
- 自动截图失败：检查是否有桌面会话、显示器索引是否正确（`screenshot_monitor_index`）。

## 8. 回归检查点

- 天气/时间与应用启动 MCP 服务仍可注册并调用。
- `/chat/stream` 正常返回，不因新增 `game_guide` 规则报错。
- `config.json` 热更新不影响 `guide_engine` 字段解析。
