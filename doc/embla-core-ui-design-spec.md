# Embla_core UI 视觉规范（Zen-iOS Hybrid）

文档状态：强约束设计规范（实施版）  
创建时间：2026-02-25  
最后更新：2026-02-25  
适用工程：`Embla_core`（Next.js）

---

## 1. 角色与目标

Role：顶级 UI 视觉专家，采用 `Zen-iOS Hybrid` 设计语言。  
Core Objective：消除界面模糊感，通过物理边框、内阴影和层级叠放，创造“柔和但边界清晰”的专业级 UI。

该文档是实现约束，不是视觉建议。

### 1.1 信息层级硬约束（新增）

1. 首页主视觉必须服务于 `Runtime + MCP + Memory + Workflow`。
2. 发布相关内容只允许出现在次级 `Evidence` 区域。
3. `Release countdown` 不得占据 hero 区、首屏第一行或最大卡片位。
4. `ChatOps` 必须视觉后置，明确标识为沟通通道。

---

## 2. 核心视觉基调

### 2.1 底色规范（Base Layer）

1. 禁止纯白作为全局底色。
2. 全局底色仅允许：
- `#F2F2F7`（iOS 系统级灰）
- `#F9F9FB`（冷灰）

推荐：
- 默认浅色模式使用 `#F2F2F7`。
- 内容区域可在 `#F9F9FB` 与 `#F2F2F7` 间切换制造分层。

### 2.2 对比策略（Contrast Rule）

1. 任何按钮或交互组件背景必须比父容器深或浅 `3%-10%`。
2. 优先使用微色阶差异，不依赖粗重描边。
3. 文字与背景最低对比度建议 `4.5:1`（正文），关键数据建议 `7:1`。

---

## 3. 材质与物理质感

### 3.1 极致毛玻璃（Frosted Glass）

层级容器必须满足：

1. `backdrop-blur-[40px]` 到 `backdrop-blur-[60px]`。
2. 半透明填充：`bg-white/40` 到 `bg-white/60`。
3. 同层级不能出现“无 blur 的透明白块”替代毛玻璃。

### 3.2 双层物理描边（Dual-Stroke）

所有核心容器使用双描边：

1. 内描边：`1px border-white/60`（模拟玻璃切面捕光）。
2. 外描边：`1px border-gray-200/40`（定义空间轮廓）。

实现建议：
- 主描边用于容器本体。
- 次描边可由伪元素 `::before` 或叠层壳体实现。

### 3.3 深度反馈（Depth & Shadow）

悬浮组件（卡片、弹层）：

- `shadow-[0_24px_48px_-12px_rgba(0,0,0,0.08)]`

凹陷组件（输入槽、切换器槽）：

- `shadow-inner`
- `bg-gray-100/50`

禁止：
- 硬边强阴影（例如 `shadow-2xl` 黑重投影）
- 纯平白块 + 强线框的低级拟态

---

## 4. 按钮与交互件规范

### 4.1 高对比交互（High-Contrast Action）

1. 主按钮：
- 背景 `#1C1C1E`（深空黑）或近似石墨色。
- 文本使用高亮白。

2. 次级按钮：
- 纯白微透明块（如 `bg-white/85`）。
- 搭配轻投影和双描边。

### 4.2 触觉感（Tactile Feedback）

所有可点击元素必须具备按压反馈：

1. `active:scale-95` 或 `active:scale-[0.98]`。
2. Hover 状态增加以下之一：
- `backdrop-blur-3xl`
- 边框亮度轻微抬升（如 `border-white/70`）

### 4.3 圆角美学（Curvature）

圆角标准：

1. 大容器：`rounded-[40px]` 到 `rounded-[50px]`
2. 功能块：`rounded-[28px]`
3. 小组件：`rounded-xl`

禁止同页混乱曲率。

---

## 5. 模块化布局逻辑

### 5.1 层级堆叠（Layering）

1. 界面应呈现“多层有机玻璃板”堆叠。
2. 通过阴影深度和 blur 强度区分优先级。
3. 主看板层级建议：
- L0：全局底层
- L1：页面壳层
- L2：功能板层
- L3：弹出层

### 5.2 呼吸感排版（Whitespace）

1. 强制大间距。
2. 容器内边距最小 `p-6`，推荐 `p-8`。
3. 卡片之间垂直间距建议 `gap-6` 到 `gap-8`。

目标：信息密度高但不压迫。

---

## 6. 字体与细节

### 6.1 字体

1. 主字体：`Inter`。
2. Apple 设备优先 fallback：`SF Pro Display`。
3. 推荐字体栈：
`Inter, "SF Pro Display", "Helvetica Neue", Arial, sans-serif`

### 6.2 排版

1. 标题：`font-extrabold + tracking-tight`
2. 次级标签：
- `uppercase`
- `tracking-widest`
- `font-bold`
- `text-[10px]`

### 6.3 图标

1. 统一使用 `Lucide React`。
2. 线宽固定为 `1.5` 或 `2`。
3. 默认图标颜色：`gray-500` 或接近黑灰。

---

## 7. 设计令牌（Design Tokens）

建议在 `Embla_core/styles/tokens.css` 定义：

