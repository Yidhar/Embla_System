# `logs/knowledge_graph`

这个目录只存放 `summer_memory` 的运行时产物。

## 文件

```text
logs/knowledge_graph/
├── quintuples.json   # 五元组事实缓存
└── graph.html        # 基于 quintuples.json 生成的可视化页面
```

## 生成来源

- `quintuples.json`
  - 写入方：`summer_memory/quintuple_graph.py`
  - 触发源：`summer_memory/memory_manager.py` / `summer_memory/main.py`

- `graph.html`
  - 生成方：`summer_memory/quintuple_visualize.py`
  - 数据源：`quintuples.json`

## 当前口径

- 这是运行时数据目录，不是源码目录
- 文件内容可以被覆盖、清空或重建
- 当前 canonical 数据模型是五元组
- 旧三元组产物已经退役

## 常用操作

```bash
# 查看五元组数据
cat logs/knowledge_graph/quintuples.json

# 在 Linux 上打开图谱
xdg-open logs/knowledge_graph/graph.html
```

## 注意

- `graph.html` 不是事实源，只是 `quintuples.json` 的可视化投影
- 清理图谱记忆时，应同时考虑 JSON 文件、Neo4j 节点关系和向量索引
