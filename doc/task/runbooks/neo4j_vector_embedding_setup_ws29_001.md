# Neo4j Vector + Embedding Setup (WS29-001)

文档状态：`active`  
文档层级：`L2-RUNBOOK`  
任务标识：`NGA-WS29-001`

## 1. 目标

在 `Embla_System` 中完成以下闭环：

1. 本机启动 Neo4j 5.x（支持向量索引）。
2. 配置 `grag`、`embedding` 与 `computer_control.model`（Vision 多模态）参数。
3. 通过后端 smoke 脚本验证：
   - Neo4j 连接可用；
   - 五元组可写入/可查询；
   - 向量索引状态可观测；
   - Embedding 通道参数已就绪。

## 2. Neo4j 启动（本机）

可任选一种方式。

### 2.1 Docker（推荐）

```bash
docker run -d \
  --name embla-neo4j \
  -p 7474:7474 \
  -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/<your_neo4j_password> \
  neo4j:5
```

### 2.2 Neo4j Desktop

1. 创建 5.x 数据库实例。
2. 记录 Bolt 地址（通常 `neo4j://127.0.0.1:7687`）。
3. 确认用户名/密码可登录。

## 3. 配置项更新

通过 `/settings` 页面或 `config.json` patch 更新以下字段。

### 3.1 `grag`（图谱 + 向量）

```json
{
  "grag": {
    "enabled": true,
    "auto_extract": true,
    "neo4j_uri": "neo4j://127.0.0.1:7687",
    "neo4j_user": "neo4j",
    "neo4j_password": "<your_neo4j_password>",
    "neo4j_database": "neo4j",
    "vector_index_enabled": true,
    "vector_index_name": "entity_embedding_index",
    "vector_query_top_k": 8,
    "vector_similarity_function": "cosine",
    "vector_upsert_on_write": true
  }
}
```

### 3.2 `embedding`（OpenAI-Compatible）

```json
{
  "embedding": {
    "api_base": "<openai_compatible_embedding_base>",
    "api_key": "<embedding_api_key>",
    "model": "text-embedding-v4",
    "dimensions": 1024,
    "encoding_format": "float",
    "max_input_tokens": 8192,
    "request_timeout_seconds": 30
  }
}
```

说明：

1. `embedding.api_base`、`embedding.api_key` 为空时，会回退到 `api.base_url`、`api.api_key`。
2. 建议将敏感值通过设置页写入，不在脚本或仓库中硬编码。

### 3.3 `computer_control`（Vision 多模态理解模型）

```json
{
  "computer_control": {
    "enabled": true,
    "model": "gemini-2.5-flash"
  }
}
```

说明：

1. `vision` Agent 的 `image_qa` 默认优先使用 `computer_control.model`。
2. 若该字段为空，会回退到 `api.model`。
3. 设置页字段路径：`Settings -> API & Model -> Multimodal Vision Model`。

## 4. 验收与排障

### 4.1 运行 smoke

```bash
.venv/bin/python scripts/run_ws29_neo4j_vector_smoke_ws29_001.py --strict
```

报告输出：

- `scratch/reports/ws29_neo4j_vector_smoke_ws29_001.json`

### 4.2 通过标准

`passed = true` 且以下检查为 `true`：

1. `grag_enabled`
2. `neo4j_configured`
3. `embedding_ready`
4. `neo4j_connected`
5. `smoke_write_ok`
6. `smoke_query_has_rows`

若 `vector_index_enabled=true`，还应满足 `vector_status_known=true`。

### 4.3 常见失败

1. `neo4j_connected=false`：Neo4j 未启动或认证错误。
2. `embedding_ready=false`：Embedding API 配置为空或不完整。
3. `vector_status_known=false`：索引探测失败，可先执行写入触发索引创建，再复测。
