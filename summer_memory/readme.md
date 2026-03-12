# 🧠 中文五元组知识图谱构建与可视化系统

本项目通过接入 DeepSeek API 实现中文文本的五元组抽取，并借助 Neo4j 构建实体关系图谱，同时使用 PyVis 实现知识图谱的可视化展示与交互式查询。

**新增功能**: 五元组提取任务管理器，支持并发处理和任务管理。

---

## 📦 项目结构

```
.
├── main.py                 # 主程序入口，负责流程调度、用户交互
├── quintuple_extractor.py  # 使用 DeepSeek API 进行五元组抽取
├── quintuple_graph.py      # 操作 Neo4j，存储与查询五元组
├── quintuple_visualize_v2.py  # 使用 PyVis 生成 graph.html 知识图谱可视化页面（解耦版本）
├── quintuple_rag_query.py  # 使用 DeepSeek 提取关键词并在图谱中检索答案
├── task_manager.py         # 🆕 五元组提取任务管理器，支持并发处理
├── memory_manager.py       # 🆕 记忆管理器，集成任务管理器
├── test_task_manager.py    # 🆕 任务管理器测试脚本
├── quintuples.json         # 持久化的五元组缓存文件
├── graph.html              # 可视化结果文件，自动生成
└── README.md               # 项目说明文档
```

---

## 🚀 使用说明

### 1. 安装依赖

```bash
pip install py2neo pyvis requests
```

### 2. 安装Neo4j数据库

**选项A：使用Neo4j Desktop（推荐）**
- 下载并安装 [Neo4j Desktop](https://neo4j.com/download/)
- 创建新的数据库项目
- 设置数据库密码（默认用户名：neo4j）
- 启动数据库服务

**选项B：使用Docker**
```bash
docker run -p 7474:7474 -p 7687:7687 -e NEO4J_AUTH=neo4j/your_password neo4j:latest
```

**选项C：直接安装Neo4j Community Edition**
- 从官网下载Neo4j Community Edition
- 按照官方文档安装和配置

### 3. 配置连接信息

在项目根目录的 `config.json` 中配置 Neo4j 连接信息：

```json
{
  "grag": {
    "neo4j_uri": "bolt://localhost:7687",
    "neo4j_user": "neo4j",
    "neo4j_password": "your_password",
    "neo4j_database": "neo4j"
  }
}
```

### 4. 验证连接

启动Neo4j Desktop后，可以通过以下方式验证：
- 访问 http://localhost:7474 打开Neo4j Browser
- 使用配置的用户名密码登录
- 执行测试查询：`MATCH (n) RETURN n LIMIT 5`

### 5. 设置 LLM API Key

在项目根目录的 `config.json` 中配置：

```json
{
  "api": {
    "api_key": "sk-xxx",
    "base_url": "https://api.deepseek.com/v1",
    "model": "deepseek-chat"
  }
}
```

> DeepSeek 注册地址：https://platform.deepseek.com/

---

## 🆕 任务管理器功能

### 任务管理器特性

- **并发处理**: 支持多个五元组提取任务同时进行
- **任务队列**: 智能队列管理，避免重复任务
- **状态监控**: 实时监控任务状态和进度
- **超时控制**: 自动处理超时任务
- **错误处理**: 完善的错误处理和重试机制
- **自动清理**: 定期清理已完成的任务

### 配置选项

在 `config.json` 的 `grag` 段中配置提取预算：

```json
{
  "grag": {
    "enabled": true,
    "auto_extract": true,
    "extraction_timeout": 12,
    "extraction_retries": 2
  }
}
```

- `grag.extraction_timeout`: 单轮五元组提取总超时时间（秒）
- `grag.extraction_retries`: 提取失败后的重试次数
- 任务管理器仍会在运行时维护并发 worker、队列和清理周期，但这些属于内部调度参数，不再作为外部配置口径

### 测试任务管理器

运行测试脚本验证功能：

```bash
cd summer_memory
python test_task_manager.py
```

---

## 🧪 使用方式

### 方法一：运行主程序

```bash
python main.py
```

程序将提示你选择输入方式：
```
请选择输入方式：
1 - 手动输入文本
2 - 从文件读取文本
```

- **手动输入**：支持逐段输入中文语句，提取知识。
- **文件读取**：输入包含多条文本的 `.txt` 文件路径，逐行处理。

成功后将自动打开 `graph.html`，展示生成的知识图谱。

### 方法二：使用任务管理器

```python
from summer_memory.task_manager import task_manager

# 提交提取任务
task_id = task_manager.add_task("小明在图书馆里看书。")

# 查询任务状态
status = task_manager.get_task_status(task_id)
print(f"任务状态: {status['status']}")

# 获取统计信息
stats = task_manager.get_stats()
print(f"运行中任务: {stats['running_tasks']}")
```

### 方法三：使用记忆管理器

```python
from summer_memory.memory_manager import memory_manager

# 添加对话记忆（自动使用任务管理器）
await memory_manager.add_conversation_memory(
    "用户: 你好，我想了解人工智能",
    "Embla: 人工智能是一个快速发展的技术领域..."
)

# 查询记忆
result = await memory_manager.query_memory("什么是人工智能？")
```

---

### 方法四：构建批处理函数

可独立调用：

```python
from summer_memory.main import batch_add_texts

texts = ["李雷在操场上打篮球。", "韩梅梅喜欢读书。"]
batch_add_texts(texts)
```

---

### 方法五：知识图谱问答

图谱构建完成后支持交互式问答：

```text
请输入查询问题（输入空行退出）：
> 谁喜欢读书？
```

将返回从图谱中提取的实体与关系信息。

---

## 📊 可视化效果

使用 PyVis 生成交互式图谱页面 `graph.html`，节点和关系可拖动、放缩、查看信息。

## ✅ 示例输入输出

**输入文本：**

小红在教室里看书。
小明和小强是好朋友。

**生成五元组：**

[
  ["小红", "人物", "看", "书", "物品"],
  ["小明", "人物", "是", "好朋友", "关系"],
  ["小强", "人物", "是", "好朋友", "关系"]
]

**可视化图谱：**

- 小红(人物) —[看]→ 书(物品)  
- 小明(人物) —[是]→ 好朋友(关系)  
- 小强(人物) —[是]→ 好朋友(关系)  

---

## 🔧 高级功能

### 任务管理器API

```python
# 获取所有任务状态
all_tasks = task_manager.get_all_tasks()

# 获取运行中的任务
running_tasks = task_manager.get_running_tasks()

# 取消任务
task_manager.cancel_task(task_id)

# 清理已完成任务
task_manager.clear_completed_tasks(max_age_hours=24)
```

### 记忆管理器API

```python
# 获取记忆统计
stats = memory_manager.get_memory_stats()

# 获取任务状态
task_status = memory_manager.get_task_status(task_id)

# 清空记忆
await memory_manager.clear_memory()
```

---

## 🚀 性能优化

- **并发提取**: 多个五元组提取任务可以同时进行
- **智能去重**: 自动识别重复文本，避免重复提取
- **超时控制**: 防止单个任务长时间阻塞
- **资源管理**: 自动清理过期任务，释放内存
- **错误恢复**: 任务失败时自动回退到同步模式
