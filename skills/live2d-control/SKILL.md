---
name: live2d-control
description: 控制 Live2D 虚拟形象的表情和动作。当 AI 回复表达肯定/同意时触发点头动画，表达否定/拒绝时触发摇头动画。用于增强虚拟形象的情感表达。
version: 1.0.0
author: Naga Team
tags:
  - live2d
  - animation
  - expression
enabled: true
---

# Live2D 动作控制技能

本技能通过 `agentType: "live2d"` 调度虚拟形象 Naga 的表情和肢体动作。

## 可用动作

| 动作名 | 说明 | 触发场景 |
|--------|------|----------|
| `nod`  | 点头 | AI 表达肯定、同意、确认时 |
| `shake`| 摇头 | AI 表达否定、拒绝、不同意时 |

## 调用格式

```json
{
  "agentType": "live2d",
  "action": "nod"
}
```

## 触发规则

- 当 AI 回复内容表达 **肯定/同意/确认**（如"好的"、"没问题"、"可以"、"对"）→ 输出 `nod`
- 当 AI 回复内容表达 **否定/拒绝/不同意**（如"不行"、"不可以"、"抱歉做不到"）→ 输出 `shake`
- 可以与其他 agentType（如 openclaw）的调用同时存在，作为 JSON 数组的一个元素
- 普通回复不需要触发动作，仅在明确的肯定/否定语义时使用
