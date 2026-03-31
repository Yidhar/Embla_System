# WS11 Artifact 与证据链路

## 目标

解决 `raw_result_ref` 读后即盲与 Artifact 磁盘 DoS，构建可读、可控、可回收的证据管线。

## 任务拆解

### NGA-WS11-001 建立 Artifact 元数据模型
- type: feature
- priority: P0
- phase: M1
- owner_role: backend
- scope: artifact store schema
- inputs: `doc/12#2.4`, `doc/13#R9,R16`
- depends_on: NGA-WS10-001
- deliverables: `ref/content_type/size/ttl/created_at/fetch_hints` 元数据
- acceptance: 每个 raw_result_ref 都可查询元数据
- rollback: 旧 ref 自动映射默认元数据
- status: review

### NGA-WS11-002 实现 artifact_reader 工具（jsonpath/line_range/grep）
- type: feature
- priority: P0
- phase: M1
- owner_role: backend
- scope: new tool + registry
- inputs: `doc/12#2.3`, `doc/06#6.3`
- depends_on: NGA-WS11-001
- deliverables: artifact_reader 工具及 schema
- acceptance: 预览不足场景可通过 ref 二次定位根因
- rollback: 只读模式不影响现有执行链
- status: review

### NGA-WS11-003 在 os_bash 接入 fetch_hints 与二次读取指引
- type: feature
- priority: P0
- phase: M1
- owner_role: backend
- scope: os_bash result packager
- inputs: `doc/12#2.3`
- depends_on: NGA-WS11-002
- deliverables: `fetch_hints` 自动生成
- acceptance: 超大结构化输出返回有效检索提示
- rollback: hints 失败不影响主结果
- status: done

### NGA-WS11-004 实现 Artifact 配额与生命周期策略
- type: hardening
- priority: P0
- phase: M1
- owner_role: infra
- scope: store policy
- inputs: `doc/12#2.4`, `doc/09#10.3`, `doc/13#R16`
- depends_on: NGA-WS11-001
- deliverables: global/session/tenant quota + TTL + LRU
- acceptance: 72h 压测磁盘占用受控，无 ENOSPC 雪崩
- rollback: 先启用告警阈值，再启强制拒绝
- status: done

### NGA-WS11-005 高水位背压与关键路径保护
- type: hardening
- priority: P1
- phase: M2
- owner_role: infra
- scope: high-watermark backpressure
- inputs: `doc/12#2.4`, `doc/13#R16`
- depends_on: NGA-WS11-004
- deliverables: 高水位拒绝低优先级写入、关键数据库保护
- acceptance: 高水位时 EventBus/SQLite 仍可写
- rollback: 背压策略可临时降级为只告警
- status: done

### NGA-WS11-006 证据链可观测性（指标与审计）
- type: ops
- priority: P1
- phase: M2
- owner_role: ops
- scope: metrics/logging
- inputs: `doc/11#5.3`, `doc/13`
- depends_on: NGA-WS11-002,NGA-WS11-004
- deliverables: ref 命中率、读取延迟、回收统计看板
- acceptance: 可观测面覆盖关键指标
- rollback: 保留原日志链路
- status: done
