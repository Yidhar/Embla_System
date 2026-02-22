# 文档冲突修复总结报告

生成时间：2026-02-22
执行状态：✅ 已完成

---

## 1. 修复概览

### 1.1 修复范围

本次修复覆盖 **9 个核心文档**，消除了 **5 大类架构冲突**，统一了 **As-Is vs Target** 语义标注。

**修复文档列表**：
1. ✅ `00-文档冲突修复计划.md` - 新增
2. ✅ `01-module-overview.md` - 更新 AgentServer 状态
3. ✅ `07-autonomous-agent-sdlc-architecture.md` - 统一 autonomous/ 定位 + 执行模型演进
4. ✅ `09-工具调用与任务执行规范.md` - 增加 Codex-first 路由策略
5. ✅ `架构与时序设计.md` - 修复 Codex 定位 + 增加状态标注
6. ✅ `gemin-结构图.md` - 增加目标态标注 + 实施路径映射
7. ✅ `10-brainstem-layer-modules.md` - 增加实施状态标注
8. ✅ `11-brain-layer-modules.md` - 增加实施状态标注
9. ✅ `12-limbs-layer-modules.md` - 增加实施状态标注

---

## 2. 核心冲突修复详情

### 2.1 Codex 定位冲突 ✅ 已解决

**冲突描述**：
- 旧文档：Codex MCP 仅用于验证降级
- 新实现：Codex 已升级为主执行路径

**修复措施**：
1. **更新 `架构与时序设计.md`**：
   - 删除 §3.4 "验证阶段降级" 的旧描述
   - 新增 §3.2 "Codex-first 策略 v2" 章节
   - 增加优先级表格：Codex (P0) > Claude (P1) > Gemini (P2)
   - 新增 §3.3 CLI 选择策略（Codex-first 实现）
   - 新增 §3.4 Codex 执行模式详解（CLI 模式 + MCP 模式 + 降级场景）

2. **更新 `09-工具调用与任务执行规范.md`**：
   - 增加 Codex 策略版本标注：v2 (2026-02-22)
   - 新增 §3.1 Codex-first 路由策略
   - 明确触发条件、路由规则、自动参数注入、降级场景

3. **更新 `07-autonomous-agent-sdlc-architecture.md`**：
   - 在 §2.1 标注执行策略更新（v1 → v2）
   - 增加执行模型演进路径说明

**验证结果**：
- ✅ 所有文档中 Codex 定位一致
- ✅ 明确标注策略版本和更新时间
- ✅ 提供清晰的历史变更记录

---

### 2.2 执行模型冲突 ✅ 已解决

**冲突描述**：
- `架构与时序设计.md`：描述 CLI Tools
- `gemin-结构图.md`：描述 Sub-Agent Runtime
- 实际代码：使用 CLI Adapter

**修复措施**：
1. **在 `架构与时序设计.md` 顶部增加醒目标注**：
   ```markdown
   ---
   **文档类型**：As-Is 实施文档（Phase 0 MVP）
   **实施状态**：✅ 已实现（autonomous/ 模块）
   **最后验证**：2026-02-22
   **Codex 策略版本**：v2 (Codex-first 主执行路径)
   **目标态参考**：gemin-结构图.md (Sub-Agent Runtime, Phase 3)
   ---
   ```

2. **在 `gemin-结构图.md` 顶部增加目标态标注**：
   ```markdown
   ---
   **文档类型**：🎯 目标态架构设计（Target Architecture）
   **实施状态**：Phase 3 规划（当前 Phase 0 已实现 CLI Adapter 过渡方案）
   **当前替代方案**：见 `架构与时序设计.md` (CLI Tools + Codex-first)
   **实施路径**：Phase 0 (CLI) → Phase 1-2 (增强) → Phase 3 (本文档)
   ---
   ```

3. **在 `gemin-结构图.md` 增加实施路径映射表**：
   - 对比目标态组件与当前实现
   - 使用图例标注：🟢 已实现 / 🟡 部分实现 / 🔴 未实现

4. **在 `07-autonomous-agent-sdlc-architecture.md` 增加执行模型演进路径**：
   - Phase 0：CLI Adapter + Codex MCP（✅ 已实现）
   - Phase 1-2：增强监控与降级（🟡 规划中）
   - Phase 3：Sub-Agent Runtime（🔴 目标态）

