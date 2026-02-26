# WS14 Brainstem 安全与运行时守门

## 目标

把关键运行时安全控制从文档规则变成可执行守门能力，覆盖 R1-R3、R6、R14、R15。

## 任务拆解

### NGA-WS14-001 Policy Firewall 能力白名单与 argv 校验
- type: hardening
- priority: P0
- phase: M1
- owner_role: security
- scope: policy firewall
- inputs: `doc/10#4.4`, `doc/13#R1`
- depends_on: NGA-WS10-003
- deliverables: capability allowlist + argv schema
- acceptance: 混淆命令与非法参数被拒绝并审计
- rollback: 先告警后强拦截灰度
- status: review

### NGA-WS14-002 解释器入口硬门禁
- type: hardening
- priority: P0
- phase: M1
- owner_role: security
- scope: command gate
- inputs: `doc/10#4.3,#4.4`
- depends_on: NGA-WS14-001
- deliverables: `python -c / sh -c / EncodedCommand` 拦截
- acceptance: 20+ payload 回归全部拦截
- rollback: 风险审批白名单临时放行
- status: review

### NGA-WS14-003 Global Mutex TTL + Heartbeat + Fencing
- type: hardening
- priority: P0
- phase: M2
- owner_role: backend
- scope: global state mutex
- inputs: `doc/09#11.2`, `doc/10#7.3`, `doc/13#R3`
- depends_on: NGA-WS10-002
- deliverables: 锁续租、过期回收、fencing token
- acceptance: kill -9 注入后锁可自动回收
- rollback: 临时单实例串行降级
- status: done

### NGA-WS14-004 Orphan Lock 清道夫
- type: hardening
- priority: P1
- phase: M2
- owner_role: backend
- scope: lock cleanup daemon
- inputs: `doc/13#R3`
- depends_on: NGA-WS14-003
- deliverables: 启动/周期扫描 orphan lock
- acceptance: 无永久悬挂锁
- rollback: 人工清锁脚本兜底
- status: done

### NGA-WS14-005 Process Lineage 绑定与回收
- type: hardening
- priority: P0
- phase: M2
- owner_role: infra
- scope: executor runtime
- inputs: `doc/09#11.2`, `doc/13#R15`
- depends_on: NGA-WS14-003
- deliverables: `job_root_id + cgroup/container_id` 绑定
- acceptance: 旧 epoch lineage 可完整回收
- rollback: runtime API 手工回收脚本
- status: done

### NGA-WS14-006 Double-Fork 幽灵进程清理
- type: hardening
- priority: P0
- phase: M2
- owner_role: infra
- scope: detached process killer
- inputs: `doc/13#R15`
- depends_on: NGA-WS14-005
- deliverables: 对 docker -d/nohup/setsid 的递归回收
- acceptance: 切主后无幽灵进程占端口/写文件
- rollback: 切换到保守禁止 detached 策略
- status: done

### NGA-WS14-007 Sleep Watch ReDoS 防护
- type: hardening
- priority: P0
- phase: M1
- owner_role: security
- scope: sleep watch daemon
- inputs: `doc/10#7.3,#7.4`, `doc/13#R6`
- depends_on: NGA-WS10-003
- deliverables: safe-regex profile + timeout budget
- acceptance: 恶意 regex 压测不拖垮宿主
- rollback: 仅允许预定义 pattern 模式
- status: done

### NGA-WS14-008 Logrotate 容错
- type: hardening
- priority: P1
- phase: M1
- owner_role: backend
- scope: watcher reopen
- inputs: `doc/12#6`, `doc/13#R6`
- depends_on: NGA-WS14-007
- deliverables: tail -F 语义 + inode 变更重开
- acceptance: logrotate 后仍可成功唤醒
- rollback: watcher 自动重建守护任务
- status: done

### NGA-WS14-009 KillSwitch OOB 出口策略
- type: hardening
- priority: P0
- phase: M1
- owner_role: infra
- scope: kill switch
- inputs: `doc/10#5.3`, `doc/13#R14`
- depends_on: NGA-WS14-001
- deliverables: deny-non-allowlist + OOB allowlist
- acceptance: 熔断时堡垒机/SSM 通道可用
- rollback: 切回保守只告警不熔断
- status: done

### NGA-WS14-010 OOB 健康探测与恢复 runbook
- type: ops
- priority: P1
- phase: M1
- owner_role: ops
- scope: oob probes/runbook
- inputs: `doc/10#5.4`, `doc/13#R14`
- depends_on: NGA-WS14-009
- deliverables: OOB 探测任务、disarm/recover 手册
- acceptance: 故障演练可在 OOB 通道完成恢复
- rollback: 云控制台人工应急流程
- status: done
