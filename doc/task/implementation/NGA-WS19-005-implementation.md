> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS19-005 实施记录（Episodic Memory 写入与检索链路）

## 任务信息
- 任务ID: `NGA-WS19-005`
- 标题: Episodic Memory 写入与检索链路
- 状态: 已完成（最小可交付）

## 变更范围
- `agents/memory/episodic_memory.py`（当前 canonical）
- `apiserver/agentic_tool_loop.py`
- `tests/test_episodic_memory.py`（新增）

## 实施内容
1. 本地 episodic archive 落盘
- 采用 JSONL 本地归档（默认 `logs/episodic_memory/episodic_archive.jsonl`）。
- 记录字段：
  - `record_id`
  - `session_id`
  - `source_tool`
  - `narrative_summary`
  - `forensic_artifact_ref`
  - `fetch_hints`
  - `timestamp`

2. 轻量检索策略（无外部向量依赖）
- 确定性分词（英文/CJK）+ hashing sparse vector。
- 余弦相似度召回，排序为 `score desc -> timestamp desc -> record_id asc`。
- 支持会话偏置（同 session 轻微加权），提高会话内稳定召回。

3. 回注（reinjection）链路
- 在 loop 启动前根据最新用户请求检索 top-k 历史经验并注入系统上下文。
- 每轮工具执行后归档执行结果，形成持续可检索经验池。

## 验证
- `uv --cache-dir .uv_cache run python -m pytest -q tests/test_episodic_memory.py`
- `uv --cache-dir .uv_cache run python -m ruff check agents/memory/episodic_memory.py agents/tool_loop.py tests/test_episodic_memory.py`

结果：通过。
