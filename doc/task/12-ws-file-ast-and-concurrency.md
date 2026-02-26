# WS12 file_ast 巨型文件与并发冲突治理

## 目标

消除 Monolith OOM 与 Livelock Storm，保证大文件编辑与并发修改可控。

## 任务拆解

### NGA-WS12-001 实现 file_ast_skeleton 分层读取
- type: feature
- priority: P0
- phase: M1
- owner_role: backend
- scope: file_ast read path
- inputs: `doc/12#3.4`, `doc/09#11.1`
- depends_on: NGA-WS10-001
- deliverables: imports/symbols/function_ranges 索引输出
- acceptance: >5000 行文件默认不走全量正文回读
- rollback: 保留旧 readFile 兜底开关
- status: review

### NGA-WS12-002 定向 chunk 读取能力
- type: feature
- priority: P0
- phase: M1
- owner_role: backend
- scope: chunk API
- inputs: `doc/12#3.3,#3.4`
- depends_on: NGA-WS12-001
- deliverables: `readChunkByRange` 与上下文窗口策略
- acceptance: 编辑链路只拉取目标区域与最小上下文
- rollback: 回退到只读索引模式
- status: review

### NGA-WS12-003 语义重基（semantic_rebase）
- type: hardening
- priority: P1
- phase: M2
- owner_role: backend
- scope: conflict resolver
- inputs: `doc/12#3.2`, `doc/13#R11`
- depends_on: NGA-WS12-002
- deliverables: hash 冲突时语义重基路径
- acceptance: 轻度冲突可自动合并成功
- rollback: 降级为冲突票据 +人工仲裁
- status: done

### NGA-WS12-004 冲突票据与退避机制
- type: hardening
- priority: P1
- phase: M2
- owner_role: backend
- scope: retry coordinator
- inputs: `doc/12#3.4`, `doc/09#11.1`
- depends_on: NGA-WS12-003
- deliverables: `conflict_ticket + exponential_backoff + jitter`
- acceptance: 冲突场景不出现无界重试
- rollback: 退避阈值可配置下调
- status: done

### NGA-WS12-005 Router 仲裁升级路径
- type: feature
- priority: P1
- phase: M2
- owner_role: backend
- scope: router escalation
- inputs: `doc/11#2.5`, `doc/09#11.3`
- depends_on: NGA-WS12-004
- deliverables: 达上限后自动升级 Router/HITL
- acceptance: 无预算烧穿型活锁
- rollback: 手工仲裁通道兜底
- status: done

### NGA-WS12-006 大文件与并发压测基线
- type: qa
- priority: P1
- phase: M2
- owner_role: qa
- scope: benchmark suites
- inputs: `doc/13#R10,R11`
- depends_on: NGA-WS12-001,NGA-WS12-004
- deliverables: 30k 行文件 + 并发冲突基线报告
- acceptance: token 峰值/重试次数/成功率达到阈值
- rollback: 回退到保守串行编辑策略
- status: done
