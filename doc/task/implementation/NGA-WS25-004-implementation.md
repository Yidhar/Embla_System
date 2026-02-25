# NGA-WS25-004 实施记录（关键证据字段保真策略）

## 1. 背景

在 `WS25-001~003` 后，事件总线的 Topic/Replay 能力已具备，但对 GC 场景仍有一个风险：

1. 大输出进入摘要后，`trace_id / error_code / path` 可能只存在于原始 artifact；
2. 若仅凭叙事摘要继续排障，关键硬证据可见性不足；
3. 归档回读链路需要稳定的结构化入口来复用这些证据。

本任务目标是把关键证据从“隐式存在于原文”升级为“显式透传字段”。

## 2. 实施内容

1. Tool Contract 增加关键证据快照字段
   - 文件：`system/tool_contract.py`
   - `ToolResultEnvelope` 新增 `critical_evidence` 字段：
     - `trace_ids`
     - `error_codes`
     - `paths`
   - `build_tool_result_with_artifact()` 在结构化/超长输出分支统一提取证据并透传：
     - 保留 `fetch_hints`
     - 同步输出 `critical_evidence`
   - 结构化摘要新增 `Critical evidence: ...` 行，保证摘要链路可见硬字段。

2. Native 工具结果文本透传关键证据
   - 文件：`apiserver/native_tools.py`
   - `_render_tool_result_envelope()` 新增标准字段：
     - `[critical_evidence] {...}`
   - 与现有 `[forensic_artifact_ref]`、`[fetch_hints]` 并行输出。

3. Agentic Loop 新契约检测补齐
   - 文件：`apiserver/agentic_tool_loop.py`
   - `_has_new_contract_payload()` 纳入 `critical_evidence` 检测。

4. Episodic 归档回读增强
   - 文件：`system/episodic_memory.py`
   - `_extract_from_result_text()` 增强：
     - 解析 `[critical_evidence]` JSON
     - 自动补全 `grep:*` hints（trace/error/path）
   - 使归档检索在缺少显式 `fetch_hints` 时仍可保留关键排障锚点。

## 3. 变更文件

- `system/tool_contract.py`
- `apiserver/native_tools.py`
- `apiserver/agentic_tool_loop.py`
- `system/episodic_memory.py`
- `tests/test_tool_contract.py`
- `tests/test_native_tools_ws11_003.py`
- `tests/test_episodic_memory.py`
- `doc/task/23-phase3-full-target-task-list.md`
- `doc/00-omni-operator-architecture.md`
- `doc/task/implementation/NGA-WS25-004-implementation.md`

## 4. 验证记录

```bash
.\.venv\Scripts\python.exe -m pytest -q tests/test_tool_contract.py tests/test_native_tools_ws11_003.py tests/test_episodic_memory.py tests/test_gc_evidence_extractor.py tests/test_gc_reader_bridge.py tests/test_gc_memory_card_injection.py
```

M10 事件链路兼容回归：

```bash
.\.venv\Scripts\python.exe -m pytest -q autonomous/tests/test_topic_event_bus_ws25_001.py autonomous/tests/test_cron_alert_producer_ws25_002.py autonomous/tests/test_topic_event_bus_replay_idempotency_ws25_003.py autonomous/tests/test_system_agent_topic_bus_ws25_001.py autonomous/tests/test_system_agent_cron_alert_ws25_002.py autonomous/tests/test_system_agent_release_flow.py autonomous/tests/test_system_agent_outbox_bridge_ws23_005.py autonomous/tests/test_event_store_ws18_001.py autonomous/tests/test_event_replay_tool_ws18_003.py
```

## 5. 结果

- 工具执行结果中关键证据字段实现结构化保真；
- 摘要、文本回执、归档链路对 trace/error/path 的可见性提升；
- M10 下一步可推进 `WS25-005`（Event/GC 质量评测基线）。
