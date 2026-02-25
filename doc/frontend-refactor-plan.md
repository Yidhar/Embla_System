 全新 Web 前端设计方案

 文档状态：核心架构与视觉设计方案（最终版）
 创建时间：2026-02-25
 最后更新：2026-02-25
 目标：设计一个全新的纯 Web 前端，融合 Perplexity 交互模式与 Zen-iOS Hybrid 视觉语言

 用户需求确认：
 - ✅ 技术栈：React + Tailwind CSS + Ant Design（降级为底层支撑）
 - ✅ 设计风格：Perplexity 搜索引擎风格 + Zen-iOS Hybrid 物理触感
 - ✅ 核心功能：聊天对话、工具管理、记忆图谱、移动端适配
 - ✅ 部署方式：局域网访问
 - ✅ 特别关注：记忆图谱和五元组展示（后端已重构）
 - ✅ 视觉升级：毛玻璃效果、双层物理描边、触觉反馈、工业级微排版

 ---
 背景与上下文

 为什么需要全新 Web 前端？

 1. 现有系统局限：
   - Electron 客户端依赖桌面环境，无法跨平台访问
   - Live2D 渲染和悬浮球模式增加复杂度
   - 缺乏现代化的 UI/UX 设计
 2. 用户需求：
   - 需要纯浏览器访问的 Web 应用
   - 局域网内多设备访问（桌面/平板/手机）
   - 参考 Perplexity 的搜索引擎式交互
   - 专业级记忆图谱可视化（后端已重构为五元组模型）
 3. 设计升级：
   - 引入 Zen-iOS Hybrid 设计语言
   - 物理触感、毛玻璃效果、双层描边
   - 高对比度冷灰调、工业级微排版

 ---
 1. 核心定位

 1.1 产品定位

 全新独立 Web 应用：
 - 🌐 纯浏览器访问，无需安装客户端
 - 📱 响应式设计，支持桌面 + 平板 + 移动端
 - ⚡ 现代化 UI/UX，对标 ChatGPT/Claude Web
 - 🔌 通过 HTTP API 连接后端服务（apiserver:8000）

 1.2 与现有系统的关系

 ┌─────────────────────────────────────────┐
 │  现有系统（保留）                        │
 │  ├─ Electron 客户端（桌面应用）          │
 │  ├─ PyQt5 GUI（备选方案）                │
 │  └─ Live2D 渲染 + 悬浮球模式             │
 └─────────────────────────────────────────┘
                     ↓
             共享后端 API
                     ↓
 ┌─────────────────────────────────────────┐
 │  全新 Web 前端（本次设计）               │
 │  ├─ 纯浏览器访问（http://localhost:3000）│
 │  ├─ 现代化 UI（类 ChatGPT）              │
 │  ├─ 响应式布局（桌面/移动）              │
 │  └─ 独立部署（Nginx/Vercel）             │
 └─────────────────────────────────────────┘

 关键差异：
 - ❌ 不依赖 Electron
 - ❌ 不包含 Live2D 渲染
 - ❌ 不包含悬浮球模式
 - ✅ 纯 Web 技术栈
 - ✅ 可独立部署
 - ✅ 跨平台访问

 ---
 2. 技术架构

 2.1 技术栈选型（Zen-iOS Hybrid 升级版）

 前端框架：
 - next.js


 样式方案（组合拳）：
 - Tailwind CSS 4 原子化样式（主力）- 精密控制物理级样式、阴影、圆角
 - Ant Design 5.x 降级为底层支撑 - 仅用于 Modal、Drawer、Message 等复杂逻辑组件
 - 自定义 CSS 毛玻璃效果、双层描边、触觉反馈动画

 图标与可视化：
 - Lucide-React 统一图标库（替换 Ant Design Icons）- 保证线条风格统一（1.5/2px）
 - G6 5.x 蚂蚁图可视化引擎（记忆图谱）
 - Canvas 渲染 性能优化

 数据通信（关键升级）：
 - @microsoft/fetch-event-source 替代原生 EventSource - 支持 POST 请求和自定义 Header
 - Axios HTTP 客户端
 - WebSocket（可选，用于实时语音）

 开发工具：
 - ESLint + Prettier 代码规范
 - Jest 单元测试
 - React Testing Library 组件测试

 2.2 项目结构（React + Ant Design）

 naga-web/                        # 全新项目根目录
 ├── public/                      # 静态资源
 │   ├── favicon.ico
 │   └── robots.txt
 ├── src/
 │   ├── main.tsx                 # 应用入口
 │   ├── App.tsx                  # 根组件
 │   ├── router/                  # 路由配置
 │   │   └── index.tsx
 │   ├── stores/                  # Zustand 状态管理
 │   │   ├── useChatStore.ts      # 聊天状态
 │   │   ├── useToolsStore.ts     # 工具状态
 │   │   ├── useMemoryStore.ts    # 记忆状态
 │   │   └── useConfigStore.ts    # 配置状态
 │   ├── pages/                   # 页面视图
 │   │   ├── ChatPage.tsx         # 聊天主界面
 │   │   ├── ToolsPage.tsx        # 工具管理
 │   │   ├── MemoryPage.tsx       # 记忆图谱（重点）
 │   │   └── SettingsPage.tsx     # 设置页
 │   ├── components/              # 组件库
 │   │   ├── layout/              # 布局组件
 │   │   │   ├── AppLayout.tsx    # 主布局
 │   │   │   ├── AppHeader.tsx    # 顶部导航
 │   │   │   └── AppSidebar.tsx   # 侧边栏
 │   │   ├── chat/                # 聊天组件
 │   │   │   ├── MessageList.tsx
 │   │   │   ├── MessageItem.tsx
 │   │   │   ├── MessageInput.tsx
 │   │   │   ├── ToolCallCard.tsx
 │   │   │   └── StreamingText.tsx
 │   │   ├── tools/               # 工具组件
 │   │   │   ├── ToolCard.tsx
 │   │   │   ├── ToolStatusBadge.tsx
 │   │   │   └── ToolConfigModal.tsx
 │   │   ├── memory/              # 记忆组件（重点）
 │   │   │   ├── KnowledgeGraph.tsx      # G6 图谱主组件
 │   │   │   ├── GraphToolbar.tsx        # 图谱工具栏
 │   │   │   ├── GraphFilters.tsx        # 过滤器面板
 │   │   │   ├── EntityDetailDrawer.tsx  # 实体详情抽屉
 │   │   │   ├── QuintupleList.tsx       # 五元组列表
 │   │   │   ├── QuintupleCard.tsx       # 五元组卡片
 │   │   │   └── MemoryStats.tsx         # 统计面板
 │   │   └── common/              # 通用组件
 │   │       ├── LoadingSpinner.tsx
 │   │       ├── ErrorBoundary.tsx
 │   │       └── EmptyState.tsx
 │   ├── hooks/                   # 自定义 Hooks
 │   │   ├── useChat.ts           # 聊天逻辑
 │   │   ├── useSSE.ts            # SSE 流式处理
 │   │   ├── useTools.ts          # 工具管理
 │   │   ├── useMemoryGraph.ts    # 记忆图谱逻辑（重点）
 │   │   └── useQuintuples.ts     # 五元组查询
 │   ├── api/                     # API 客户端
 │   │   ├── client.ts            # Axios 实例
 │   │   ├── chat.ts              # 聊天 API
 │   │   ├── tools.ts             # 工具 API
 │   │   ├── memory.ts            # 记忆 API（重点）
 │   │   └── config.ts            # 配置 API
 │   ├── types/                   # TypeScript 类型
 │   │   ├── chat.ts
 │   │   ├── tools.ts
 │   │   ├── memory.ts            # 记忆类型定义（重点）
 │   │   └── api.ts
 │   ├── utils/                   # 工具函数
 │   │   ├── format.ts            # 格式化工具
 │   │   ├── markdown.ts          # Markdown 渲染
 │   │   ├── graphLayout.ts       # 图谱布局算法
 │   │   └── storage.ts           # 本地存储
 │   └── styles/                  # 样式文件
 │       ├── global.css           # 全局样式
 │       └── antd-theme.ts        # Ant Design 主题配置
 ├── tests/                       # 测试文件
 │   ├── unit/
 │   └── integration/
 ├── .env.development             # 开发环境配置
 ├── .env.production              # 生产环境配置
 ├── index.html                   # HTML 入口
 ├── vite.config.ts               # Vite 配置
 ├── tsconfig.json                # TypeScript 配置
 └── package.json                 # 依赖配置

 ---
 3. 核心界面设计（参考 Perplexity 风格）

 3.1 整体布局（搜索引擎风格 + 引用来源可视化）

 ┌─────────────────────────────────────────────────────────┐
 │  🐉 NagaAgent          [搜索框]      [🔧] [🧠] [⚙️]    │  ← Header (固定)
 ├─────────────────────────────────────────────────────────┤
 │                                                         │
 │  ┌─────────────────────────────────────────────────┐   │
 │  │  User: 帮我分析 Python 代码的性能问题           │   │
 │  └─────────────────────────────────────────────────┘   │
 │                                                         │
 │  ┌─ 来源 ─────────────────────────────────────────┐   │
 │  │  [1] read_file: main.py                        │   │
 │  │  [2] search_docs: Python profiling             │   │
 │  │  [3] memory: 用户偏好使用 cProfile              │   │
 │  └────────────────────────────────────────────────┘   │
 │                                                         │
 │  Assistant: 根据代码分析[1]和你的偏好[3]，建议...     │
 │                                                         │
 │  ┌─ 工具调用详情 ─────────────────────────────────┐   │
 │  │  🔧 read_file                                  │   │
 │  │  ├─ Input: { "path": "main.py" }              │   │
 │  │  └─ Output: [展开查看 200 行代码]              │   │
 │  └────────────────────────────────────────────────┘   │
 │                                                         │
 │  [相关问题] [导出对话] [分享]                          │
 │                                                         │
 └─────────────────────────────────────────────────────────┘

 Perplexity 风格特点：
 - ✅ 顶部搜索框（全局快速访问）
 - ✅ 引用来源编号（[1][2][3]）
 - ✅ 来源卡片展示（工具调用 + 记忆检索）
 - ✅ 相关问题推荐
 - ✅ 简洁的卡片式布局

 响应式适配：
 - 桌面（>1024px）：全宽布局，最大宽度 1200px 居中
 - 平板（768-1024px）：自适应宽度，侧边距 24px
 - 移动（<768px）：全屏布局，侧边距 16px

 3.2 聊天界面（ChatPage）- Perplexity 风格

 核心功能：
 1. 消息流展示（卡片式布局）
   - 用户问题（白色卡片，左对齐）
   - AI 回答（灰色卡片，全宽）
   - 引用来源（蓝色标签 [1][2][3]）
   - 流式打字效果
 2. 来源卡片（Sources Card）
 ┌─ 来源 ─────────────────────────────────────┐
 │  [1] 🔧 read_file: main.py                 │
 │      └─ 200 行 Python 代码                 │
 │  [2] 🔍 search_docs: Python profiling      │
 │      └─ 5 个搜索结果                       │
 │  [3] 🧠 memory: 用户偏好 cProfile          │
 │      └─ 五元组: (用户, 喜欢, cProfile, 工具)│
 └────────────────────────────────────────────┘
 3. 工具调用详情（可折叠）
 ┌─ 工具调用详情 ─────────────────────────────┐
 │  🔧 read_file                              │
 │  ├─ Status: ✅ Success (0.3s)              │
 │  ├─ Input: { "path": "main.py" }          │
 │  └─ Output: [展开查看 200 行]              │
 │                                            │
 │  🔍 search_docs                            │
 │  ├─ Status: ✅ Success (1.2s)              │
 │  ├─ Input: { "query": "Python profiling" }│
 │  └─ Output: [展开查看 5 个结果]            │
 └────────────────────────────────────────────┘
 4. 输入区域（底部固定）
   - 大号搜索框（Perplexity 风格）
   - 占位符："Ask anything..."
   - 文件上传按钮（📎）
   - 发送按钮（Enter 发送，Shift+Enter 换行）
 5. 相关问题推荐
   - AI 自动生成 3-5 个相关问题
   - 点击直接发送
   - 帮助用户深入探索

 3.3 工具管理界面（ToolsView）

 ┌─────────────────────────────────────────────────────────┐
 │  工具注册表                          [搜索...] [+ 添加]  │
 ├─────────────────────────────────────────────────────────┤
 │  ┌─────────────────┐  ┌─────────────────┐              │
 │  │ 🌤️ weather_time │  │ 🚀 open_launcher│
 │  │ 天气与时间查询  │  │ 应用启动器      │              │
 │  │ ✅ 已启用       │  │ ✅ 已启用       │              │
 │  │ [配置] [禁用]   │  │ [配置] [禁用]   │              │
 │  └─────────────────┘  └─────────────────┘              │
 │                                                         │
 │  ┌─────────────────┐  ┌─────────────────┐              │
 │  │ 🎮 game_guide   │  │ 🔍 online_search│              │
 │  │ 游戏攻略助手    │  │ 在线搜索        │              │
 │  │ ✅ 已启用       │  │ ⚠️  配置缺失    │              │
 │  │ [配置] [禁用]   │  │ [配置] [启用]   │              │
 │  └─────────────────┘  └─────────────────┘              │
 └─────────────────────────────────────────────────────────┘

 功能特性：
 - 工具卡片展示（图标 + 名称 + 描述 + 状态）
 - 状态指示器（✅ 健康 / ⚠️ 警告 / ❌ 错误）
 - 快速启用/禁用
 - 配置面板（Modal 弹窗）
 - 搜索过滤
 - 分类筛选

 3.4 记忆图谱界面（MemoryPage）- 重点设计

 基于后端重构的数据模型：
 - 五元组格式：(subject, subject_type, predicate, object, object_type)
 - 实体类型：人物、地点、组织、物品、概念、时间、事件、活动
 - 存储：JSON 文件 + Neo4j 图数据库
 - API：/memory/stats、/memory/quintuples、/memory/quintuples/search

 界面布局：
 ┌─────────────────────────────────────────────────────────┐
 │  🧠 记忆图谱                    [搜索] [导出] [刷新]    │
 ├──────────┬──────────────────────────────────────────────┤
 │  统计面板│  知识图谱可视化（G6 力导向图）               │
 │          │  ┌────────────────────────────────────────┐  │
 │  📊 总览 │  │                                        │  │
 │  ├ 实体  │  │         ●───喜欢───●                   │  │
 │  │ 42个 │  │        /           \                   │  │
 │  ├ 关系  │  │   用户●             ●编程              │  │
 │  │ 68条 │  │        \           /                   │  │
 │  └ 五元组│  │         ●───使用───●                   │  │
 │    156个 │  │                                        │  │
 │          │  │    [点击节点查看详情]                  │  │
 │  过滤器  │  └────────────────────────────────────────┘  │
 │          │                                              │
 │  实体类型│  ┌─ 五元组列表 ─────────────────────────┐  │
 │  ☑ 人物  │  │                                      │  │
 │  ☑ 地点  │  │  (用户, 人物, 喜欢, 编程, 活动)      │  │
 │  ☑ 组织  │  │  └─ 来源: 2024-02-25 对话            │  │
 │  ☐ 物品  │  │                                      │  │
 │  ☐ 概念  │  │  (用户, 人物, 位于, 北京, 地点)      │  │
 │          │  │  └─ 来源: 2024-02-20 对话            │  │
 │  关系类型│  │                                      │  │
 │  ☑ 喜欢  │  │  (用户, 人物, 使用, Python, 工具)    │  │
 │  ☑ 位于  │  │  └─ 来源: 2024-02-18 对话            │  │
 │  ☐ 拥有  │  │                                      │  │
 │          │  │  [加载更多]                          │  │
 │  时间范围│  └──────────────────────────────────────┘  │
 │  [最近7天]│                                              │
 └──────────┴──────────────────────────────────────────────┘

 技术实现（G6 图可视化引擎）：

 1. G6 配置
 const graph = new G6.Graph({
   container: 'graph-container',
   width: 800,
   height: 600,
   layout: {
     type: 'force',  // 力导向布局
     preventOverlap: true,
     nodeStrength: -30,
     edgeStrength: 0.1,
   },
   modes: {
     default: ['drag-canvas', 'zoom-canvas', 'drag-node'],
   },
   defaultNode: {
     size: 30,
     style: {
       fill: '#5B8FF9',
       stroke: '#fff',
       lineWidth: 2,
     },
     labelCfg: {
       position: 'bottom',
       style: { fill: '#000' },
     },
   },
   defaultEdge: {
     style: {
       stroke: '#e2e2e2',
       lineWidth: 2,
     },
     labelCfg: {
       autoRotate: true,
       style: { fill: '#666' },
     },
   },
 })
 2. 数据转换（五元组 → G6 格式）
 interface Quintuple {
   subject: string
   subject_type: string
   predicate: string
   object: string
   object_type: string
 }

 function quintuplesToG6Data(quintuples: Quintuple[]) {
   const nodes = new Map<string, any>()
   const edges: any[] = []

   quintuples.forEach((q, index) => {
     // 添加主体节点
     if (!nodes.has(q.subject)) {
       nodes.set(q.subject, {
         id: q.subject,
         label: q.subject,
         type: q.subject_type,
         style: { fill: getColorByType(q.subject_type) },
       })
     }

     // 添加客体节点
     if (!nodes.has(q.object)) {
       nodes.set(q.object, {
         id: q.object,
         label: q.object,
         type: q.object_type,
         style: { fill: getColorByType(q.object_type) },
       })
     }

     // 添加关系边
     edges.push({
       id: `edge-${index}`,
       source: q.subject,
       target: q.object,
       label: q.predicate,
     })
   })

   return {
     nodes: Array.from(nodes.values()),
     edges,
   }
 }
 3. 实体类型颜色映射
 const entityColors = {
   人物: '#5B8FF9',    // 蓝色
   地点: '#5AD8A6',    // 绿色
   组织: '#5D7092',    // 灰蓝
   物品: '#F6BD16',    // 黄色
   概念: '#E86452',    // 红色
   时间: '#6DC8EC',    // 浅蓝
   事件: '#945FB9',    // 紫色
   活动: '#FF9845',    // 橙色
 }
 4. 交互功能
   - 节点点击：显示实体详情抽屉（Ant Design Drawer）
   - 节点拖拽：调整布局
   - 边悬停：高亮关系路径
   - 画布缩放：鼠标滚轮
   - 画布拖拽：鼠标拖动
 5. 性能优化
   - 节点数量限制：默认显示 100 个节点
   - 虚拟化渲染：大规模数据分页加载
   - Canvas 渲染：比 SVG 性能更好
   - 防抖搜索：避免频繁 API 请求

 五元组列表组件：
 interface QuintupleCardProps {
   quintuple: Quintuple
   source?: string  // 来源对话
   timestamp?: string
 }

 const QuintupleCard: React.FC<QuintupleCardProps> = ({ quintuple, source, timestamp }) => {
   return (
     <Card size="small" style={{ marginBottom: 8 }}>
       <Space>
         <Tag color="blue">{quintuple.subject_type}</Tag>
         <Text strong>{quintuple.subject}</Text>
         <Text type="secondary">{quintuple.predicate}</Text>
         <Text strong>{quintuple.object}</Text>
         <Tag color="green">{quintuple.object_type}</Tag>
       </Space>
       {source && (
         <Text type="secondary" style={{ fontSize: 12 }}>
           来源: {source} · {timestamp}
         </Text>
       )}
     </Card>
   )
 }

 API 集成：
 // api/memory.ts
 export const memoryApi = {
   // 获取统计信息
   async getStats() {
     const res = await client.get('/memory/stats')
     return res.data.memory_stats
   },

   // 获取所有五元组
   async getQuintuples(limit = 100, offset = 0) {
     const res = await client.get('/memory/quintuples', {
       params: { limit, offset },
     })
     return res.data
   },

   // 搜索五元组
   async searchQuintuples(keywords: string[]) {
     const res = await client.get('/memory/quintuples/search', {
       params: { keywords: keywords.join(',') },
     })
     return res.data
   },
 }

 3.5 设置界面（SettingsView）

 ┌─────────────────────────────────────────────────────────┐
 │  设置                                                    │
 ├─────────────────────────────────────────────────────────┤
 │  ┌─ 模型配置 ─────────────────────────────────────────┐ │
 │  │  API Key:     [••••••••••••••••••]                 │ │
 │  │  Base URL:    [https://api.deepseek.com/v1]       │ │
 │  │  Model:       [deepseek-v3.2 ▼]                   │ │
 │  │  Temperature: [0.7] ━━━━●━━━━━━                   │ │
 │  │  Max Tokens:  [8192]                               │ │
 │  └────────────────────────────────────────────────────┘ │
 │                                                         │
 │  ┌─ 记忆服务 ─────────────────────────────────────────┐ │
 │  │  启用 GRAG:   [✓]                                  │ │
 │  │  Neo4j URI:   [neo4j://127.0.0.1:7687]            │ │
 │  │  用户名:      [neo4j]                              │ │
 │  │  密码:        [••••••••]                           │ │
 │  └────────────────────────────────────────────────────┘ │
 │                                                         │
 │  ┌─ 界面设置 ─────────────────────────────────────────┐ │
 │  │  主题:        [● 深色  ○ 浅色  ○ 自动]            │ │
 │  │  语言:        [简体中文 ▼]                         │ │
 │  │  字体大小:    [中 ▼]                               │ │
 │  └────────────────────────────────────────────────────┘ │
 │                                                         │
 │  [保存设置]  [重置为默认]                               │
 └─────────────────────────────────────────────────────────┘

 ---
 4. 核心功能实现（React + Ant Design）

 4.1 SSE 流式消息处理（关键重构）

 为什么必须使用 @microsoft/fetch-event-source：
 - 原生 EventSource 不支持 POST 请求（只能 GET）
 - 无法自定义 HTTP Header（如 Authorization）
 - 无法传递 Request Body（长文本、上下文）
 - 本项目对话 API 需要 POST 传递消息内容

 // hooks/useChatStream.ts
 import { fetchEventSource } from '@microsoft/fetch-event-source'
 import { useRef } from 'react'

 interface ChatStreamOptions {
   onMessage?: (content: string) => void
   onToolCalls?: (data: any) => void
   onToolResults?: (data: any) => void
   onDone?: () => void
   onError?: (error: Error) => void
 }

 export function useChatStream() {
   const abortControllerRef = useRef<AbortController | null>(null)

   const sendMessage = async (
     message: string,
     sessionId: string,
     options: ChatStreamOptions
   ) => {
     abortControllerRef.current = new AbortController()

     await fetchEventSource(`/api/chat/stream?session_id=${sessionId}`, {
       method: 'POST', // 支持 POST 传递 payload
       headers: {
         'Content-Type': 'application/json',
       },
       body: JSON.stringify({ message }),
       signal: abortControllerRef.current.signal,

       onmessage(event) {
         if (event.event === 'message') {
           const data = JSON.parse(event.data)
           options.onMessage?.(data.content)
         } else if (event.event === 'tool_calls') {
           const data = JSON.parse(event.data)
           options.onToolCalls?.(data)
         } else if (event.event === 'tool_results') {
           const data = JSON.parse(event.data)
           options.onToolResults?.(data)
         } else if (event.event === 'done') {
           options.onDone?.()
         }
       },

       onerror(err) {
         console.error('SSE Error:', err)
         options.onError?.(err)
         throw err // 抛出错误以防止自动无限重试
       },
     })
   }

   const stopGeneration = () => {
     abortControllerRef.current?.abort()
   }

   return { sendMessage, stopGeneration }
 }

 4.2 聊天状态管理（Zustand）

 // stores/useChatStore.ts
 import { create } from 'zustand'
 import { chatApi } from '@/api/chat'

 interface Message {
   role: 'user' | 'assistant' | 'system'
   content: string
   sources?: Source[]
   toolCalls?: ToolCall[]
   timestamp: number
 }

 interface Source {
   id: string
   type: 'tool' | 'memory'
   name: string
   summary: string
 }

 interface ToolCall {
   id: string
   name: string
   status: 'pending' | 'running' | 'success' | 'error'
   input?: any
   output?: any
   error?: string
   duration?: number
 }

 interface ChatStore {
   currentSessionId: string
   messages: Message[]
   isGenerating: boolean
   sources: Source[]
   toolCalls: ToolCall[]

   sendMessage: (content: string) => Promise<void>
   addMessage: (message: Message) => void
   updateLastMessage: (updates: Partial<Message>) => void
   addSource: (source: Source) => void
   addToolCall: (toolCall: ToolCall) => void
   updateToolCall: (id: string, updates: Partial<ToolCall>) => void
   clearMessages: () => void
 }

 export const useChatStore = create<ChatStore>((set, get) => ({
   currentSessionId: '',
   messages: [],
   isGenerating: false,
   sources: [],
   toolCalls: [],

   sendMessage: async (content: string) => {
     const { currentSessionId, addMessage } = get()

     // 添加用户消息
     addMessage({
       role: 'user',
       content,
       timestamp: Date.now(),
     })

     set({ isGenerating: true, sources: [], toolCalls: [] })

     // 建立 SSE 连接
     const url = `/api/chat/stream?session_id=${currentSessionId}`
     const eventSource = new EventSource(url)

     eventSource.addEventListener('message', (e) => {
       const data = JSON.parse(e.data)
       get().updateLastMessage({ content: data.content })
     })

     eventSource.addEventListener('tool_calls', (e) => {
       const data = JSON.parse(e.data)
       data.tool_calls.forEach((tc: any) => {
         get().addToolCall({
           id: tc.id,
           name: tc.name,
           status: 'running',
           input: tc.input,
         })
         get().addSource({
           id: tc.id,
           type: 'tool',
           name: tc.name,
           summary: `${tc.name} 调用`,
         })
       })
     })

     eventSource.addEventListener('tool_results', (e) => {
       const data = JSON.parse(e.data)
       data.tool_results.forEach((tr: any) => {
         get().updateToolCall(tr.id, {
           status: tr.error ? 'error' : 'success',
           output: tr.output,
           error: tr.error,
           duration: tr.duration,
         })
       })
     })

     eventSource.addEventListener('done', () => {
       set({ isGenerating: false })
       eventSource.close()
     })
   },

   addMessage: (message) => {
     set((state) => ({ messages: [...state.messages, message] }))
   },

   updateLastMessage: (updates) => {
     set((state) => {
       const messages = [...state.messages]
       const lastMsg = messages[messages.length - 1]
       if (lastMsg) {
         messages[messages.length - 1] = { ...lastMsg, ...updates }
       }
       return { messages }
     })
   },

   addSource: (source) => {
     set((state) => ({ sources: [...state.sources, source] }))
   },

   addToolCall: (toolCall) => {
     set((state) => ({ toolCalls: [...state.toolCalls, toolCall] }))
   },

   updateToolCall: (id, updates) => {
     set((state) => ({
       toolCalls: state.toolCalls.map((tc) =>
         tc.id === id ? { ...tc, ...updates } : tc
       ),
     }))
   },

   clearMessages: () => {
     set({ messages: [], sources: [], toolCalls: [] })
   },
 }))

 4.3 工具调用可视化（Ant Design）

 // components/chat/ToolCallCard.tsx
 import React, { useState } from 'react'
 import { Card, Tag, Space, Typography, Collapse, Badge } from 'antd'
 import { CheckCircleOutlined, CloseCircleOutlined, LoadingOutlined } from '@ant-design/icons'

 const { Text } = Typography
 const { Panel } = Collapse

 interface ToolCallCardProps {
   toolCall: {
     id: string
     name: string
     status: 'pending' | 'running' | 'success' | 'error'
     input?: any
     output?: any
     error?: string
     duration?: number
   }
 }

 const ToolCallCard: React.FC<ToolCallCardProps> = ({ toolCall }) => {
   const getStatusIcon = () => {
     switch (toolCall.status) {
       case 'success':
         return <CheckCircleOutlined style={{ color: '#52c41a' }} />
       case 'error':
         return <CloseCircleOutlined style={{ color: '#ff4d4f' }} />
       case 'running':
         return <LoadingOutlined />
       default:
         return null
     }
   }

   const getStatusText = () => {
     switch (toolCall.status) {
       case 'success':
         return `Success (${toolCall.duration}s)`
       case 'error':
         return 'Error'
       case 'running':
         return 'Running...'
       default:
         return 'Pending'
     }
   }

   return (
     <Card size="small" style={{ marginBottom: 8 }}>
       <Space direction="vertical" style={{ width: '100%' }}>
         <Space>
           <Text strong>🔧 {toolCall.name}</Text>
           <Badge status={toolCall.status === 'success' ? 'success' : 'processing'} />
           {getStatusIcon()}
           <Text type="secondary">{getStatusText()}</Text>
         </Space>

         <Collapse ghost>
           <Panel header="查看详情" key="1">
             <Space direction="vertical" style={{ width: '100%' }}>
               <div>
                 <Text strong>Input:</Text>
                 <pre style={{ background: '#f5f5f5', padding: 8, borderRadius: 4 }}>
                   {JSON.stringify(toolCall.input, null, 2)}
                 </pre>
               </div>

               {toolCall.output && (
                 <div>
                   <Text strong>Output:</Text>
                   <pre style={{ background: '#f5f5f5', padding: 8, borderRadius: 4 }}>
                     {JSON.stringify(toolCall.output, null, 2)}
                   </pre>
                 </div>
               )}

               {toolCall.error && (
                 <div>
                   <Text type="danger" strong>Error:</Text>
                   <pre style={{ background: '#fff2f0', padding: 8, borderRadius: 4, color: '#ff4d4f' }}>
                     {toolCall.error}
                   </pre>
                 </div>
               )}
             </Space>
           </Panel>
         </Collapse>
       </Space>
     </Card>
   )
 }

 export default ToolCallCard

 4.4 记忆图谱核心逻辑（性能优化版）

 // hooks/useMemoryGraph.ts
 import { useEffect, useState } from 'react'
 import G6 from '@antv/g6'
 import { memoryApi } from '@/api/memory'

 interface Quintuple {
   subject: string
   subject_type: string
   predicate: string
   object: string
   object_type: string
 }

 export function useMemoryGraph(containerId: string) {
   const [graph, setGraph] = useState<any>(null)
   const [loading, setLoading] = useState(false)

   useEffect(() => {
     const g = new G6.Graph({
       container: containerId,
       width: 800,
       height: 600,
       layout: {
         type: 'force',
         preventOverlap: true,
         nodeStrength: -30,
         edgeStrength: 0.1,
       },
       modes: {
         default: ['drag-canvas', 'zoom-canvas', 'drag-node'],
       },
       defaultNode: {
         size: 30,
         style: {
           fill: '#5B8FF9',
           stroke: '#fff',
           lineWidth: 2,
         },
         labelCfg: {
           position: 'bottom',
           style: { fill: '#000' },
         },
       },
       defaultEdge: {
         style: {
           stroke: '#e2e2e2',
           lineWidth: 2,
         },
         labelCfg: {
           autoRotate: true,
           style: { fill: '#666' },
         },
       },
     })

     // 性能优化：布局稳定后立刻停止计算，释放 CPU 资源
     g.on('afterlayout', () => {
       g.stopLayout()
     })

     setGraph(g)

     return () => {
       g.destroy()
     }
   }, [containerId])

   const loadData = async () => {
     setLoading(true)
     try {
       const { quintuples } = await memoryApi.getQuintuples(100, 0)
       const graphData = quintuplesToG6Data(quintuples)
       graph?.data(graphData)
       graph?.render()
     } catch (error) {
       console.error('Failed to load memory graph:', error)
     } finally {
       setLoading(false)
     }
   }

   const quintuplesToG6Data = (quintuples: Quintuple[]) => {
     const nodes = new Map<string, any>()
     const edges: any[] = []

     quintuples.forEach((q, index) => {
       if (!nodes.has(q.subject)) {
         nodes.set(q.subject, {
           id: q.subject,
           label: q.subject,
           type: q.subject_type,
           style: { fill: getColorByType(q.subject_type) },
         })
       }

       if (!nodes.has(q.object)) {
         nodes.set(q.object, {
           id: q.object,
           label: q.object,
           type: q.object_type,
           style: { fill: getColorByType(q.object_type) },
         })
       }

       edges.push({
         id: `edge-${index}`,
         source: q.subject,
         target: q.object,
         label: q.predicate,
       })
     })

     return {
       nodes: Array.from(nodes.values()),
       edges,
     }
   }

   const getColorByType = (type: string) => {
     const colors: Record<string, string> = {
       人物: '#5B8FF9',
       地点: '#5AD8A6',
       组织: '#5D7092',
       物品: '#F6BD16',
       概念: '#E86452',
       时间: '#6DC8EC',
       事件: '#945FB9',
       活动: '#FF9845',
     }
     return colors[type] || '#5B8FF9'
   }

   return { graph, loading, loadData }
 }

 ---
 5. 设计系统（Zen-iOS Hybrid 设计语言）

 5.1 核心设计原则

 Zen-iOS Hybrid 设计语言：追求极致的物理触感、光学模糊效果和高对比度的冷灰调设计。

 核心目标：
 - 消除界面模糊感
 - 通过物理边框、内阴影和层级叠放创造清晰边界
 - 既柔和又专业的视觉体验

 5.2 视觉基调

 // styles/design-tokens.ts
 export const designTokens = {
   // 底色规范 (Base Layer)
   colors: {
     base: {
       background: '#F2F2F7',      // iOS 系统级灰
       backgroundAlt: '#F9F9FB',   // 冷灰
       white: '#FFFFFF',
       black: '#1C1C1E',           // 深空黑
       graphite: '#2C2C2E',        // 石墨色
     },

     // 对比策略 (Contrast Rule)
     surface: {
       elevated: 'rgba(255, 255, 255, 0.6)',  // 毛玻璃填充
       card: 'rgba(255, 255, 255, 0.4)',
       hover: 'rgba(255, 255, 255, 0.8)',
     },

     // 边框颜色
     border: {
       inner: 'rgba(255, 255, 255, 0.6)',     // 内描边（光线）
       outer: 'rgba(229, 229, 234, 0.4)',     // 外描边（轮廓）
     },

     // 文字颜色
     text: {
       primary: '#1C1C1E',
       secondary: '#6E6E73',
       tertiary: '#AEAEB2',
     },

     // 功能色
     accent: {
       primary: '#007AFF',         // iOS 蓝
       success: '#34C759',
       warning: '#FF9500',
       error: '#FF3B30',
     },
   },

   // 圆角美学 (Curvature)
   radius: {
     container: '40px',            // 大容器
     card: '28px',                 // 功能块
     button: '20px',               // 按钮
     small: '12px',                // 小组件
   },

   // 模糊效果 (Blur)
   blur: {
     light: '40px',
     medium: '50px',
     heavy: '60px',
   },

   // 阴影深度 (Shadow)
   shadow: {
     elevated: '0 24px 48px -12px rgba(0, 0, 0, 0.08)',
     card: '0 8px 24px -4px rgba(0, 0, 0, 0.06)',
     inset: 'inset 0 2px 4px rgba(0, 0, 0, 0.06)',
   },

   // 间距 (Spacing)
   spacing: {
     xs: '8px',
     sm: '12px',
     md: '16px',
     lg: '24px',
     xl: '32px',
     xxl: '48px',
   },

   // 字体 (Typography)
   font: {
     family: {
       display: 'SF Pro Display, Inter, -apple-system, BlinkMacSystemFont, sans-serif',
       text: 'SF Pro Text, Inter, -apple-system, BlinkMacSystemFont, sans-serif',
     },
     size: {
       xs: '10px',
       sm: '12px',
       base: '14px',
       lg: '16px',
       xl: '20px',
       '2xl': '24px',
       '3xl': '30px',
       '4xl': '38px',
     },
     weight: {
       regular: 400,
       medium: 500,
       semibold: 600,
       bold: 700,
       extrabold: 800,
     },
   },
 }

 5.3 Ant Design 主题定制

 // styles/antd-theme.ts
 import type { ThemeConfig } from 'antd'
 import { designTokens } from './design-tokens'

 export const theme: ThemeConfig = {
   token: {
     // 颜色
     colorPrimary: designTokens.colors.accent.primary,
     colorSuccess: designTokens.colors.accent.success,
     colorWarning: designTokens.colors.accent.warning,
     colorError: designTokens.colors.accent.error,
     colorBgBase: designTokens.colors.base.background,
     colorTextBase: designTokens.colors.text.primary,

     // 字体
     fontFamily: designTokens.font.family.text,
     fontSize: 14,
     fontSizeHeading1: 38,
     fontSizeHeading2: 30,
     fontSizeHeading3: 24,

     // 圆角（iOS 连续曲率）
     borderRadius: 20,
     borderRadiusLG: 28,
     borderRadiusSM: 12,

     // 间距（呼吸感排版）
     padding: 24,
     paddingLG: 32,
     paddingSM: 16,
     paddingXS: 12,
   },

   components: {
     // 卡片组件（毛玻璃效果）
     Card: {
       borderRadiusLG: 28,
       boxShadowTertiary: designTokens.shadow.card,
     },

     // 按钮组件（高对比交互）
     Button: {
       borderRadius: 20,
       controlHeight: 44,
       primaryColor: designTokens.colors.base.black,
       defaultBg: designTokens.colors.base.white,
       defaultBorderColor: designTokens.colors.border.outer,
     },

     // 输入框组件（凹陷效果）
     Input: {
       borderRadius: 20,
       controlHeight: 44,
       colorBgContainer: 'rgba(242, 242, 247, 0.5)',
     },
   },
 }

 5.4 Tailwind 配置（Zen-iOS Hybrid）

 // tailwind.config.js
 module.exports = {
   content: ['./src/**/*.{js,jsx,ts,tsx}'],
   theme: {
     extend: {
       colors: {
         zen: {
           bg: '#F2F2F7',           // 底层系统灰
           surface: 'rgba(255, 255, 255, 0.5)', // 毛玻璃底色
           black: '#1C1C1E',        // 极致深空黑
           graphite: '#2C2C2E',     // 石墨色
           textSecondary: '#6E6E73',// 次要文本
           textTertiary: '#AEAEB2', // 三级文本
         },
       },
       boxShadow: {
         // 双层物理描边 + 大范围柔和扩散阴影
         'zen-glass': 'inset 0 0 0 1px rgba(255,255,255,0.6), 0 0 0 1px rgba(229,229,234,0.4), 0 24px 48px -12px
 rgba(0,0,0,0.08)',
         // 输入框凹陷工艺
         'zen-inset': 'inset 0 2px 4px rgba(0,0,0,0.06), 0 0 0 1px rgba(229,229,234,0.4)',
       },
       borderRadius: {
         'zen-lg': '40px',
         'zen-md': '28px',
         'zen-sm': '20px',
       },
       backdropBlur: {
         'zen': '50px',
       },
     },
   },
   plugins: [],
 }

 5.5 全局样式（Zen-iOS Hybrid）

 /* styles/global.css */
 * {
   margin: 0;
   padding: 0;
   box-sizing: border-box;
 }

 body {
   font-family: 'SF Pro Text', 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
   background: #F2F2F7;  /* iOS 系统级灰 */
   color: #1C1C1E;       /* 深空黑 */
   line-height: 1.6;
   -webkit-font-smoothing: antialiased;
   -moz-osx-font-smoothing: grayscale;
 }

 /* 毛玻璃容器 (Frosted Glass Container) */
 .glass-container {
   background: rgba(255, 255, 255, 0.6);
   backdrop-filter: blur(50px);
   -webkit-backdrop-filter: blur(50px);
   border-radius: 40px;
   border: 1px solid rgba(255, 255, 255, 0.6);  /* 内描边 */
   box-shadow:
     0 0 0 1px rgba(229, 229, 234, 0.4),        /* 外描边 */
     0 24px 48px -12px rgba(0, 0, 0, 0.08);     /* 扩散阴影 */
   padding: 32px;
 }

 /* 卡片组件 (Card) */
 .card {
   background: rgba(255, 255, 255, 0.4);
   backdrop-filter: blur(40px);
   -webkit-backdrop-filter: blur(40px);
   border-radius: 28px;
   border: 1px solid rgba(255, 255, 255, 0.6);
   box-shadow:
     0 0 0 1px rgba(229, 229, 234, 0.4),
     0 8px 24px -4px rgba(0, 0, 0, 0.06);
   padding: 24px;
   margin-bottom: 16px;
   transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
 }

 .card:hover {
   background: rgba(255, 255, 255, 0.8);
   backdrop-filter: blur(60px);
   -webkit-backdrop-filter: blur(60px);
   transform: translateY(-2px);
   box-shadow:
     0 0 0 1px rgba(229, 229, 234, 0.4),
     0 16px 32px -8px rgba(0, 0, 0, 0.12);
 }

 /* 主按钮 (Primary Button) */
 .btn-primary {
   background: #1C1C1E;  /* 深空黑 */
   color: white;
   border: none;
   border-radius: 20px;
   padding: 12px 32px;
   font-size: 14px;
   font-weight: 600;
   cursor: pointer;
   transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
   box-shadow: 0 4px 12px rgba(28, 28, 30, 0.2);
 }

 .btn-primary:hover {
   background: #2C2C2E;
   transform: translateY(-1px);
   box-shadow: 0 6px 16px rgba(28, 28, 30, 0.3);
 }

 .btn-primary:active {
   transform: scale(0.98);
 }

 /* 次级按钮 (Secondary Button) */
 .btn-secondary {
   background: white;
   color: #1C1C1E;
   border: 1px solid rgba(229, 229, 234, 0.4);
   border-radius: 20px;
   padding: 12px 32px;
   font-size: 14px;
   font-weight: 600;
   cursor: pointer;
   transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
   box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
 }

 .btn-secondary:hover {
   background: rgba(255, 255, 255, 0.8);
   backdrop-filter: blur(60px);
   -webkit-backdrop-filter: blur(60px);
   border-color: rgba(229, 229, 234, 0.6);
 }

 .btn-secondary:active {
   transform: scale(0.98);
 }

 /* 输入框 (Input Field) */
 .input-field {
   background: rgba(242, 242, 247, 0.5);
   border: 1px solid rgba(229, 229, 234, 0.4);
   border-radius: 20px;
   padding: 12px 20px;
   font-size: 14px;
   color: #1C1C1E;
   box-shadow: inset 0 2px 4px rgba(0, 0, 0, 0.06);  /* 凹陷效果 */
   transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
 }

 .input-field:focus {
   outline: none;
   background: rgba(255, 255, 255, 0.8);
   border-color: #007AFF;
   box-shadow:
     inset 0 2px 4px rgba(0, 0, 0, 0.06),
     0 0 0 4px rgba(0, 122, 255, 0.1);
 }

 .input-field::placeholder {
   color: #AEAEB2;
 }

 /* 搜索框（大号） */
 .search-input-large {
   background: rgba(255, 255, 255, 0.6);
   backdrop-filter: blur(40px);
   -webkit-backdrop-filter: blur(40px);
   border: 1px solid rgba(255, 255, 255, 0.6);
   border-radius: 24px;
   padding: 16px 24px;
   font-size: 16px;
   color: #1C1C1E;
   box-shadow:
     0 0 0 1px rgba(229, 229, 234, 0.4),
     inset 0 2px 4px rgba(0, 0, 0, 0.04);
   transition: all 0.3s cubic-bezier(0, 0, 0.2, 1);
 }

 .search-input-large:focus {
   outline: none;
   background: rgba(255, 255, 255, 0.9);
   backdrop-filter: blur(60px);
   -webkit-backdrop-filter: blur(60px);
   border-color: #007AFF;
   box-shadow:
     0 0 0 1px #007AFF,
     0 0 0 4px rgba(0, 122, 255, 0.1),
     0 8px 24px rgba(0, 122, 255, 0.15);
 }

 /* 来源标签 (Source Tag) */
 .source-tag {
   display: inline-flex;
   align-items: center;
   gap: 6px;
   padding: 6px 14px;
   background: rgba(0, 122, 255, 0.1);
   color: #007AFF;
   border: 1px solid rgba(0, 122, 255, 0.2);
   border-radius: 16px;
   font-size: 10px;
   font-weight: 700;
   text-transform: uppercase;
   letter-spacing: 0.5px;
   cursor: pointer;
   transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
 }

 .source-tag:hover {
   background: rgba(0, 122, 255, 0.15);
   border-color: rgba(0, 122, 255, 0.3);
   transform: translateY(-1px);
 }

 .source-tag:active {
   transform: scale(0.95);
 }

 /* 工具调用卡片 (Tool Call Card) */
 .tool-call-card {
   background: rgba(242, 242, 247, 0.5);
   border: 1px solid rgba(229, 229, 234, 0.4);
   border-radius: 20px;
   padding: 16px;
   margin-bottom: 12px;
   box-shadow: inset 0 2px 4px rgba(0, 0, 0, 0.06);
 }

 /* 图谱容器 (Graph Container) */
 .graph-container {
   width: 100%;
   height: 600px;
   background: rgba(255, 255, 255, 0.6);
   backdrop-filter: blur(50px);
   -webkit-backdrop-filter: blur(50px);
   border-radius: 40px;
   border: 1px solid rgba(255, 255, 255, 0.6);
   box-shadow:
     0 0 0 1px rgba(229, 229, 234, 0.4),
     0 24px 48px -12px rgba(0, 0, 0, 0.08);
   overflow: hidden;
 }

 /* 标签文字（工业设计风格） */
 .label-text {
   font-size: 10px;
   font-weight: 700;
   text-transform: uppercase;
   letter-spacing: 1px;
   color: #6E6E73;
 }

 /* 标题文字 */
 .heading-text {
   font-family: 'SF Pro Display', 'Inter', sans-serif;
   font-weight: 800;
   letter-spacing: -0.02em;
   color: #1C1C1E;
 }

 /* 响应式布局 */
 @media (max-width: 768px) {
   .glass-container {
     border-radius: 28px;
     padding: 24px;
   }

   .card {
     border-radius: 20px;
     padding: 20px;
   }

   .search-input-large {
     font-size: 14px;
     padding: 12px 20px;
     border-radius: 20px;
   }

   .graph-container {
     height: 400px;
     border-radius: 28px;
   }
 }

 /* 触觉反馈动画 */
 @keyframes tactile-press {
   0% { transform: scale(1); }
   50% { transform: scale(0.98); }
   100% { transform: scale(1); }
 }

 .tactile-feedback:active {
   animation: tactile-press 0.15s cubic-bezier(0.4, 0, 0.2, 1);
 }

 ---
 6. 部署方案（局域网访问）

 6.1 开发环境配置

 # .env.development
 VITE_API_BASE_URL=http://localhost:8000
 VITE_APP_TITLE=NagaAgent Web

 // vite.config.ts
 import { defineConfig } from 'vite'
 import react from '@vitejs/plugin-react'
 import path from 'path'

 export default defineConfig({
   plugins: [react()],
   resolve: {
     alias: {
       '@': path.resolve(__dirname, './src'),
     },
   },
   server: {
     host: '0.0.0.0',  // 允许局域网访问
     port: 3000,
     proxy: {
       '/api': {
         target: 'http://localhost:8000',
         changeOrigin: true,
       },
     },
   },
 })

 6.2 启动命令

 # 安装依赖
 npm install

 # 启动开发服务器（局域网可访问）
 npm run dev

 # 访问地址
 # 本机: http://localhost:3000
 # 局域网: http://192.168.x.x:3000

 6.3 生产构建（可选）

 # 构建生产版本
 npm run build

 # 预览构建结果
 npm run preview

 # 使用 serve 部署静态文件
 npx serve -s dist -l 3000

 6.4 Nginx 配置（可选）

 server {
   listen 80;
   server_name naga.local;

   root /var/www/naga-web/dist;
   index index.html;

   # 前端路由
   location / {
     try_files $uri $uri/ /index.html;
   }

   # 后端 API 代理
   location /api {
     proxy_pass http://localhost:8000;
     proxy_http_version 1.1;
     proxy_set_header Upgrade $http_upgrade;
     proxy_set_header Connection 'upgrade';
     proxy_set_header Host $host;
     proxy_cache_bypass $http_upgrade;

     # SSE 支持
     proxy_buffering off;
     proxy_read_timeout 86400;
   }
 }

 ---
 7. 72h 实施计划（调整后）

 Day 1（0-24h）：项目搭建 + 聊天功能

 上午（0-4h）：
 - 初始化项目（npm create vite@latest naga-web -- --template react-ts）
 - 安装依赖（React Router、Ant Design、Zustand、Axios、G6）
 - 配置 Vite（代理、别名、局域网访问）
 - 搭建基础布局（AppLayout、AppHeader）

 下午（4-8h）：
 - 实现聊天页面布局（Perplexity 风格）
 - 实现消息列表组件（MessageList、MessageItem）
 - 实现输入框组件（MessageInput）
 - 集成 SSE 流式消息（useSSE Hook）

 晚上（8-12h）：
 - 实现工具调用卡片（ToolCallCard）
 - 实现来源卡片（SourceCard）
 - 实现聊天状态管理（useChatStore）
 - 测试聊天基础功能

 验收标准：
 - ✅ 可以发送消息并接收流式回复
 - ✅ 工具调用可视化正常显示
 - ✅ 来源引用编号正确展示

 Day 2（24-48h）：工具管理 + 记忆图谱（重点）

 上午（24-28h）：
 - 实现工具管理页面布局
 - 实现工具卡片组件（ToolCard）
 - 实现工具状态监控
 - 集成工具 API（/mcp/services）

 下午（28-32h）：
 - 实现记忆图谱页面布局（重点）
 - 集成 G6 图可视化引擎
 - 实现五元组数据转换逻辑
 - 实现图谱交互功能（拖拽、缩放、点击）

 晚上（32-36h）：
 - 实现五元组列表组件（QuintupleList）
 - 实现实体详情抽屉（EntityDetailDrawer）
 - 实现图谱过滤器（GraphFilters）
 - 实现记忆统计面板（MemoryStats）

 验收标准：
 - ✅ 工具列表正常加载和显示
 - ✅ 记忆图谱正常渲染（节点、边、标签）
 - ✅ 五元组列表正确展示
 - ✅ 图谱交互功能正常（拖拽、缩放）

 Day 3（48-72h）：移动端适配 + 优化 + 测试

 上午（48-52h）：
 - 响应式布局适配（移动端）
 - 实现设置页面（SettingsPage）
 - 实现配置持久化（localStorage）
 - 添加错误边界（ErrorBoundary）

 下午（52-56h）：
 - 性能优化（虚拟滚动、懒加载）
 - 添加 Loading 状态
 - 添加空状态提示（EmptyState）
 - 优化图谱渲染性能（节点数量限制）

 晚上（56-60h）：
 - 集成测试（手动）
 - 修复关键 Bug
 - UI/UX 优化
 - 添加动画与过渡效果

 最后 12h（60-72h）：
 - 局域网部署测试
 - 多设备兼容性测试（桌面/平板/手机）
 - 用户验收测试
 - 编写部署文档

 验收标准：
 - ✅ 移动端布局正常显示
 - ✅ 局域网内其他设备可正常访问
 - ✅ 核心功能无阻塞性 Bug
 - ✅ 性能满足基本要求（图谱渲染 <2s）

 ---
 8. 技术亮点

 8.1 Perplexity 风格 UI

 - 搜索引擎式布局
 - 引用来源可视化（[1][2][3] 标签）
 - 来源卡片展示（工具调用 + 记忆检索）
 - 相关问题推荐

 8.2 专业级知识图谱

 - G6 图可视化引擎（蚂蚁集团出品）
 - 力导向布局算法
 - 实体类型颜色映射
 - 交互式节点操作（拖拽、缩放、点击）
 - 五元组列表与图谱联动

 8.3 实时交互

 - SSE 流式消息推送
 - 工具调用实时可视化
 - 打字机效果
 - 状态实时同步

 8.4 响应式设计

 - 桌面/平板/移动端适配
 - Ant Design 响应式栅格系统
 - 移动端优化（触摸交互、手势支持）

 ---
 9. 成功标准

 9.1 必须完成（P0）

 - ✅ 聊天界面可用（发送消息 + 接收回复）
 - ✅ SSE 流式消息正常工作
 - ✅ 工具调用可视化（Perplexity 风格来源卡片）
 - ✅ 记忆图谱可视化（G6 力导向图）
 - ✅ 五元组列表展示
 - ✅ 响应式布局（桌面 + 移动）
 - ✅ 局域网访问正常

 9.2 期望完成（P1）

 - ⭕ 工具管理界面
 - ⭕ 图谱过滤器（实体类型、关系类型）
 - ⭕ 实体详情抽屉
 - ⭕ 设置界面
 - ⭕ 会话历史管理

 9.3 可选完成（P2）

 - ⭕ 相关问题推荐
 - ⭕ 导出对话功能
 - ⭕ 图谱导出（PNG/JSON）
 - ⭕ 暗色主题切换

 ---
 10. 风险与缓解

 ┌──────────────────┬──────┬────────────────────────────────────────┐
 │       风险       │ 影响 │                缓解措施                │
 ├──────────────────┼──────┼────────────────────────────────────────┤
 │ React 生态不熟悉 │ 中   │ 参考 Ant Design 官方示例，使用成熟组件 │
 ├──────────────────┼──────┼────────────────────────────────────────┤
 │ G6 学习曲线陡    │ 高   │ 使用官方示例代码，简化配置             │
 ├──────────────────┼──────┼────────────────────────────────────────┤
 │ SSE 跨域问题     │ 高   │ 配置 Vite 代理，后端启用 CORS          │
 ├──────────────────┼──────┼────────────────────────────────────────┤
 │ 移动端适配复杂   │ 中   │ 优先桌面版，移动端简化布局             │
 ├──────────────────┼──────┼────────────────────────────────────────┤
 │ 图谱性能问题     │ 中   │ 限制节点数量（100 个），Canvas 渲染    │
 ├──────────────────┼──────┼────────────────────────────────────────┤
 │ 72h 时间不足     │ 高   │ 砍掉非核心功能（相关问题、导出）       │
 └──────────────────┴──────┴────────────────────────────────────────┘

 ---
 11. 关键文件清单

 11.1 核心页面

 - src/pages/ChatPage.tsx - 聊天主界面（Perplexity 风格）
 - src/pages/MemoryPage.tsx - 记忆图谱界面（G6 可视化）
 - src/pages/ToolsPage.tsx - 工具管理界面
 - src/pages/SettingsPage.tsx - 设置界面

 11.2 核心组件

 - src/components/chat/MessageList.tsx - 消息列表
 - src/components/chat/ToolCallCard.tsx - 工具调用卡片
 - src/components/chat/SourceCard.tsx - 来源卡片
 - src/components/memory/KnowledgeGraph.tsx - G6 图谱主组件
 - src/components/memory/QuintupleList.tsx - 五元组列表

 11.3 核心 Hooks

 - src/hooks/useSSE.ts - SSE 流式处理
 - src/hooks/useMemoryGraph.ts - 记忆图谱逻辑
 - src/hooks/useQuintuples.ts - 五元组查询

 11.4 状态管理

 - src/stores/useChatStore.ts - 聊天状态
 - src/stores/useMemoryStore.ts - 记忆状态
 - src/stores/useToolsStore.ts - 工具状态

 11.5 API 客户端

 - src/api/client.ts - Axios 实例
 - src/api/chat.ts - 聊天 API
 - src/api/memory.ts - 记忆 API（重点）
 - src/api/tools.ts - 工具 API

 ---
 12. 后端 API 契约（基于探索结果）

 12.1 记忆 API

 获取统计信息：
 GET /memory/stats
 Response: {
   status: "success",
   memory_stats: {
     enabled: true,
     total_tasks: 42,
     pending_tasks: 2,
     completed_tasks: 35,
     ...
   }
 }

 获取所有五元组：
 GET /memory/quintuples?limit=100&offset=0
 Response: {
   status: "success",
   quintuples: [
     ["小明", "人物", "踢", "足球", "物品"],
     ["小明", "人物", "在", "公园", "地点"]
   ],
   count: 2
 }

 搜索五元组：
 GET /memory/quintuples/search?keywords=小明,足球
 Response: {
   status: "success",
   quintuples: [...],
   count: 1
 }

 12.2 聊天 API

 流式聊天：
 POST /chat/stream?session_id=xxx
 Events:
 - message: { content: "..." }
 - tool_calls: { tool_calls: [...] }
 - tool_results: { tool_results: [...] }
 - done: {}

 12.3 工具 API

 获取工具列表：
 GET /mcp/services
 Response: {
   services: [
     { name: "weather_time", enabled: true, ... }
   ]
 }

 ---
 13. 验证计划

 13.1 功能验证

 - 发送消息并接收流式回复
 - 工具调用正确显示在来源卡片中
 - 记忆图谱正确渲染五元组数据
 - 图谱节点可拖拽、缩放
 - 五元组列表与图谱数据一致
 - 移动端布局正常显示

 13.2 性能验证

 - 图谱渲染时间 <2s（100 个节点）
 - SSE 消息延迟 <100ms
 - 页面首次加载 <3s

 13.3 兼容性验证

 - Chrome/Edge 最新版
 - Firefox 最新版
 - Safari 最新版（macOS/iOS）
 - 移动端浏览器（Android/iOS）

 ---
 14. 交付物清单

 - 完整源代码（naga-web/ 目录）
 - 部署文档（README.md）
 - 环境配置文件（.env.example）
 - 依赖清单（package.json）
 - 构建产物（dist/ 目录，可选）

 ---
 15. 核心组件示例代码

 15.1 来源卡片（Perplexity 风格 + Zen-iOS）

 // components/chat/SourceCard.tsx
 import { Link2, Database, Brain } from 'lucide-react'

 interface SourceCardProps {
   type: 'tool' | 'memory' | 'web'
   title: string
   index: number
   onClick?: () => void
 }

 export const SourceCard: React.FC<SourceCardProps> = ({ type, title, index, onClick }) => {
   const Icon = type === 'memory' ? Brain : type === 'tool' ? Database : Link2

   return (
     <div
       className="group flex flex-col gap-2 p-3 bg-white/40 backdrop-blur-md rounded-xl border border-white/60
 shadow-[0_4px_12px_rgba(0,0,0,0.03)] cursor-pointer hover:bg-white/80 active:scale-[0.98] transition-all"
       onClick={onClick}
     >
       <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-widest
 text-zen-textSecondary">
         <Icon size={12} strokeWidth={2} />
         <span>Source {index}</span>
       </div>
       <div className="text-[13px] font-semibold text-zen-black line-clamp-2">
         {title}
       </div>
     </div>
   )
 }

 15.2 搜索输入框（凹陷工艺）

 // components/chat/ChatInput.tsx
 import { Search, Paperclip, ArrowUp } from 'lucide-react'
 import { useState } from 'react'

 interface ChatInputProps {
   onSend: (message: string) => void
   disabled?: boolean
 }

 export const ChatInput: React.FC<ChatInputProps> = ({ onSend, disabled }) => {
   const [message, setMessage] = useState('')

   const handleSend = () => {
     if (message.trim() && !disabled) {
       onSend(message)
       setMessage('')
     }
   }

   return (
     <div className="p-6 bg-zen-bg">
       <div className="relative flex items-end gap-3 p-3 bg-[#F2F2F7]/80 shadow-zen-inset rounded-zen-md transition-all
  focus-within:bg-white/80 focus-within:shadow-[inset_0_2px_4px_rgba(0,0,0,0.02),0_0_0_1px_#007AFF]">
         <button className="p-3 text-zen-textSecondary hover:text-zen-black transition-colors active:scale-[0.98]">
           <Paperclip strokeWidth={2} size={20} />
         </button>

         <textarea
           className="flex-1 max-h-48 min-h-[44px] bg-transparent resize-none outline-none text-[16px] text-zen-black
 placeholder-zen-textSecondary py-3"
           placeholder="Ask anything..."
           value={message}
           onChange={(e) => setMessage(e.target.value)}
           onKeyDown={(e) => {
             if (e.key === 'Enter' && !e.shiftKey) {
               e.preventDefault()
               handleSend()
             }
           }}
           disabled={disabled}
         />

         <button
           className="p-3 bg-zen-black text-white rounded-[20px] shadow-md hover:bg-zen-graphite active:scale-[0.98]
 transition-all disabled:opacity-50"
           onClick={handleSend}
           disabled={disabled || !message.trim()}
         >
           <ArrowUp strokeWidth={2} size={20} />
         </button>
       </div>
     </div>
   )
 }

 15.3 五元组卡片（工业设计风格）

 // components/memory/QuintupleCard.tsx
 import { Tag } from 'antd'

 interface QuintupleCardProps {
   quintuple: {
     subject: string
     subject_type: string
     predicate: string
     object: string
     object_type: string
   }
   source?: string
   timestamp?: string
 }

 export const QuintupleCard: React.FC<QuintupleCardProps> = ({ quintuple, source, timestamp }) => {
   return (
     <div className="p-4 bg-white/40 backdrop-blur-md rounded-zen-sm border border-white/60
 shadow-[0_2px_8px_rgba(0,0,0,0.04)] mb-3 hover:bg-white/60 transition-all">
       <div className="flex items-center gap-2 flex-wrap">
         <span className="text-[10px] font-bold uppercase tracking-widest text-zen-textSecondary">
           {quintuple.subject_type}
         </span>
         <span className="text-[14px] font-semibold text-zen-black">
           {quintuple.subject}
         </span>
         <span className="text-[12px] text-zen-textSecondary">
           {quintuple.predicate}
         </span>
         <span className="text-[14px] font-semibold text-zen-black">
           {quintuple.object}
         </span>
         <span className="text-[10px] font-bold uppercase tracking-widest text-zen-textSecondary">
           {quintuple.object_type}
         </span>
       </div>
       {source && (
         <div className="mt-2 text-[11px] text-zen-textTertiary">
           来源: {source} · {timestamp}
         </div>
       )}
     </div>
   )
 }

 ---
 16. 依赖清单（package.json）

 {
   "name": "naga-web",
   "version": "1.0.0",
   "type": "module",
   "scripts": {
     "dev": "vite",
     "build": "tsc && vite build",
     "preview": "vite preview",
     "lint": "eslint src --ext ts,tsx",
     "test": "jest"
   },
   "dependencies": {
     "react": "^18.3.1",
     "react-dom": "^18.3.1",
     "react-router-dom": "^6.22.0",
     "zustand": "^4.5.0",
     "axios": "^1.6.7",
     "@microsoft/fetch-event-source": "^2.0.1",
     "antd": "^5.15.0",
     "@antv/g6": "^5.0.0",
     "lucide-react": "^0.344.0"
   },
   "devDependencies": {
     "@types/react": "^18.2.55",
     "@types/react-dom": "^18.2.19",
     "@vitejs/plugin-react": "^4.2.1",
     "typescript": "^5.3.3",
     "vite": "^5.1.0",
     "tailwindcss": "^3.4.1",
     "autoprefixer": "^10.4.17",
     "postcss": "^8.4.35",
     "eslint": "^8.56.0",
     "prettier": "^3.2.5",
     "jest": "^29.7.0",
     "@testing-library/react": "^14.2.1"
   }
 }

 ---
 17. 参考资料

 - UI 参考：Perplexity AI (https://www.perplexity.ai/)
 - React 官方文档：https://react.dev/
 - Ant Design 文档：https://ant.design/
 - G6 图可视化：https://g6.antv.antgroup.com/
 - Zustand 状态管理：https://zustand-demo.pmnd.rs/
 - 后端 API：doc/04-api-protocol-proxy-guide.md
 - 记忆系统：summer_memory/ 目录
 - 工具规范：doc/09-tool-execution-specification.md