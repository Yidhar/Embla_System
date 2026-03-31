# KillSwitch OOB 健康探测与恢复 Runbook

## 1. 适用范围
- 任务: `NGA-WS14-010`
- 场景: 需要执行网络冻结（KillSwitch freeze）且必须保留 OOB 管理通道。
- 前提: 已具备 sudo/root 权限；已确认 `oob_allowlist`（CIDR/host）来自运维白名单。

## 2. 触发条件
满足任一项时进入本 Runbook：
1. 检测到异常外联/数据外发风险，需紧急冻结 egress。
2. 人工触发 KillSwitch 演练（故障恢复演习）。
3. 安全策略要求临时收敛出口，仅保留 OOB 运维面。

## 3. 执行前准备
1. 记录变更窗口和操作者（值班人、工单号、开始时间）。
2. 备份当前防火墙规则：
   ```bash
   iptables-save > /var/tmp/killswitch.before.rules
   ```
3. 明确 OOB allowlist 与 probe targets（建议 probe targets 为可直连主机/IP，而不是大网段）：
   - `oob_allowlist`: `10.0.0.0/24,bastion.example.com`
   - `probe_targets`: `10.0.0.10,bastion.example.com`

## 4. 生成并校验计划（freeze + probe）
在目标主机执行：

```bash
python3 - <<'PY'
from system.killswitch_guard import (
    build_oob_killswitch_plan,
    build_oob_health_probe_plan,
    validate_oob_health_probe_plan,
)

allowlist = ["10.0.0.0/24", "bastion.example.com"]
probe_targets = ["10.0.0.10", "bastion.example.com"]

freeze_plan = build_oob_killswitch_plan(oob_allowlist=allowlist, dns_allow=True)
probe_plan = build_oob_health_probe_plan(
    oob_allowlist=allowlist,
    probe_targets=probe_targets,
    tcp_port=22,
    ping_timeout_seconds=2,
)
ok, reason = validate_oob_health_probe_plan(
    oob_allowlist=allowlist,
    probe_targets=probe_targets,
    commands=probe_plan.commands,
)

if not ok:
    raise SystemExit(f"probe plan invalid: {reason}")

print("=== FREEZE PLAN ===")
print("\n".join(freeze_plan.commands))
print("\n=== PROBE PLAN ===")
print("\n".join(probe_plan.commands))
PY
```

验收标准：
1. `validate_oob_health_probe_plan` 返回 `ok`。
2. 输出命令包含 marker `OOB_ALLOWLIST_ENFORCED`。

## 5. 探测（熔断前）
先执行 probe plan，确认 OOB 通道当前可达：

```bash
# 仅示例：请替换为上一阶段生成的 probe 命令
iptables -C OUTPUT -d 10.0.0.10 -j ACCEPT # OOB_ALLOWLIST_ENFORCED
iptables -C INPUT -s 10.0.0.10 -j ACCEPT # OOB_ALLOWLIST_ENFORCED
ping -c 1 -W 2 10.0.0.10
nc -z -w 2 10.0.0.10 22
```

若任一关键 OOB 目标探测失败，禁止进入 freeze，先修正 allowlist/probe target。

## 6. 触发冻结（freeze）
按生成顺序执行 freeze plan 命令。执行后立即再次运行 probe plan（第 7 节）。

```bash
# 仅示例：请替换为上一阶段生成的 freeze 命令
iptables -P OUTPUT DROP
iptables -P INPUT DROP
iptables -A INPUT -i lo -j ACCEPT
iptables -A OUTPUT -o lo -j ACCEPT
iptables -A OUTPUT -p udp --dport 53 -j ACCEPT
iptables -A OUTPUT -p tcp --dport 53 -j ACCEPT
iptables -A OUTPUT -d 10.0.0.0/24 -j ACCEPT
iptables -A INPUT -s 10.0.0.0/24 -j ACCEPT
```

## 7. 探测（熔断后）
再次执行 probe plan：
1. 规则检查必须通过（`iptables -C` 不报错）。
2. 至少一个 OOB 管理目标 `ping + nc` 成功。

若失败，立即执行第 9 节回滚流程。

## 8. Disarm / Recover

### 8.1 Disarm（紧急解除）
当 OOB 通道异常、误触发或演练结束时：

```bash
iptables -P INPUT ACCEPT
iptables -P OUTPUT ACCEPT
iptables -F INPUT
iptables -F OUTPUT
```

### 8.2 Recover（恢复）
1. 恢复到 freeze 前规则（推荐）：
   ```bash
   iptables-restore < /var/tmp/killswitch.before.rules
   ```
2. 再次验证管理面可达：
   ```bash
   ping -c 1 -W 2 bastion.example.com
   nc -z -w 2 bastion.example.com 22
   ```
3. 记录恢复完成时间、执行人、验证输出。

## 9. 回滚策略（失败分支）
触发条件：
1. freeze 后 OOB 探测失败。
2. 规则应用出现不可预期副作用（SSH/SSM 失联风险）。

回滚步骤：
1. 立即执行 `Disarm`（第 8.1 节）。
2. 执行 `iptables-restore < /var/tmp/killswitch.before.rules`。
3. 若仍失败，走云控制台/带外串口等人工应急通道。
4. 保留证据并升级事件：freeze 命令、probe 输出、回滚时间线。

## 10. 证据留存（验收）
至少保留以下证据：
1. 生成的 freeze/probe 命令文本（含 marker）。
2. 熔断前后 probe 输出。
3. disarm/recover 或 rollback 的执行日志。
4. 工单链接与事件时间线。
