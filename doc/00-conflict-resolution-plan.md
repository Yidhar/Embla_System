# 文档冲突修复计划

生成时间：2026-02-22
状态：待执行

## 1. 核心冲突识别

### 1.1 执行模型冲突 ⚠️ 严重

**冲突描述**：
- `00-mvp-architecture-design.md`：描述 Agent CLI Tools (Codex/Claude/Gemini CLI) 作为外部进程调用
- `00-omni-operator-architecture.md`：描述 Sub-Agent Runtime + Scaffold Engine 作为目标架构
- `07-autonomous-agent-sdlc-architecture.md`：明确"CLI 节点不再是主执行设计"
- **实际代码**：`autonomous/` 使用 CLI Adapter + Codex MCP

**修复策略**：
1. 在 `00-mvp-architecture-design.md` 顶部增加醒目标注：
   ```
   > **文档定位**：本文是 Phase 0 (MVP) 实施稿，描述 CLI Tools 作为过渡方案。
   > **目标态**：见 `00-omni-operator-architecture.md` 的 Sub-Agent Runtime 架构。
   > **当前实现**：autonomous/ 使用 CLI Adapter，符合本文描述。
   ```

2. 在 `00-omni-operator-architecture.md` 的 Sub-Agent 章节增加：
   ```
   > **实施路径**：Phase 0 使用 CLI Tools 过渡，Phase 3 切换到 Sub-Agent Runtime。
   > **当前状态**：CLI Adapter 已实现，Sub-Agent Runtime 为目标态设计。
   ```

3. 在 `07-autonomous-agent-sdlc-architecture.md` 增加明确说明：
   ```
   ### 2.7 执行模型演进路径
   - **Phase 0 (当前)**：CLI Adapter + Codex MCP
   - **Phase 1-2**：保持 CLI 模式，增强监控与降级
   - **Phase 3**：引入 Sub-Agent Runtime，逐步替换 CLI
   ```

---

### 1.2 Codex 定位冲突 ⚠️ 严重

**冲突描述**：
- `task-autonomous-skeleton.md`：Codex-first 主执行路径（最新状态）
- `00-mvp-architecture-design.md`：Codex MCP 仅验证降级（旧描述）
- `09-tool-execution-specification.md`：Codex-first 编码策略（已更新）
- `00-omni-operator-architecture.md`：未明确 Codex 定位

**修复策略**：
1. **更新 `00-mvp-architecture-design.md`**：
   - 删除 §3.4 "验证阶段降级：Codex MCP" 的"仅降级"描述
   - 改为：
     ```markdown
     ### 3.4 Codex 执行策略（已更新为主路径）

     **当前策略**（2026-02-22 更新）：
     - Codex CLI / Codex MCP 作为**编码任务主执行路径**
     - 优先级：codex > claude > gemini
     - 降级场景：Codex 不可用时才使用 Claude/Gemini

     **历史变更**：
     - 初版设计：Codex 仅用于验证阶段降级
     - 当前版本：Codex 升级为主执行工具
     ```

2. **更新 `00-omni-operator-architecture.md`**：
   - 在 §2 工程目录树中增加：
     ```markdown
     ├── autonomous/
     │   ├── tools/
     │   │   ├── cli_adapter.py          # CLI 统一适配器
     │   │   ├── codex_adapter.py        # Codex CLI/MCP 主执行器
     │   │   ├── claude_adapter.py       # Claude Code 降级备选
     │   │   └── gemini_adapter.py       # Gemini CLI 降级备选
     ```

3. **在所有文档顶部增加版本标注**：
   ```markdown
   > **Codex 策略版本**：v2 (2026-02-22)
   > Codex 已从"验证降级"升级为"主执行路径"。
   ```

---

### 1.3 AgentServer 状态冲突 ⚠️ 中等

**冲突描述**：
- `01-module-overview.md`：已弃用
- `task-autonomous-skeleton.md`：已禁用自动启动
- `00-omni-operator-architecture.md` / `00-mvp-architecture-design.md`：未提及