**验证结果**：
- ✅ 读者能快速区分 As-Is vs Target
- ✅ 演进路径清晰可追溯
- ✅ 实施状态映射完整

---

### 2.3 子代理架构冲突 ✅ 已解决

**冲突描述**：
- 目标态文档：描述 Sub-Agent Runtime (Frontend/Backend/Ops)
- 实际代码：无子代理实现，使用 CLI Adapter

**修复措施**：
1. **在所有目标态文档（gemin/10/11/12）顶部增加统一标注**：
   ```markdown
   ---
   **文档类型**：🎯 目标态架构设计（Target Architecture - Phase 3）
   **实施状态**：Phase 3 规划（当前 Phase 0 部分实现）
   **最后更新**：2026-02-22
   **当前替代方案**：[具体实现]
   **实施路径**：Phase 0 → Phase 1-2 → Phase 3 (本文档)
   ---
   ```

2. **在每个目标态文档增加当前实现映射**：
   - `11-brain-layer-modules.md`：
     - Meta-Agent → System Agent
     - Router → CLI Selector
   - `12-limbs-layer-modules.md`：
     - Sub-Agent Runtime → CLI Adapter
     - Scaffold Engine → 无（目标态）

3. **在 `gemin-结构图.md` 增加实施路径映射表**：
   - 完整对比 Phase 3 目标态与 Phase 0 当前实现
   - 明确标注每个组件的实施阶段和状态

**验证结果**：
- ✅ 目标态文档有清晰的实施状态标注
- ✅ 当前实现与目标态的映射关系明确
- ✅ 避免混淆"设计"与"实现"

---

### 2.4 autonomous/ 定位冲突 ✅ 已解决

**冲突描述**：
- 不同文档对 autonomous/ 的定位描述不一致
- 缺少统一的职责与架构定位说明

**修复措施**：
1. **在 `07-autonomous-agent-sdlc-architecture.md` 增加统一定义**：
   ```markdown
   ## 1.1 autonomous/ 模块统一定位

   **核心职责**：
   - System Agent 自治闭环（感知 → 规划 → 执行 → 评估）
   - SDLC 工作流状态管理（Workflow Store + Event Log）
   - 单活 Lease/Fencing 防双主
   - Canary 发布与自动回滚

   **架构定位**：
   - 属于 Brainstem 层（控制与接入）
   - 与 apiserver 平级，独立后台运行
   - 通过 Event Bus 与其他模块通信（目标态）
   - 当前通过 CLI Adapter 调用外部工具（Phase 0）

   **运行模式**：
   - Phase 0（当前）：单实例常驻，按配置周期执行
   - Phase 1-2：增加 Standby 实例，Lease 抢占
   - Phase 3：完整 Event Bus 驱动
   ```

2. **在 `gemin-结构图.md` 的目录树中明确标注**：
   - 增加 🟢 已实现标记
   - 详细列出 autonomous/ 子模块及其状态

**验证结果**：
- ✅ autonomous/ 定位在所有文档中一致
- ✅ 职责边界清晰
- ✅ 演进路径明确

---

### 2.5 AgentServer 状态冲突 ✅ 已解决

**冲突描述**：
- 不同文档对 AgentServer 的状态描述不一致
- 缺少统一的弃用说明和清理计划

**修复措施**：
1. **在 `01-module-overview.md` 增加完整的弃用说明**：
   ```markdown
   ## 6. AgentServer 状态（已弃用）

   **当前状态**：
   - 代码保留但已禁用自动启动（2026-02-20）
   - Legacy 执行接口返回 `deprecated`

   **弃用原因**：
   - OpenClaw 旧执行链路已被替代
   - 架构简化：减少服务依赖，统一执行入口

   **替代方案**：
   - 工具调用：agentic_tool_loop + native_tools / mcp_manager
   - 自治执行：autonomous/system_agent.py + CLI Adapter

   **清理计划**：
   - Phase 1：标记所有接口为 deprecated（✅ 已完成）
   - Phase 2：完全移除代码与配置（🟡 规划中）
   ```

2. **从架构图中移除 AgentServer**：
   - `gemin-结构图.md`：未提及 AgentServer（正确）
   - `架构与时序设计.md`：未提及 AgentServer（正确）