```css
:root {
  --embla-bg-base: #f2f2f7;
  --embla-bg-cool: #f9f9fb;
  --embla-text-primary: #1c1c1e;
  --embla-text-secondary: #3a3a3c;
  --embla-text-muted: #6b7280;

  --embla-glass-fill: rgba(255, 255, 255, 0.5);
  --embla-stroke-inner: rgba(255, 255, 255, 0.6);
  --embla-stroke-outer: rgba(209, 213, 219, 0.4);

  --embla-shadow-float: 0 24px 48px -12px rgba(0, 0, 0, 0.08);
  --embla-shadow-inset: inset 0 2px 6px rgba(0, 0, 0, 0.08);

  --embla-radius-panel: 48px;
  --embla-radius-card: 28px;
  --embla-radius-chip: 12px;
}
```

---

## 8. 组件级样式模板

### 8.1 页面壳层（Shell）

```tsx
<div className="min-h-screen bg-[#F2F2F7] p-8">
  <main className="rounded-[48px] border border-white/60 bg-white/50 backdrop-blur-[50px] shadow-[0_24px_48px_-12px_rgba(0,0,0,0.08)]" />
</div>
```

### 8.2 看板卡片（Metric Card）

```tsx
<section className="rounded-[28px] border border-gray-200/40 bg-white/55 backdrop-blur-[45px] p-6 shadow-[0_24px_48px_-12px_rgba(0,0,0,0.08)]">
  <p className="text-[10px] font-bold uppercase tracking-widest text-gray-500">Runtime Lease</p>
  <h3 className="mt-2 text-2xl font-extrabold tracking-tight text-[#1C1C1E]">HEALTHY</h3>
</section>
```

### 8.3 主按钮（Primary Action）

```tsx
<button className="rounded-xl bg-[#1C1C1E] px-5 py-3 text-sm font-bold text-white shadow-[0_10px_24px_-10px_rgba(0,0,0,0.45)] transition active:scale-[0.98] hover:brightness-110">
  Trigger Check
</button>
```

### 8.4 凹陷输入槽（Inset Input）

```tsx
<div className="rounded-[20px] bg-gray-100/50 p-2 shadow-inner">
  <input className="h-11 w-full rounded-xl border border-white/60 bg-white/70 px-4 text-sm text-[#1C1C1E] outline-none" />
</div>
```

---

## 9. 页面级布局约束

### 9.1 Runtime Posture（首页）

1. 顶部核心指标卡优先展示 rollout/fail-open/lease/queue/lock/disk。
2. 中部趋势图必须保留错误率与延迟两条核心曲线。
3. 首屏不得出现发布倒计时主卡。

### 9.2 MCP Fabric

1. 来源分组（builtin/mcporter/isolated/rejected）必须同屏可见。
2. 不可把“服务数量”替代“可用性状态”，必须同时展示。
3. 降级或不可用服务必须有明显状态芯片与原因摘要。

### 9.3 Memory Graph

1. 图谱画布与统计栏并排，不允许只有图不显示数字。
2. 关系边颜色保持克制，避免干扰节点可读性。
3. 搜索结果要有数量与耗时反馈。

### 9.4 Workflow & Events

1. Outbox 积压卡片与事件时间线需同屏，防止只看单一指标。
2. 关键事件（fail-open/lease-lost）采用高对比告警色。
3. 日志上下文区与工具状态区分层展示，避免信息混叠。

### 9.5 Incidents

1. 最近演练结论放在页首，历史列表放后。
2. 失败 case 必须带修复入口（runbook link 或命令片段）。

### 9.6 Evidence（次级）

1. 发布/签署/72h 验收只在该页展示，不前置到首页。
2. 失败证据优先排序，路径列必须可复制。

### 9.7 ChatOps（次级）

1. 页面头部需标注“沟通通道（非主态势页）”。
2. 工具流事件展示优先于闲聊装饰。

---

## 10. 响应式规则

1. `>=1536px`：四栏密集看板。
2. `>=1280px`：三栏主布局。
3. `>=1024px`：双栏布局。
4. `<1024px`：单栏堆叠，保证数据可读优先。
5. 移动端保留玻璃与边框逻辑，但 blur 可降到 `40px` 以控制性能。

---

## 11. 动效与交互节奏

1. 过渡时长：`120ms` 到 `220ms`。
2. 默认缓动：`cubic-bezier(0.2, 0.8, 0.2, 1)`。
3. 状态变更（healthy/warning/critical）必须有轻微颜色过渡。
4. 严禁炫技型长动画影响读数判断。

---

## 12. 禁止项（Red Lines）

1. 全局纯白背景。
2. 大量扁平块无层次。
3. 仅靠粗线条做边界。
4. 按钮无按压反馈。
5. 图标混用不同风格库。
6. 聊天页抢占首页地位。
7. 发布倒计时占据首屏主视觉。

---

## 13. 实施检查清单（开发前）

1. 是否已引入 `Inter` + `SF Pro Display` fallback。
2. 是否全局启用底色 `#F2F2F7`/`#F9F9FB`。
3. 是否建立 `tokens.css` 与可复用玻璃容器类。
4. 是否固定首页为 `Runtime Posture`。
5. 是否将 `MCP Fabric`、`Memory Graph`、`Workflow & Events` 设为一级主域。
6. 是否确认发布内容仅位于 `Evidence` 次级域。