**修复策略**：
1. **统一表述为**：
   ```markdown
   ## AgentServer 状态（已弃用）

   - **当前状态**：代码保留但已禁用自动启动
   - **弃用时间**：2026-02-20
   - **替代方案**：apiserver + agentic_tool_loop + native/mcp
   - **保留原因**：兼容性考虑，避免破坏性删除
   - **清理计划**：Phase 2 完全移除
   ```

2. **在所有架构图中移除 AgentServer**：
   - `00-omni-operator-architecture.md` 的 Mermaid 图中删除 AgentServer 节点
   - `00-mvp-architecture-design.md` 的时序图中删除 AgentServer 相关流程

---

### 1.4 子代理架构冲突 ⚠️ 严重

**冲突描述**：
- `00-omni-operator-architecture.md`：Sub-Agent Runtime (Frontend/Backend/Ops)
- `11-brain-layer-modules.md`：Meta-Agent 派发子 Agent
- `12-limbs-layer-modules.md`：Sub-Agent Fabric
- **实际代码**：autonomous/ 无子代理实现

**修复策略**：
1. **在所有目标态文档顶部增加醒目标注**：
   ```markdown
   ---
   **文档类型**：目标态架构设计（Target Architecture）
   **实施状态**：Phase 3 规划，当前未实现
   **当前替代**：CLI Adapter (见 `00-mvp-architecture-design.md`)
   ---
   ```

2. **创建实施路径映射表**：
   ```markdown
   ## 子代理实施路径

   | 目标态组件 | 当前实现 | 实施阶段 | 状态 |
   |-----------|---------|---------|------|
   | Sub-Agent Runtime | CLI Adapter | Phase 0 | ✅ 已实现 |
   | Frontend Sub-Agent | Codex CLI | Phase 0 | ✅ 已实现 |
   | Backend Sub-Agent | Codex CLI | Phase 0 | ✅ 已实现 |
   | Ops Sub-Agent | Codex CLI | Phase 0 | ✅ 已实现 |
   | Scaffold Engine | 无 | Phase 3 | ❌ 未实现 |
   | Execution Bridge | CLI Adapter | Phase 0 | ✅ 已实现 |
   ```

3. **在 `00-omni-operator-architecture.md` 增加实施状态图例**：
   ```markdown
   图例：
   - 🟢 已实现 (Phase 0)
   - 🟡 部分实现 (Phase 1-2)
   - 🔴 未实现 (Phase 3)
   - ⚪ 已弃用
   ```

---

### 1.5 autonomous/ 定位冲突 ⚠️ 中等

**冲突描述**：
- `01-module-overview.md`：System Agent 自治闭环
- `07-autonomous-agent-sdlc-architecture.md`：SDLC 工作流管理
- `00-omni-operator-architecture.md`：未明确定位
- `00-mvp-architecture-design.md`：MVP 单实例常驻

**修复策略**：
1. **统一定义**：
   ```markdown
   ## autonomous/ 模块定位

   **核心职责**：
   - System Agent 自治闭环（感知 → 规划 → 执行 → 评估）
   - SDLC 工作流状态管理（Workflow Store + Event Log）
   - 单活 Lease/Fencing 防双主
   - Canary 发布与自动回滚

   **架构定位**：
   - 属于 Brainstem 层（控制与接入）
   - 与 apiserver 平级，独立后台运行
   - 通过 Event Bus 与其他模块通信（目标态）
   - 当前通过 CLI Adapter 调用外部工具

   **运行模式**：
   - Phase 0：单实例常驻，按配置周期执行
   - Phase 1-2：增加 Standby 实例，Lease 抢占
   - Phase 3：完整 Event Bus 驱动
   ```