**验证结果**：
- ✅ AgentServer 状态在所有文档中一致
- ✅ 弃用原因和替代方案清晰
- ✅ 清理计划明确

---

## 3. 文档标注规范

### 3.1 统一的文档头部标注

**As-Is 文档**（当前实现）：
```markdown
---
**文档类型**：As-Is 实施文档（Phase X）
**实施状态**：✅ 已实现 / 🟡 部分实现
**最后验证**：YYYY-MM-DD
**当前实现**：[具体模块/文件]
**目标态参考**：[目标态文档]
---
```

**Target 文档**（目标态设计）：
```markdown
---
**文档类型**：🎯 目标态架构设计（Target Architecture - Phase X）
**实施状态**：Phase X 规划（当前 Phase Y 部分实现）
**最后更新**：YYYY-MM-DD
**当前替代方案**：[As-Is 实现]
**实施路径**：Phase 0 → Phase 1-2 → Phase 3 (本文档)
---
```

**Hybrid 文档**（混合文档）：
```markdown
---
**文档类型**：As-Is + Target-Aligned（混合文档）
**实施状态**：Phase X 已实现 + Phase Y-Z 规划
**最后更新**：YYYY-MM-DD
**当前实现**：[具体模块]
**目标态参考**：[目标态文档]
---
```

### 3.2 图例标注规范

**状态图例**：
- 🟢 **已实现** (Phase 0)：当前代码可运行
- 🟡 **部分实现** (Phase 1-2)：骨架存在，功能待增强
- 🔴 **未实现** (Phase 3)：目标态设计
- ⚪ **已弃用**：保留兼容但不推荐使用

---

## 4. 实施路径映射

### 4.1 Phase 划分

| Phase | 时间范围 | 核心目标 | 状态 |
|-------|---------|---------|------|
| **Phase 0** | 2026-02-20 前 | CLI Adapter + System Agent + 基础 MCP | 🟢 已实现 |
| **Phase 1-2** | 2026-03-01 ~ 2026-04-30 | 增强监控、Token 经济学、并发安全墙 | 🟡 规划中 |
| **Phase 3** | 2026-05-01 ~ 2026-06-30 | Sub-Agent Runtime + Event Bus + 完整守护 | 🔴 目标态 |

### 4.2 关键组件演进路径

| 组件 | Phase 0 (当前) | Phase 1-2 (规划) | Phase 3 (目标态) |
|------|---------------|-----------------|-----------------|
| **执行模型** | CLI Adapter | 增强监控 + 降级 | Sub-Agent Runtime |
| **编码工具** | Codex CLI/MCP | 多 CLI 负载均衡 | Scaffold Engine |
| **事件系统** | Event Store (SQLite) | 增强分发 + 去重 | Event Bus (PubSub) |
| **记忆系统** | 对话上下文 | GC Engine | 三维记忆（WM/EM/SG） |
| **安全内核** | Native Executor | Regex Firewall | Security Kernel |
| **监控系统** | 无 | 基础监控 | Watchdog + KillSwitch |

---

## 5. 验收标准

### 5.1 状态标注完整性 ✅

- [x] 所有文档顶部有明确的 `文档类型` 标注
- [x] 目标态文档标注 `实施状态` 和 `Phase`
- [x] As-Is 文档标注 `最后验证时间`
- [x] 混合文档明确区分 As-Is 和 Target 部分

### 5.2 冲突消除验证 ✅

- [x] Codex 定位在所有文档中一致（v2 Codex-first）
- [x] 执行模型描述与实际代码对齐（CLI Adapter）
- [x] 子代理架构有清晰的实施路径（Phase 0 → Phase 3）
- [x] autonomous/ 定位统一（Brainstem 层 + SDLC 管理）
- [x] AgentServer 状态统一（已弃用，Phase 2 清理）

### 5.3 可读性提升 ✅

- [x] 新读者能快速区分 As-Is vs Target
- [x] 开发者能找到当前实现的准确描述
- [x] 架构师能理解演进路径
- [x] 实施路径映射表完整清晰

---

## 6. 后续维护建议

### 6.1 文档更新规则

1. **修改 As-Is 文档**：
   - 必须与代码同步更新
   - 更新 `最后验证` 时间戳
   - 如有策略变更，增加版本标注

