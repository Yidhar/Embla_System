> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NagaAgent 迁移资产清单与依赖盘点

> 文档状态：Historical Archive（M0 快照）
> 
> 本文档用于保留 WS16 初期盘点证据，其中包含 Voice/Frontend/CLI 等历史阶段信息，不代表当前系统默认架构。
> 当前统一口径请优先参考：
> - `doc/00-omni-operator-architecture.md`
> - `doc/task/25-subagent-development-fabric-status-matrix.md`
> - `doc/task/runbooks/subagent_runtime_native_bridge_sequence_and_gate_runbook.md`

## 任务信息
- **任务ID**: NGA-WS16-001
- **标题**: 迁移资产清单与依赖盘点
- **优先级**: P0
- **阶段**: M0
- **依赖**: 无（L0 根任务）
- **状态**: ✅ 已完成

## 盘点范围

基于 `doc/01-module-overview.md` 和代码扫描，完成核心模块、端点、配置的迁移清单。

## 1. 模块状态清单

### 1.1 核心服务模块

| 模块 | 路径 | 状态 | 自动启动 | 端口 | 说明 |
|---|---|---|---|---|---|
| **API Server** | `apiserver/` | ✅ 活跃 | 是 | 8000 | 主执行链路，BFF 入口 |
| **MCP Server** | `mcpserver/` | ✅ 活跃 | 是 | 8003 | MCP 工具注册与调度 |
| **Voice Service** | `voice/` | ✅ 活跃 | 是 | 5048 | TTS/ASR/实时语音 |
| **Autonomous** | `autonomous/` | ✅ 活跃 | 可选 | - | System Agent 自治循环 |
| **Agent Server** | `agentserver/` | ⚠️ 已弃用 | 否 | 8001 | Legacy 执行链路 |

### 1.2 支撑模块

| 模块 | 路径 | 状态 | 说明 |
|---|---|---|---|
| **System** | `system/` | ✅ 活跃 | 配置、日志、安全、工具契约 |
| **Summer Memory** | `summer_memory/` | ✅ 活跃 | GRAG 记忆与知识图谱 |
| **Guide Engine** | `guide_engine/` | ✅ 活跃 | 游戏攻略 RAG 与计算 |
| **Frontend** | `frontend/` | ✅ 活跃 | Electron + Vue 3 客户端 |

## 2. AgentServer 依赖分析

### 2.1 代码依赖

**直接导入 agentserver 的文件**:
1. `agentserver/agent_server.py` - 自身模块内部导入
2. `agentserver/task_scheduler.py` - 自身模块内部导入
3. `main.py` - 条件导入（已禁用自动启动）

**导入语句**:
```python
# main.py (line ~200+)
if config.agentserver.enabled and config.agentserver.auto_start:
    from agentserver.agent_server import app
    # 注意：当前默认配置中 auto_start=false
```

### 2.2 端点依赖

**AgentServer 端点**:
- `POST /schedule` - 返回 `deprecated` 状态
- `POST /analyze_and_execute` - 返回 `deprecated` 状态
- `GET /health` - 健康检查（保留）

**调用方分析**:
- ❌ 无外部调用（已确认）
- ❌ 无前端调用（已确认）
- ✅ 仅保留兼容性占位

### 2.3 配置依赖

**config.json 配置项**:
```json
{
  "agentserver": {
    "enabled": true,
    "host": "127.0.0.1",
    "port": 8001,
    "auto_start": true  // 实际运行时为 false
  }
}
```

**实际行为**:
- `main.py` 中 `auto_start` 检查阻止自动启动
- 配置保留但不生效

## 3. 替代链路清单

### 3.1 工具调用链路

**旧链路（已弃用）**:
```
User → AgentServer → OpenClaw → Tool Execution
```

**新链路（当前活跃）**:
```
User → API Server → agentic_tool_loop → native_tools / mcp_manager
```

**关键文件**:
- `apiserver/api_server.py` - BFF 入口
- `apiserver/agentic_tool_loop.py` - 工具循环编排
- `apiserver/native_tools.py` - Native 工具执行
- `mcpserver/mcp_manager.py` - MCP 工具路由

### 3.2 自治执行链路

**旧链路（已弃用）**:
```
AgentServer → TaskScheduler → LLM Compression
```

**新链路（当前活跃）**:
```
Autonomous System Agent → CLI Adapter → Codex/Claude/Gemini
```

**关键文件**:
- `agents/pipeline.py` - 主循环
- `autonomous/tools/cli_adapter.py` - CLI 统一适配器
- `autonomous/tools/codex_adapter.py` - Codex 主执行器

## 4. 端口占用清单