2. **在 `00-omni-operator-architecture.md` 的目录树中明确标注**：
   ```markdown
   └── NagaAgent/                          # ═══ 现有项目集成层 ═══
       ├── autonomous/                     # 🟢 System Agent 自治闭环 (Phase 0 已实现)
       │   ├── system_agent.py             # 主循环：感知 → 规划 → 执行 → 评估
       │   ├── state/workflow_store.py     # SDLC 工作流状态机 + Lease/Fencing
       │   ├── tools/cli_adapter.py        # CLI 工具适配器 (Codex/Claude/Gemini)
       │   └── release/controller.py       # Canary 发布控制器
   ```

---

## 2. 次要冲突

### 2.1 Token 经济学描述不一致

**冲突**：
- `04-api-protocol-proxy-guide.md`：目标态规范，未实现
- `09-tool-execution-specification.md`：硬约束，待落地
- `00-omni-operator-architecture.md`：详细设计，Phase 2

**修复**：统一标注实施状态，增加 Phase 映射。

### 2.2 MCP 状态接口混乱

**冲突**：
- `01-module-overview.md`：占位响应
- 实际代码：部分真实，部分占位

**修复**：明确标注哪些接口是占位，哪些是真实。

---

## 3. 修复优先级

### P0 - 立即修复（影响理解）
1. ✅ Codex 定位冲突（更新 `00-mvp-architecture-design.md`）
2. ✅ 执行模型冲突（增加 Phase 标注）
3. ✅ 子代理架构冲突（增加实施状态标注）

### P1 - 本周修复（影响开发）
4. autonomous/ 定位冲突（统一定义）
5. AgentServer 状态冲突（统一表述）

### P2 - 下周修复（影响规划）
6. Token 经济学描述不一致
7. MCP 状态接口混乱

---

## 4. 修复执行计划

### 阶段一：增加状态标注（2h）
- [ ] 在所有目标态文档顶部增加 `文档类型` 标注
- [ ] 在所有 As-Is 文档顶部增加 `当前实现` 标注
- [ ] 创建统一的状态图例

### 阶段二：修复核心冲突（4h）
- [ ] 更新 `00-mvp-architecture-design.md` Codex 章节
- [ ] 更新 `00-omni-operator-architecture.md` 增加实施路径映射
- [ ] 更新 `07-autonomous-agent-sdlc-architecture.md` 增加执行模型演进路径
- [ ] 统一 autonomous/ 定位描述

### 阶段三：清理弃用内容（2h）
- [ ] 从所有架构图中移除 AgentServer
- [ ] 统一 AgentServer 弃用说明
- [ ] 清理过时的执行链路描述

### 阶段四：验证一致性（1h）
- [ ] 交叉检查所有文档的状态标注
- [ ] 验证实施路径映射的完整性
- [ ] 生成文档依赖关系图

---

## 5. 验收标准

### 5.1 状态标注完整性
- [ ] 所有文档顶部有明确的 `文档类型` 标注
- [ ] 目标态文档标注 `实施状态` 和 `Phase`
- [ ] As-Is 文档标注 `最后验证时间`

### 5.2 冲突消除验证
- [ ] Codex 定位在所有文档中一致
- [ ] 执行模型描述与实际代码对齐
- [ ] 子代理架构有清晰的实施路径
- [ ] autonomous/ 定位统一

### 5.3 可读性提升
- [ ] 新读者能快速区分 As-Is vs Target
- [ ] 开发者能找到当前实现的准确描述
- [ ] 架构师能理解演进路径

---

## 6. 后续维护规范

### 6.1 文档更新规则
1. **修改 As-Is 文档**：必须与代码同步更新
2. **修改 Target 文档**：必须标注 Phase 和依赖
3. **新增功能**：同时更新 As-Is 和 Target 映射

### 6.2 状态标注规范
```markdown
---
**文档类型**：As-Is / Target / Hybrid
**实施状态**：Phase X / 已实现 / 未实现
**最后验证**：YYYY-MM-DD
**依赖文档**：[列表]
---
```

### 6.3 冲突预防检查清单
- [ ] 新增执行路径时，检查是否与现有描述冲突
- [ ] 修改模块定位时，更新所有引用文档
- [ ] 弃用功能时，统一标注并清理架构图
- [ ] 升级策略时，更新所有相关文档的版本标注