2. **修改 Target 文档**：
   - 必须标注 Phase 和依赖
   - 更新实施路径映射表
   - 保持与 As-Is 文档的引用关系

3. **新增功能**：
   - 同时更新 As-Is 和 Target 映射
   - 在实施路径映射表中标注状态变更
   - 更新相关交叉引用

### 6.2 冲突预防检查清单

**新增执行路径时**：
- [ ] 检查是否与现有描述冲突
- [ ] 更新所有相关文档的执行链路说明
- [ ] 增加策略版本标注

**修改模块定位时**：
- [ ] 更新所有引用文档
- [ ] 更新架构图中的模块位置
- [ ] 更新实施路径映射表

**弃用功能时**：
- [ ] 统一标注弃用状态和时间
- [ ] 清理架构图中的相关节点
- [ ] 提供替代方案说明
- [ ] 制定清理计划

**升级策略时**：
- [ ] 更新所有相关文档的版本标注
- [ ] 记录历史变更
- [ ] 更新实施路径映射表

### 6.3 定期审查机制

**每月审查**：
- [ ] 检查 As-Is 文档与代码的一致性
- [ ] 验证实施路径映射表的准确性
- [ ] 更新 Phase 进度

**每季度审查**：
- [ ] 重新评估 Target 文档的合理性
- [ ] 调整 Phase 划分和时间线
- [ ] 清理过时的弃用内容

---

## 7. 修复成果总结

### 7.1 量化指标

- **修复文档数量**：9 个
- **消除冲突类型**：5 大类
- **新增标注规范**：3 种（As-Is / Target / Hybrid）
- **新增映射表**：2 个（实施路径 + Phase 划分）
- **统一定义**：3 个（autonomous/ / AgentServer / Codex 策略）

### 7.2 质量提升

**修复前**：
- ❌ 文档间存在严重冲突
- ❌ As-Is 与 Target 混淆
- ❌ 实施路径不清晰
- ❌ 策略版本无追溯

**修复后**：
- ✅ 文档语义统一一致
- ✅ As-Is 与 Target 明确区分
- ✅ 实施路径清晰可追溯
- ✅ 策略版本有明确标注

### 7.3 用户体验提升

**新读者**：
- 能快速理解当前实现状态
- 能区分设计文档与实施文档
- 能找到准确的代码入口

**开发者**：
- 能准确定位当前实现
- 能理解演进路径
- 能避免引用已弃用功能

**架构师**：
- 能理解完整的架构演进
- 能评估实施进度
- 能规划下一阶段工作

---

## 8. 附录

### 8.1 修复前后对比

**Codex 定位**：
- 修复前：`架构与时序设计.md` 描述"验证降级"，与实际代码冲突
- 修复后：统一为 "Codex-first 主执行路径 v2"，增加详细策略说明

**执行模型**：
- 修复前：CLI Tools 与 Sub-Agent Runtime 描述混乱
- 修复后：明确 Phase 0 (CLI) → Phase 3 (Sub-Agent) 演进路径

**子代理架构**：
- 修复前：目标态文档未标注实施状态，易混淆
- 修复后：所有目标态文档顶部有醒目标注 + 实施路径映射

**autonomous/ 定位**：
- 修复前：不同文档描述不一致
- 修复后：统一定义职责、架构定位、运行模式

**AgentServer 状态**：
- 修复前：弃用说明分散，清理计划不明确
- 修复后：统一弃用说明 + 替代方案 + 清理计划

### 8.2 相关文档索引

- 修复计划：`00-文档冲突修复计划.md`
- 修复总结：`00-文档冲突修复总结.md`（本文档）
- 模块总览：`01-module-overview.md`
- SDLC 架构：`07-autonomous-agent-sdlc-architecture.md`
- 工具规范：`09-工具调用与任务执行规范.md`
- MVP 实施：`架构与时序设计.md`
- 目标态蓝图：`gemin-结构图.md`
- 脑干层：`10-brainstem-layer-modules.md`
- 大脑层：`11-brain-layer-modules.md`
- 手脚层：`12-limbs-layer-modules.md`

---

**修复完成时间**：2026-02-22
**修复执行者**：Claude Opus 4.6
**文档版本**：v2.0 (Codex-first + Phase 标注)