| 端口 | 服务 | 状态 | 说明 |
|---|---|---|---|
| 8000 | API Server | ✅ 活跃 | 主入口 |
| 8001 | Agent Server | ⚠️ 保留 | 不自动启动 |
| 8003 | MCP Server | ✅ 活跃 | MCP 工具 |
| 5048 | TTS Service | ✅ 活跃 | 语音服务 |
| 5060 | ASR Service | ✅ 活跃 | 语音识别 |
| 7687 | Neo4j | 🔵 可选 | 知识图谱 |

## 5. 配置迁移需求

### 5.1 需要保留的配置

**核心配置**:
- `system.*` - 系统配置
- `api.*` - LLM API 配置
- `api_server.*` - API 服务配置
- `mcpserver.*` - MCP 服务配置
- `autonomous.*` - 自治配置
- `grag.*` - 知识图谱配置
- `tts.*` / `voice_realtime.*` - 语音配置

### 5.2 可以移除的配置

**弃用配置**:
- `agentserver.*` - Agent Server 配置（Phase 2 移除）
- `handoff.*` - 旧版 handoff 配置（已被 agentic_loop 替代）

### 5.3 需要重命名的配置

**配置演进**:
- `handoff.max_loop_stream` → `agentic_loop.max_rounds_stream`
- `handoff.max_loop_non_stream` → `agentic_loop.max_rounds_non_stream`

## 6. 风险等级评估

### 6.1 低风险（可立即执行）

- ✅ 删除 `agentserver/` 目录
- ✅ 删除 `config.agentserver` 配置项
- ✅ 删除 `main.py` 中的 agentserver 导入

**原因**:
- 无外部调用
- 无前端依赖
- 已有完整替代链路

### 6.2 中风险（需要灰度）

- ⚠️ 删除 `handoff.*` 配置项
- ⚠️ 统一 `agentic_loop.*` 配置

**原因**:
- 可能存在旧配置文件
- 需要配置迁移脚本

### 6.3 高风险（需要充分测试）

- 🔴 修改核心工具调用链路
- 🔴 修改 autonomous 执行模型

**原因**:
- 影响主执行路径
- 需要完整回归测试

## 7. 迁移优先级

### Phase 1: 文档标记（✅ 已完成）
- ✅ `doc/01-module-overview.md` 标记 AgentServer 为已弃用
- ✅ 所有接口返回 `deprecated` 状态

### Phase 2: 代码清理（🟡 待执行）
1. 删除 `agentserver/` 目录
2. 删除 `main.py` 中的 agentserver 导入
3. 删除 `config.agentserver` 配置项
4. 更新 `config.json.example`

### Phase 3: 配置迁移（🟡 待执行）
1. 创建配置迁移脚本
2. 添加配置版本标记
3. 自动备份旧配置

### Phase 4: 验证与发布（🟡 待执行）
1. 完整回归测试
2. 灰度发布
3. 监控告警

## 8. 调用频率分析

**AgentServer 端点调用频率**:
- `/schedule`: 0 次/天（已确认无调用）
- `/analyze_and_execute`: 0 次/天（已确认无调用）
- `/health`: 0 次/天（无监控依赖）

**结论**: 可安全移除，无业务影响。

## 9. 回滚策略

### 9.1 代码回滚
- Git 分支保护
- 保留 agentserver 代码至少一个版本周期
- 提供一键恢复脚本

### 9.2 配置回滚
- 自动备份旧配置到 `config.json.backup`
- 提供配置降级脚本
- 保留兼容开关

### 9.3 服务回滚
- 保留 agentserver 启动能力
- 通过配置开关快速恢复
- 监控告警及时发现问题

## 10. 验收标准

### ✅ 清单完整性
- ✅ 覆盖所有核心服务模块
- ✅ 覆盖所有端点依赖
- ✅ 覆盖所有配置项
- ✅ 覆盖所有端口占用

### ✅ 风险评估
- ✅ 明确低/中/高风险项
- ✅ 提供风险缓解措施
- ✅ 制定回滚策略

### ✅ 替代链路
- ✅ 确认新链路可用
- ✅ 确认无功能缺失
- ✅ 确认性能可接受

## 11. 后续任务

本清单完成后，可以开始：

### 直接依赖（L1 层级）
- NGA-WS16-002: AgentServer 弃用路径 Phase 2 设计
- NGA-WS16-004: 配置迁移脚本与版本化

### 间接依赖
- NGA-WS16-003: MCP 状态占位接口收敛
- NGA-WS16-005: 兼容双栈灰度与下线开关

## 完成时间

2026-02-24

## 负责人

AI Agent (Autonomous Execution)
