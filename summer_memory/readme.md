# `summer_memory`

`summer_memory` 是 Embla 当前仍在使用的 Shell L2 会话级五元组记忆实现。
它负责：

- 从 Shell 轮次消息抽取五元组
- 将五元组写入 `logs/knowledge_graph/quintuples.json`
- 在 Neo4j 可用时同步写入图数据库与向量索引
- 基于最近上下文提取关键词并查询五元组图谱
- 生成 `logs/knowledge_graph/graph.html` 供人工查看

## 当前有效文件

```text
summer_memory/
├── main.py                  # 本地手动调试入口
├── memory_manager.py        # 运行时 GRAG 管理器
├── task_manager.py          # 异步抽取任务队列
├── quintuple_extractor.py   # 五元组抽取
├── quintuple_graph.py       # 文件 + Neo4j 双写与查询
├── quintuple_rag_query.py   # 关键词提取与图谱查询
├── quintuple_visualize.py   # 从 quintuples.json 生成 graph.html
└── memory_client.py         # 远程调用封装
```

已经退役：

- 旧三元组链路
- 旧的解耦说明文档

## 运行时数据目录

运行时产物统一写到 `logs/knowledge_graph/`：

- `logs/knowledge_graph/quintuples.json`
- `logs/knowledge_graph/graph.html`

`summer_memory/` 目录下不再维护这些产物副本。

## 配置

配置来自项目根目录的 `config.json`。

### LLM

```json
{
  "api": {
    "api_key": "sk-xxx",
    "base_url": "https://api.deepseek.com/v1",
    "model": "deepseek-chat"
  }
}
```

### GRAG / Neo4j

```json
{
  "grag": {
    "enabled": true,
    "auto_extract": true,
    "context_length": 5,
    "extraction_timeout": 12,
    "extraction_retries": 2,
    "neo4j_uri": "neo4j://127.0.0.1:7687",
    "neo4j_user": "neo4j",
    "neo4j_password": "your_password",
    "neo4j_database": "neo4j"
  }
}
```

关键参数：

- `grag.enabled`：总开关
- `grag.auto_extract`：写入轮次后是否自动触发抽取
- `grag.context_length`：用于问答关键词提取的最近上下文条数
- `grag.extraction_timeout`：单轮抽取的总超时预算
- `grag.extraction_retries`：抽取失败后的重试次数

## 数据流

当前 live 路径如下：

```text
Shell 轮次消息
  → memory_manager.add_shell_round_memory(...)
  → task_manager.add_task(...)
  → quintuple_extractor.py
  → quintuple_graph.py
  → logs/knowledge_graph/quintuples.json
  → (可选) Neo4j / 向量索引
```

问答路径如下：

```text
用户问题
  → quintuple_rag_query.py
  → 提取关键词
  → quintuple_graph.query_graph_by_keywords(...)
  → 返回图谱命中结果
```

可视化路径如下：

```text
logs/knowledge_graph/quintuples.json
  → quintuple_visualize.py
  → logs/knowledge_graph/graph.html
```

## 手动调试

从仓库根目录运行：

```bash
.venv/bin/python -m summer_memory.main
```

这个入口仅用于本地调试：

- 可手动输入文本或从文件读取
- 会尝试启动本目录下的 Neo4j Docker Compose
- 成功后打开 `logs/knowledge_graph/graph.html`
- 支持在终端继续做图谱问答

## 直接调用

### 批量写入文本

```python
from summer_memory.main import batch_add_texts

rows = ["李雷在操场上打篮球。", "韩梅梅喜欢读书。"]
ok = batch_add_texts(rows)
```

### 使用记忆管理器

```python
from summer_memory.memory_manager import memory_manager

await memory_manager.add_conversation_memory(
    "用户: 你好，我想了解人工智能",
    "Embla: 人工智能是一个快速发展的技术领域。"
)

result = await memory_manager.query_memory("什么是人工智能？")
```

### 生成图谱 HTML

```python
from summer_memory.quintuple_visualize import visualize_quintuples

visualize_quintuples(auto_open=False)
```

## 说明

- `summer_memory.main` 是调试入口，不是主系统启动路径
- 当前 canonical 口径是五元组，不再维护三元组运行链路
- prompt 资产已统一迁到 `system/prompts/memory/`
