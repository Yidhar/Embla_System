# NagaAgent 游戏视觉交互与攻略融合系统 — 产品需求文档

> **版本**: v1.0
> **日期**: 2026-02-11
> **产品名称**: NagaAgent（娜迦 / Naaga）
> **文档性质**: 功能更新产品需求文档（PRD）
> **涉及模块**: 屏幕视觉识别、游戏操控、攻略智能体融合

---

## 一、文档概述

### 1.1 背景

当前版本（v4.0）在屏幕识别与操控模块上存在 **7 项已知缺陷**，实质处于不可用状态；同时，团队已独立开发了一套成熟的**游戏攻略问答系统**（攻略智能体），支持 9 款游戏的 RAG 检索与流式回答，但两者完全隔离、互不感知。

本次功能更新的核心目标：**让 NagaAgent 看得见游戏画面、操作得了游戏界面、答得出攻略问题——三位一体，形成"边玩边问边代操"的沉浸式游戏陪伴体验。**

### 1.2 目标用户画像

| 特征 | 描述 |
|------|------|
| **核心用户** | 二次元手游 / PC 游戏玩家（明日方舟、原神、崩铁、鸣潮、绝区零等） |
| **使用场景** | 游玩回合制/慢节奏游戏时，希望有攻略辅助或代操日常任务 |
| **痛点** | 切出游戏查攻略打断沉浸感；日常重复操作（刷本、签到）繁琐 |
| **期望** | 一个"看得懂画面、答得出攻略、帮得上手"的二次元伙伴 |

### 1.3 设计原则

1. **渐进式交付** — P0 修复基础 → P1 核心能力 → P2 深度融合，每个阶段可独立验收
2. **快→慢、免费→付费** — 视觉识别优先模板匹配/OCR，仅在必要时调用 AI 视觉模型
3. **诚实边界** — 明确告知用户不支持内核级反作弊游戏（EAC/BattleEye/Vanguard），不做虚假承诺
4. **角色一体** — 所有交互通过 Live2D 角色"娜迦"统一呈现，攻略回答、操作反馈都是"她在说"
5. **安全优先** — 不注入游戏进程、不修改游戏内存，仅通过标准输入模拟（鼠标/键盘）与屏幕截图实现

---

## 二、功能全景

### 2.1 能力矩阵

```
┌─────────────────────────────────────────────────────────────────┐
│                    NagaAgent 游戏交互能力栈                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐    │
│  │ 游戏识别  │   │ 攻略问答  │   │ 游戏操控  │   │ 角色陪伴  │    │
│  │ (看)     │   │ (答)     │   │ (做)     │   │ (陪)     │    │
│  └────┬─────┘   └────┬─────┘   └────┬─────┘   └────┬─────┘    │
│       │              │              │              │            │
│  ┌────▼─────────────▼──────────────▼──────────────▼────┐      │
│  │              统一上下文引擎 (Unified Context)          │      │
│  │  屏幕状态 + 对话历史 + 攻略知识 + 操作记录 = 全局感知   │      │
│  └──────────────────────────────────────────────────────┘      │
│                                                                 │
│  ┌──────────────────────────────────────────────────────┐      │
│  │                   基础设施层                           │      │
│  │  视觉模型 │ OCR │ 模板匹配 │ RAG │ 知识图谱 │ TTS    │      │
│  └──────────────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 功能清单

| 编号 | 功能 | 阶段 | 优先级 | 描述 |
|------|------|------|--------|------|
| F-01 | 屏幕截图与预处理 | P0 | 必须 | DPI 感知、多显示器、区域截图、DirectX 兼容 |
| F-02 | 游戏识别与场景判断 | P1 | 必须 | 自动识别当前运行的游戏及所处界面/场景 |
| F-03 | 三层视觉感知 | P0/P1 | 必须 | 模板匹配 → OCR → AI 视觉，逐级升级 |
| F-04 | 元素定位与坐标解析 | P0 | 必须 | 文本定位、图像定位、AI 坐标提取 |
| F-05 | 鼠标/键盘操作执行 | P0 | 必须 | 点击、拖拽、滚动、按键、组合键 |
| F-06 | 操作验证与纠错 | P1 | 必须 | 截图对比验证操作结果，失败自动重试 |
| F-07 | 多步骤任务编排 | P1 | 必须 | 任务分解、依赖追踪、状态机驱动 |
| F-08 | 攻略问答（文字） | P1 | 必须 | 融合攻略智能体的 RAG 检索与流式回答 |
| F-09 | 攻略问答（视觉） | P1 | 高 | 用户截图/实时画面 + 文字提问，多模态回答 |
| F-10 | 上下文感知攻略 | P2 | 高 | 根据当前游戏画面自动判断用户可能需要的攻略 |
| F-11 | 代操模式 | P1 | 必须 | 用户授权后，NagaAgent 自主操作游戏完成指定任务 |
| F-12 | 实时状态播报 | P1 | 高 | 代操过程中 Live2D 角色语音/文字播报当前进度 |
| F-13 | 游戏配置模板 | P2 | 中 | 预设各游戏的 UI 模板、按钮位置、常用流程 |
| F-14 | 异常处理与人工接管 | P1 | 必须 | 连续失败时暂停操作，通知用户并支持一键接管 |
| F-15 | 游戏脚本系统集成 | P1 | 高 | 非大模型判断的固定流程场景，复用游戏自身的脚本/宏系统，降低延迟与成本 |

---

## 三、系统架构

### 3.1 整体架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                         NagaAgent 主进程                             │
│                                                                     │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────────┐    │
│  │   UI 层        │  │  API Server    │  │  Agent Server      │    │
│  │  PyQt5+Live2D  │  │  :8000         │  │  :8001             │    │
│  │                │  │                │  │                    │    │
│  │ - 对话窗口     │  │ - /chat        │  │ - 任务调度器       │    │
│  │ - 游戏叠加层   │  │ - /chat/stream │  │ - 工具管理器       │    │
│  │ - 操控面板     │  │ - /documents   │  │ - 屏幕操控Agent    │    │
│  │ - 状态指示器   │  │ - /game/*  NEW │  │ - 攻略桥接Agent    │    │
│  └───────┬────────┘  └───────┬────────┘  └───────┬────────────┘    │
│          │                   │                   │                  │
│  ┌───────▼───────────────────▼───────────────────▼──────────┐      │
│  │              MCP Server :8003 (工具执行层)                 │      │
│  │                                                          │      │
│  │  [既有工具]              [新增工具]                        │      │
│  │  agent_vision            agent_game_vision    NEW        │      │
│  │  agent_online_search     agent_game_control   NEW        │      │
│  │  agent_crawl4ai          agent_game_guide     NEW        │      │
│  │  agent_playwright        agent_game_monitor   NEW        │      │
│  │  agent_memory            ...                             │      │
│  └──────────────────────────────────────────────────────────┘      │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────┐      │
│  │                TTS Server :5048                           │      │
│  │  语音合成 + Live2D 口型同步                                │      │
│  └──────────────────────────────────────────────────────────┘      │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────┐      │
│  │              攻略引擎 (Guide Engine) NEW                  │      │
│  │                                                          │      │
│  │  ┌─────────┐ ┌──────────┐ ┌─────────┐ ┌────────────┐   │      │
│  │  │RAG检索  │ │知识图谱   │ │计算引擎  │ │Prompt管理  │   │      │
│  │  │ChromaDB │ │Neo4j     │ │伤害/配队 │ │YAML/游戏   │   │      │
│  │  └─────────┘ └──────────┘ └─────────┘ └────────────┘   │      │
│  └──────────────────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────────────────┘
```

### 3.2 屏幕视觉识别模块架构

```
agentserver/agent_computer_control/     (重构后目录结构)
├── screen_agent.py          # 顶层编排器：任务规划、去重、独占锁、主循环
├── capture.py               # 截图引擎：mss 库、DPI 感知、多显示器、区域截取
├── vision.py                # 三层感知：模板匹配 → OCR → AI 视觉模型
├── action.py                # 操作执行：ctypes(user32.dll) + pyautogui 双模式
├── verifier.py              # 操作验证：像素差异 + AI 对比（分层节省成本）
├── state.py                 # 状态追踪：多步骤上下文、操作历史
├── monitor.py               # 实时监控：后台画面扫描、状态变化检测
├── game_detector.py         # 游戏识别：窗口标题 + 进程名 + 视觉特征 NEW
├── game_templates/          # 游戏 UI 模板库 NEW
│   ├── arknights/
│   ├── genshin_impact/
│   ├── honkai_star_rail/
│   └── ...
└── models.py                # 数据模型定义
```

### 3.3 三层视觉感知管线

```
输入：屏幕截图 + 用户指令（如 "点击开始战斗按钮"）
                    │
                    ▼
    ┌───────────────────────────────┐
    │  第一层：模板匹配 (< 100ms)    │
    │  OpenCV matchTemplate         │
    │  - 查找游戏模板库中的已知按钮   │
    │  - 置信度 > 0.85 → 直接返回    │
    └───────────┬───────────────────┘
                │ 未匹配
                ▼
    ┌───────────────────────────────┐
    │  第二层：OCR 文字识别 (< 500ms) │
    │  Tesseract / PaddleOCR        │
    │  - 识别画面中所有文字及位置     │
    │  - 文字匹配指令中的目标         │
    │  - 匹配成功 → 返回文字中心坐标  │
    └───────────┬───────────────────┘
                │ 未匹配
                ▼
    ┌───────────────────────────────┐
    │  第三层：AI 视觉模型 (1-3s)    │
    │  Claude / Gemini / GLM-4.5V   │
    │  - 发送截图 + 结构化 Prompt     │
    │  - 要求返回目标元素坐标(JSON)   │
    │  - 支持复杂场景理解             │
    └───────────┬───────────────────┘
                │
                ▼
    ┌───────────────────────────────┐
    │  坐标归一化 & 验证              │
    │  - 坐标合法性检查               │
    │  - 屏幕边界约束                 │
    │  - DPI 缩放换算                 │
    └───────────────────────────────┘
                │
                ▼
            返回坐标
```

### 3.4 操作验证分层策略

```python
# 验证策略伪代码
def verify_action(before_screenshot, after_screenshot, expected_change):
    diff = pixel_diff(before, after)

    if diff > 0.05:          # 画面明显变化
        return SUCCESS        # 免费，< 50ms

    if diff < 0.005:         # 画面几乎没变
        return FAILURE        # 免费，< 50ms

    # 模糊区间，需要 AI 判断
    return ai_verify(before, after, expected_change)  # 约 20% 的情况
```

**成本效益**：约 80% 的验证通过像素差异免费完成，仅 ~20% 需要 AI 模型调用。

---

## 四、攻略智能体融合方案

### 4.1 现状分析

**攻略智能体（独立项目）现有能力：**

| 能力 | 实现方式 | 成熟度 |
|------|---------|--------|
| 9 款游戏攻略问答 | RAG（ChromaDB/Milvus 向量检索 + Neo4j 图谱） | 成熟 |
| 流式回答 | SSE 推流 | 成熟 |
| 多模型支持 | Gemini 2.5 Pro/Flash + 豆包 | 成熟 |
| 意图路由 | QueryRouter 分类（WIKI/CALCULATION/GUIDE） | 成熟 |
| 游戏专属 Prompt | YAML 配置（每游戏独立） | 成熟 |
| 伤害/配队计算 | CalculationService | 成熟 |
| 图片识别问答 | Gemini 多模态（base64 图片输入） | 成熟 |
| QQ Bot 接入 | OneBot11 协议 | 成熟 |
| 用户系统 | JWT 认证 + 会员等级 | 成熟 |

**NagaAgent 当前缺失：**
- 无游戏攻略知识库
- 无 RAG 向量检索（有 GRAG 图谱但不含游戏数据）
- 无游戏专属 Prompt 体系
- 无意图路由（游戏查询 vs 日常对话 vs 操控指令）

### 4.2 融合策略：内嵌式服务集成

**核心思路**：不是把攻略智能体的前端塞进 NagaAgent，而是将其**后端能力作为内部服务**接入 NagaAgent 的 MCP 工具生态，由 NagaAgent 的对话系统统一调度。

```
用户对话输入（文字/语音/截图）
        │
        ▼
┌────────────────────────────┐
│  NagaAgent API Server      │
│  意图分析增强版             │
│                            │
│  "这关怎么打" → 攻略意图    │
│  "帮我自动刷本" → 操控意图  │
│  "今天天气" → 日常意图      │
│  "这个怪弱什么" → 攻略+视觉 │
└──────────┬─────────────────┘
           │
     ┌─────┼──────────┐
     │     │          │
     ▼     ▼          ▼
  日常处理  攻略引擎   操控引擎
  (既有)   (融合)     (新建)
```

### 4.3 攻略引擎集成架构

```
NagaAgent/
├── guide_engine/                          NEW — 攻略引擎
│   ├── __init__.py
│   ├── guide_service.py                   # 攻略服务主入口
│   ├── rag_service.py                     # RAG 检索服务
│   │   ├── vector_search()                # 向量检索（ChromaDB）
│   │   ├── graph_query()                  # 图谱查询（Neo4j）
│   │   └── merge_context()                # 上下文合并
│   ├── query_router.py                    # 意图路由器
│   │   ├── detect_intent()                # 意图识别
│   │   ├── extract_entities()             # 实体抽取（角色名、技能等）
│   │   └── classify_mode()                # 模式分类
│   ├── calculation_service.py             # 游戏计算引擎
│   ├── prompt_manager.py                  # Prompt 管理
│   │   └── game_prompts/                  # 游戏 Prompt 配置
│   │       ├── arknights.yaml
│   │       ├── genshin_impact.yaml
│   │       ├── honkai_star_rail.yaml
│   │       ├── wuthering_waves.yaml
│   │       ├── zenless_zone_zero.yaml
│   │       ├── punishing_gray_raven.yaml
│   │       ├── uma_musume.yaml
│   │       └── kantai_collection.yaml
│   ├── knowledge_base/                    # 知识库数据
│   │   ├── embeddings/                    # 向量索引
│   │   └── import_scripts/                # 数据导入脚本
│   └── models.py                          # 数据模型
│
├── mcpserver/
│   ├── agent_game_guide/                  NEW — 攻略 MCP 工具
│   │   ├── __init__.py
│   │   ├── agent_game_guide.py            # MCP 工具注册
│   │   └── guide_tools.py                 # 工具实现
│   │       ├── ask_guide()                # 文字攻略查询
│   │       ├── ask_guide_with_screenshot()# 截图+文字攻略查询
│   │       ├── get_team_recommendation()  # 配队推荐
│   │       ├── calculate_damage()         # 伤害计算
│   │       └── get_game_news()            # 游戏资讯
```

### 4.4 数据流：用户边玩边问场景

```
场景：用户正在玩明日方舟，遇到一关打不过

用户："这关好难啊，怎么打？"
        │
        ▼
┌──────────────────────────────────────────────────┐
│ Step 1: 意图分析                                  │
│   - NagaAgent 检测到当前运行游戏 = 明日方舟        │
│   - 语义分析 → 攻略意图                            │
│   - 触发攻略引擎                                   │
└──────────────────┬───────────────────────────────┘
                   ▼
┌──────────────────────────────────────────────────┐
│ Step 2: 上下文采集                                │
│   - 自动截取当前游戏画面                            │
│   - AI 视觉模型识别关卡信息（关卡名、敌人、地形）    │
│   - 提取结构化信息：                                │
│     { game: "arknights",                          │
│       stage: "7-18",                              │
│       enemies: ["重装卫士", "术师领主"],            │
│       terrain: "高台多" }                          │
└──────────────────┬───────────────────────────────┘
                   ▼
┌──────────────────────────────────────────────────┐
│ Step 3: 攻略检索                                  │
│   - 向量检索：搜索 "7-18 攻略" 相关文档             │
│   - 图谱查询：查找克制关系、推荐干员                 │
│   - 计算引擎：计算所需练度                          │
└──────────────────┬───────────────────────────────┘
                   ▼
┌──────────────────────────────────────────────────┐
│ Step 4: 融合回答                                  │
│   - System Prompt (arknights.yaml)                │
│   - 检索上下文 + 视觉分析结果                      │
│   - LLM 生成流式回答                               │
│   - Live2D 角色语音播报                            │
└──────────────────┬───────────────────────────────┘
                   ▼
NagaAgent（语音+文字）：
"这关是 7-18，推荐用银灰 S3 守右路高台，配合
 安洁莉娜减速。左路放一个重装挡住就行，我可以
 帮你摆好干员位置，要我来操作吗？"
        │
        ▼ （用户说"好"）
        │
┌──────────────────────────────────────────────────┐
│ Step 5: 切换代操模式                              │
│   - 进入操控引擎                                   │
│   - 根据攻略拆解操作步骤                            │
│   - 逐步执行：选择干员 → 拖放到位置 → 调整朝向      │
│   - 每步验证结果                                   │
│   - Live2D 播报进度                                │
└──────────────────────────────────────────────────┘
```

### 4.5 攻略助手输入扩展

攻略智能体原本仅接收**文字输入**，融合后需支持以下输入模式：

| 输入模式 | 来源 | 处理方式 |
|----------|------|---------|
| **纯文字** | 用户在 NagaAgent 对话框输入 | 直接传入攻略引擎 QueryRouter |
| **语音转文字** | 用户语音输入 → ASR → 文字 | ASR 转写后同纯文字路径 |
| **截图+文字** | 用户手动截图或自动截取 | 图片送 AI 视觉提取信息 → 拼接文字查询 |
| **纯视觉** | 自动监控检测到新场景 | 视觉模型分析 → 生成描述 → 自动检索相关攻略 |
| **操控上下文** | 代操过程中遇到未知情况 | 截图 + 当前操作状态 → 请求攻略引擎决策 |

**关键改造点**：

```python
# 原攻略智能体入口（仅文字）
class ChatRequest(BaseModel):
    content: str
    images: Optional[List[str]] = None  # 已支持图片但仅透传给 LLM

# 融合后入口（多模态 + 上下文感知）
class GuideRequest(BaseModel):
    content: str                                    # 用户问题文字
    images: Optional[List[str]] = None              # 手动上传的图片
    auto_screenshot: bool = False                   # 是否自动截取当前画面
    game_context: Optional[GameContext] = None       # 游戏上下文（自动注入）
    operation_context: Optional[OpContext] = None    # 操控上下文（代操时）

class GameContext(BaseModel):
    game_id: str                    # 游戏标识 (arknights, genshin, etc.)
    scene: Optional[str] = None     # 当前场景 (main_menu, battle, gacha, etc.)
    stage: Optional[str] = None     # 关卡标识
    detected_elements: Optional[List[str]] = None   # 画面中检测到的元素
    screenshot_base64: Optional[str] = None         # 当前画面截图

class OpContext(BaseModel):
    task_name: str                  # 当前任务名
    current_step: int               # 当前步骤
    total_steps: int                # 总步骤数
    history: List[StepRecord]       # 操作历史
    status: str                     # running / paused / failed
```

---

## 五、游戏识别与操控

### 5.1 游戏识别机制

```
┌─────────────────────────────────────────────┐
│           游戏识别器 (GameDetector)           │
│                                             │
│  第一层：进程/窗口识别（< 10ms）              │
│  - 枚举前台窗口进程名                        │
│  - 匹配已知游戏进程名表                       │
│    arknights.exe → 明日方舟                   │
│    YuanShen.exe  → 原神                      │
│    StarRail.exe  → 崩坏：星穹铁道             │
│  - 匹配成功 → 确定游戏                       │
│                                             │
│  第二层：窗口标题匹配（< 10ms）               │
│  - 读取窗口标题文本                           │
│  - 模糊匹配游戏名关键词                       │
│  - 适用于模拟器/云游戏等场景                   │
│                                             │
│  第三层：视觉特征识别（< 2s）                  │
│  - 截取画面送 AI 视觉模型                     │
│  - "这是什么游戏的画面？"                     │
│  - 适用于未知进程名的情况                      │
└─────────────────────────────────────────────┘
```

**游戏注册表（可扩展）**：

```yaml
# game_templates/game_registry.yaml
games:
  arknights:
    display_name: "明日方舟"
    process_names: ["arknights.exe", "明日方舟.exe"]
    window_keywords: ["明日方舟", "Arknights"]
    guide_id: "arknights"            # 关联攻略引擎的游戏ID
    supported_operations:
      - daily_stage                   # 日常刷本
      - base_management               # 基建换班
      - recruitment                    # 公开招募
      - gacha_pull                     # 抽卡
      - navigate_menu                  # 菜单导航
    scene_templates:
      main_menu: "templates/arknights/main_menu.png"
      battle: "templates/arknights/battle.png"
      base: "templates/arknights/base.png"

  genshin_impact:
    display_name: "原神"
    process_names: ["YuanShen.exe", "GenshinImpact.exe"]
    window_keywords: ["原神", "Genshin Impact"]
    guide_id: "genshin-impact"
    supported_operations:
      - daily_commission               # 每日委托
      - resin_spend                    # 刷体力
      - expedition                     # 探索派遣
      - navigate_menu
    # ...
```

### 5.2 游戏操控模式

#### 5.2.1 支持的游戏类型

| 游戏类型 | 支持程度 | 说明 |
|----------|---------|------|
| **回合制策略** | 完全支持 | 明日方舟、崩铁回合战斗 — 无时间压力，可逐步决策 |
| **慢节奏 RPG** | 完全支持 | 原神探索/菜单操作、日常委托 — 操作间隔充裕 |
| **卡牌游戏** | 完全支持 | 出牌、选择等离散操作 |
| **自动战斗** | 完全支持 | 只需开始/暂停/选择，战斗自动进行 |
| **即时战斗** | 不支持 | 需要 < 100ms 反应的操作超出视觉模型延迟 |
| **反作弊游戏** | 不支持 | EAC/BattleEye/Vanguard 会拦截输入模拟 |

#### 5.2.2 操控流程状态机

```
                    ┌──────────┐
                    │  IDLE    │ 待命状态
                    └────┬─────┘
                         │ 用户指令 / 自动触发
                         ▼
                    ┌──────────┐
              ┌────│ PLANNING │ 任务规划
              │    └────┬─────┘
              │         │ 规划完成
              │         ▼
              │    ┌──────────┐
              │    │EXECUTING │ ← ─ ─ ─ ─ ─ ─ ─ ┐
              │    └────┬─────┘                   │
              │         │ 单步完成                  │
              │         ▼                          │
              │    ┌──────────┐     验证通过       │
              │    │VERIFYING │ ─ ─ ─ ─ ─ ─ ─ ─ ─┘
              │    └────┬─────┘     → 下一步
              │         │ 验证失败
              │         ▼
              │    ┌──────────┐
              │    │ RETRYING │ 重试（最多3次）
              │    └────┬─────┘
              │         │ 重试耗尽
              │         ▼
              │    ┌──────────┐
              ├───│ PAUSED   │ 暂停，等待用户
              │    └────┬─────┘
              │         │ 用户选择
              │    ┌────┴────┐
              │    ▼         ▼
              │  继续     ┌──────────┐
              │  执行     │ ABORTED  │ 任务中止
              │           └──────────┘
              │
              │    所有步骤完成
              │         │
              │         ▼
              │    ┌──────────┐
              └──→│COMPLETED │ 任务完成
                   └──────────┘
```

#### 5.2.3 代操任务示例

```yaml
# 明日方舟 - 自动刷本任务
task: arknights_auto_stage
name: "明日方舟自动刷本"
description: "自动重复刷指定关卡，消耗理智"
parameters:
  stage_id: "1-7"          # 关卡编号
  repeat_count: 10         # 重复次数
  use_potion: false        # 是否使用理智药

steps:
  - id: 1
    action: navigate
    target: "终端"
    description: "点击主界面终端按钮"
    verify: "进入关卡选择界面"

  - id: 2
    action: navigate
    target: "{stage_id}"
    description: "选择目标关卡"
    verify: "进入关卡详情页"

  - id: 3
    action: click
    target: "代理指挥"
    description: "开启代理指挥模式"
    verify: "代理指挥开关变为开启状态"

  - id: 4
    action: click
    target: "开始行动"
    description: "开始战斗"
    verify: "进入战斗/加载画面"

  - id: 5
    action: wait_for
    target: "行动结束"
    timeout: 300              # 最长等待5分钟
    description: "等待战斗结束"
    verify: "出现结算画面"

  - id: 6
    action: click
    target: "任意位置"
    description: "点击跳过结算"
    verify: "回到关卡详情页"

  - id: 7
    action: loop
    goto_step: 4
    condition: "repeat_count > 0"
    description: "循环刷本直到次数用完"
```

### 5.3 游戏脚本系统集成

并非所有操作都需要大模型判断。很多游戏场景是**确定性、重复性、无需理解**的固定流程，对这些场景使用视觉模型既慢又贵还不稳定。更合理的做法是：**能用脚本就用脚本，脚本搞不定的再上大模型。**

#### 5.3.1 适用场景

| 场景类型 | 为什么不需要大模型 | 脚本方案 |
|----------|------------------|---------|
| **固定坐标点击流程** | UI 位置不变（如每日签到弹窗的"确认"按钮） | 坐标脚本：按序点击固定坐标，间隔固定等待时间 |
| **键盘宏序列** | 操作序列固定（如原神烹饪：E→等待→点击） | 键盘宏：预定义按键序列 + 延时 |
| **循环操作** | 重复同一动作 N 次（如刷本点"再来一次"） | 循环脚本：单步动作 × 重复次数 |
| **菜单导航** | 路径固定（主界面→终端→关卡选择） | 导航脚本：预定义的点击坐标路径 |
| **资源收取** | 定时点击固定位置（如基建收菜） | 定时脚本：坐标 + 定时触发 |
| **体力/行动力消耗** | 重复出击直到体力耗尽 | 循环脚本 + OCR 检测体力数值作为终止条件 |

#### 5.3.2 脚本与大模型的协作分工

```
用户指令："帮我把体力刷完"
        │
        ▼
┌─────────────────────────────────────┐
│  决策层（大模型参与）                │
│                                     │
│  1. 理解用户意图 → "消耗体力刷本"    │  ← 大模型
│  2. 判断当前游戏/场景               │  ← 游戏识别器
│  3. 选择执行策略 → "使用脚本流程"    │  ← 大模型
│  4. 确定参数：刷哪个本、几次         │  ← 大模型 + 攻略引擎
└──────────┬──────────────────────────┘
           │
           ▼
┌─────────────────────────────────────┐
│  执行层（脚本执行，不调用大模型）     │
│                                     │
│  for i in range(repeat_count):      │
│    click(x=1650, y=500)  # 开始行动  │
│    wait(180)              # 等战斗   │
│    click(x=960, y=800)   # 跳结算   │
│    wait(2)                          │
│                                     │
│  异常检测：                          │
│    if 画面未变化 > 超时阈值:          │
│      → 升级为大模型分析当前状态       │  ← 仅异常时才用大模型
└─────────────────────────────────────┘
```

**核心原则：大模型管"想"（决策/规划/异常处理），脚本管"做"（执行/重复/等待）。**

#### 5.3.3 脚本配置格式

```yaml
# game_templates/arknights/scripts/daily_stage.yaml
script: arknights_daily_stage
name: "日常刷本脚本"
trigger: manual          # manual / scheduled / auto
requires_model: false    # 执行过程不需要大模型

params:
  stage_button: [1650, 500]     # "开始行动"按钮坐标
  skip_button: [960, 800]       # 结算跳过点击区域
  battle_timeout: 180            # 战斗最长等待秒数
  repeat_count: 10

steps:
  - action: click
    coords: "{stage_button}"
    wait_after: 3

  - action: wait_for_change
    timeout: "{battle_timeout}"
    fallback: model_analyze       # 超时则升级为大模型分析

  - action: click
    coords: "{skip_button}"
    wait_after: 2

  - action: ocr_check
    region: [100, 50, 300, 100]   # 体力数值区域
    pattern: "\\d+/\\d+"          # 匹配 "23/135" 格式
    stop_if: "current < cost"     # 体力不够时停止

  - action: loop
    goto: 0
    times: "{repeat_count}"

# 异常处理
on_error:
  - condition: screen_unchanged_10s
    action: escalate_to_model     # 画面卡住 → 交给大模型判断
  - condition: unexpected_popup
    action: escalate_to_model     # 意外弹窗 → 交给大模型判断
  - condition: network_error_popup
    action: click_retry_button    # 网络错误 → 脚本自行点重试
```

#### 5.3.4 大模型 vs 脚本决策矩阵

| 判断维度 | 用脚本 | 用大模型 |
|----------|--------|---------|
| UI 位置是否固定 | 固定 | 动态/不确定 |
| 操作序列是否确定 | 确定 | 需要根据画面决策 |
| 是否需要理解画面内容 | 不需要 | 需要（如识别敌人类型） |
| 是否有现成坐标/模板 | 有 | 没有 |
| 执行频率 | 高频/日常 | 低频/首次 |
| 容错要求 | 低（重试即可） | 高（错误操作有后果） |

**预期收益**：日常任务中约 60-70% 的操作步骤可脚本化，仅在决策点和异常处理时调用大模型。这将：
- 降低 AI API 调用成本约 **60%**
- 减少执行延迟（脚本步骤 < 100ms vs AI 步骤 1-3s）
- 提高稳定性（脚本不存在"模型幻觉"问题）

---

### 5.4 安全与边界

| 安全措施 | 说明 |
|----------|------|
| **无进程注入** | 不注入游戏进程内存，不修改游戏文件 |
| **标准输入** | 仅使用 OS 级鼠标/键盘模拟（user32.dll / pyautogui） |
| **操作限速** | 每次操作间最小间隔 500ms，避免异常高频操作 |
| **用户确认** | 首次代操需用户明确授权，敏感操作（如消耗付费道具）二次确认 |
| **紧急中断** | 用户按下预设快捷键（默认 Esc）立即停止所有操作 |
| **操作日志** | 每次操作截图留档，可回溯审计 |
| **反作弊声明** | 检测到反作弊游戏时主动提示不支持，不尝试绕过 |

---

## 六、视觉模型策略

### 6.1 多模型级联

```
┌─────────────────────────────────────────────────┐
│              视觉模型调度策略                      │
│                                                 │
│  简单任务（明确按钮/文字）                        │
│  → Gemini Flash（快速 + 低成本）                 │
│                                                 │
│  复杂任务（多步骤/不确定）                        │
│  → Claude Sonnet（最强 Computer Use 能力）       │
│                                                 │
│  中等任务 / 中文优化                              │
│  → GLM-4.5V / Qwen-VL（中文理解优势）           │
│                                                 │
│  API 故障 / 超时                                 │
│  → 自动切换下一模型                              │
│                                                 │
│  所有模型失败                                    │
│  → 降级为 OCR + 模板匹配                        │
└─────────────────────────────────────────────────┘
```

### 6.2 AI 视觉 Prompt 规范

现有 AI Prompt 仅 8 行且无格式约束，需重构为结构化 Prompt：

```
你是一个桌面 UI 元素定位助手。根据用户描述的目标元素，在截图中找到它的精确位置。

## 输入
- 截图：当前屏幕画面
- 目标描述：用户希望操作的 UI 元素

## 输出要求
严格返回以下 JSON 格式，不要包含其他文字：
{
  "found": true/false,
  "element_description": "你看到的目标元素描述",
  "x": 归一化横坐标 (0-1000),
  "y": 归一化纵坐标 (0-1000),
  "confidence": 置信度 (0.0-1.0),
  "alternatives": [
    {"description": "备选元素", "x": ..., "y": ..., "confidence": ...}
  ],
  "scene_description": "当前画面场景概述"
}

## 注意事项
1. 坐标使用归一化 0-1000 范围，左上角为 (0,0)，右下角为 (1000,1000)
2. 如果找不到目标，found 设为 false，并在 scene_description 中描述你看到了什么
3. 如果有多个相似元素，将其他候选放入 alternatives
4. confidence < 0.5 时 found 应为 false
```

### 6.3 辅助增强手段

除 AI 视觉模型外，以下手段可提高识别精准度：

| 手段 | 作用 | 适用场景 |
|------|------|---------|
| **模板匹配** | 快速精准定位已知 UI 元素 | 固定按钮、图标、菜单项 |
| **OCR 文字识别** | 定位文字类元素 | 按钮文字、菜单文字、数值 |
| **颜色/轮廓检测** | 辅助区分元素状态 | 按钮高亮/灰态、血条颜色 |
| **坐标缓存** | 同一界面同一元素复用上次坐标 | 短时间内重复操作同一界面 |
| **UI 布局先验** | 游戏 UI 通常有固定布局规律 | 配合模板减少搜索范围 |
| **多帧对比** | 对比连续截图差异定位动态元素 | 动画元素、弹窗检测 |
| **分辨率归一化** | 统一坐标空间消除分辨率差异 | 多设备/多分辨率兼容 |

---

## 七、开源项目功能复用总览

本次功能更新涉及两个可复用的开源/已有项目：

- **N.E.K.O.（Xiao8）** — 路径 `C:\naga\屏幕识别\Xiao8\`，Steam 已发布的桌面助手，核心能力在**屏幕视觉与操控**
- **攻略智能体** — 路径 `C:\攻略智能体 (2)\`，完整的游戏攻略问答系统，核心能力在**游戏知识检索与问答**

以下按功能维度逐项说明每项能力**从哪里来、怎么用、要改什么**。

### 7.1 功能复用全景表

| 功能 | 来源项目 | 复用方式 | 需要的改造 | 目标位置（NagaAgent） |
|------|---------|---------|-----------|---------------------|
| **屏幕截图（DPI 感知）** | N.E.K.O. | 直接复用 | 无需修改 | `capture.py` |
| **DPI 缩放适配** | N.E.K.O. | 直接复用 | 无需修改 | `action.py` |
| **AI 截图分析（送图给视觉模型）** | N.E.K.O. | 直接复用 | ConfigManager → 直接传参 | `vision.py` |
| **指令去重（避免重复截图分析）** | N.E.K.O. | 直接复用 | ConfigManager → 依赖注入 | `screen_agent.py` |
| **意图分析（判断是否需要屏幕操作）** | N.E.K.O. | 直接复用 | ConfigManager → 依赖注入 | `screen_agent.py` |
| **视觉 Prompt 模板** | N.E.K.O. | 参考改写 | 适配 NagaAgent 场景，增加 JSON 输出约束 | `vision.py` |
| **RAG 向量检索（游戏攻略）** | 攻略智能体 | 整体移植 | 改为 NagaAgent 内部服务，去除独立 Web 层 | `guide_engine/rag_service.py` |
| **ChromaDB 向量库管理** | 攻略智能体 | 整体移植 | 配置路径对齐到 NagaAgent config.json | `guide_engine/rag_service.py` |
| **Neo4j 知识图谱查询（游戏关系）** | 攻略智能体 | 整体移植 | 与 NagaAgent 已有 GRAG 的 Neo4j 实例合并 | `guide_engine/rag_service.py` |
| **意图路由器（QueryRouter）** | 攻略智能体 | 整体移植 | 扩展为三类意图：日常/攻略/操控 | `guide_engine/query_router.py` |
| **游戏专属 Prompt（9 款游戏 YAML）** | 攻略智能体 | 直接复用 | 无需修改，直接搬迁 | `guide_engine/game_prompts/` |
| **伤害/配队计算引擎** | 攻略智能体 | 整体移植 | 去除 HTTP 层，改为函数调用 | `guide_engine/calculation_service.py` |
| **流式回答（SSE）** | 攻略智能体 | 参考复用 | NagaAgent 已有流式架构，对齐数据格式即可 | `apiserver/api_server.py` |
| **多模态图片问答** | 攻略智能体 | 直接复用 | 已支持 base64 图片输入，保持原逻辑 | `guide_engine/guide_service.py` |
| **Embedding 模型管理** | 攻略智能体 | 整体移植 | sentence-transformers 加载逻辑搬迁 | `guide_engine/rag_service.py` |
| **QQ Bot 攻略接口** | 攻略智能体 | 可选移植 | 若需要保留 QQ Bot 通道则移植 | `mcpserver/agent_game_guide/` |
| **操作验证（像素差异+AI）** | 无（新建） | 新开发 | N.E.K.O. 和攻略智能体均无此功能 | `verifier.py` |
| **多步骤状态追踪** | 无（新建） | 新开发 | 两个项目均无此功能 | `state.py` |
| **实时画面监控** | 无（新建） | 新开发 | 两个项目均无此功能 | `monitor.py` |
| **游戏识别（进程/窗口/视觉）** | 无（新建） | 新开发 | 两个项目均无此功能 | `game_detector.py` |
| **代操任务状态机** | 无（新建） | 新开发 | 两个项目均无此功能 | `screen_agent.py` |
| **游戏脚本系统** | 无（新建） | 新开发 | 固定流程用脚本执行，不走大模型 | `game_templates/*/scripts/` |
| **模板匹配（OpenCV）** | NagaAgent 自有 | 修复增强 | 已有框架但 find_element_by_image 未实现 | `vision.py` |
| **OCR 文字定位** | NagaAgent 自有 | 修复增强 | 已有 Tesseract 但 find_element_by_text 未实现 | `vision.py` |

### 7.2 N.E.K.O. 逐模块复用详解

来源路径：`C:\naga\屏幕识别\Xiao8\`，可直接复用约 **700 行**代码。

| 源文件 | 复用率 | 行数 | 借用的能力 | NagaAgent 目标文件 | 改造说明 |
|--------|--------|------|-----------|-------------------|---------|
| `brain/deduper.py` | 91% | 93 | **指令去重**：相同/近似的屏幕操作指令在短时间内不重复执行，避免 AI 重复截图分析浪费 token | `screen_agent.py` | 将 `ConfigManager.get()` 调用替换为构造函数依赖注入 |
| `utils/screenshot_utils.py` | 99% | 221 | **AI 截图分析**：截取屏幕画面 → base64 编码 → 发送给视觉模型 → 解析返回坐标。包含完整的截图裁剪、缩放、编码逻辑 | `vision.py` | 仅将 ConfigManager 替换为直接传入 api_key/model 参数 |
| `brain/analyzer.py` | 97% | 98 | **意图分析**：判断用户指令是否需要屏幕操作（vs 纯对话/工具调用），决定是否启动视觉管线 | `screen_agent.py` | 同上 ConfigManager 替换 |
| `brain/computer_use.py` → `_ScaledPyAutoGUI` 类 | 100% | 55 | **DPI 适配封装**：在高 DPI 环境下正确缩放 pyautogui 的鼠标坐标，避免点击偏移 | `action.py` | 零修改直接使用 |
| `brain/computer_use.py` → DPI 初始化代码 | 100% | 12 | **系统 DPI 感知声明**：调用 `ctypes.windll.shcore.SetProcessDpiAwareness(2)` 确保截图不受系统缩放影响 | `capture.py` | 零修改直接使用 |
| `brain/computer_use.py` → `scale_screen_dimensions()` | 100% | 6 | **屏幕尺寸缩放**：获取真实物理分辨率（而非逻辑分辨率） | `capture.py` | 零修改直接使用 |
| `config/prompts_sys.py` | 参考 | ~70 | **视觉 Prompt 参考**：N.E.K.O. 给视觉模型的 system prompt，描述如何分析屏幕、返回坐标 | `vision.py` | 不直接复用，参考其思路重写为结构化 JSON 约束版本 |

**N.E.K.O. 不具备、需要新建的能力：**
- OpenCV 模板匹配（N.E.K.O. 没有模板匹配，纯依赖 AI 视觉）
- 操作结果验证（N.E.K.O. 执行操作后不验证是否成功）
- 多步骤状态追踪（N.E.K.O. 是单步执行模式）
- 后台实时画面监控
- 游戏自动识别

### 7.3 攻略智能体逐模块复用详解

来源路径：`C:\攻略智能体 (2)\backend\app\`，核心服务层约 **3000+ 行**代码可移植。

| 源文件 | 借用的能力 | NagaAgent 目标文件 | 移植方式 |
|--------|-----------|-------------------|---------|
| `services/llm_service.py` → `RAGService` 类 | **RAG 检索主流程**：接收用户问题 → 意图检测 → 并行检索（向量+图谱+计算） → 上下文合并 → 送 LLM 生成回答 | `guide_engine/rag_service.py` | 剥离 HTTP 层，保留核心检索+合并逻辑。LLM 调用改为走 NagaAgent 的 `llm_service` 统一接口 |
| `services/chroma_service.py` | **ChromaDB 向量检索**：embedding 生成、collection 管理、相似度搜索、知识库索引构建 | `guide_engine/rag_service.py` | 直接移植。配置项（embedding model 路径、collection 名）对齐到 NagaAgent config.json |
| `services/neo4j_service.py` | **游戏知识图谱查询**：角色关系、技能树、配队推荐的图查询 | `guide_engine/rag_service.py` | 移植查询逻辑。Neo4j 连接复用 NagaAgent 已有的 GRAG 实例（同一数据库，新增游戏相关节点） |
| `services/query_router.py` | **意图路由器**：分析用户问题属于 WIKI_ONLY / CALCULATION / FULL / GUIDE 哪种模式，提取实体（角色名、技能编号等） | `guide_engine/query_router.py` | 直接移植。扩展一个新意图类别 `OPERATION`（用户想让 NagaAgent 代操时） |
| `services/prompt_service.py` | **游戏 Prompt 管理**：加载 YAML 配置、动态组装 system prompt、管理每游戏的检索参数 | `guide_engine/prompt_manager.py` | 直接移植。去除数据库 GameConfig 模型依赖，改为纯 YAML 文件驱动 |
| `prompts/*.yaml`（9 个文件） | **9 款游戏的专属 Prompt 配置**：包含游戏描述、角色命名规则、实体识别模式、检索阈值、system prompt 模板 | `guide_engine/game_prompts/` | **零修改直接搬迁**，文件原封不动复制 |
| `services/calculation_service.py` | **通用游戏计算引擎**：伤害计算、属性换算等数值逻辑 | `guide_engine/calculation_service.py` | 直接移植。去除 FastAPI 依赖，改为纯函数调用 |
| `services/kantai_calculation_service.py` | **舰队收藏专用计算**：舰娘属性、制空值等特殊计算 | `guide_engine/calculation_service.py` | 直接移植，作为子模块 |
| `rag/` 目录 | **RAG 管线组件**：chunk 分割、embedding 批处理、索引构建脚本 | `guide_engine/knowledge_base/` | 直接移植。用于初始化和更新攻略知识库 |
| `crawler/` 目录 | **游戏数据爬虫**：从 Wiki/官网抓取游戏数据并入库 | `guide_engine/knowledge_base/import_scripts/` | 可选移植。用于定期更新攻略数据 |
| `api/v1/chat.py` → 流式回答逻辑 | **SSE 流式推送**：逐 chunk 返回 LLM 回答 + 结尾返回引用来源 | `apiserver/api_server.py` | **参考复用**。NagaAgent 已有 SSE 流式架构，对齐 `{type: "content"/"reference"}` 数据格式 |
| `api/v1/qq_bot.py` | **QQ Bot 接入**：OneBot11 协议接收 QQ 消息 → 自动检测游戏 → 返回攻略回答 | `mcpserver/agent_game_guide/` | **可选移植**。如需保留 QQ 渠道则移植 |
| `models/message.py` + `models/conversation.py` | **对话/消息持久化**：PostgreSQL 存储对话历史、消息引用 | — | **不移植**。NagaAgent 已有自己的 session/message 管理系统，保留原有 |
| `models/user.py` + `api/v1/auth.py` | **用户认证系统**：JWT 登录、会员等级、使用限额 | — | **不移植**。NagaAgent 是本地桌面应用，不需要独立用户认证系统 |
| `frontend/` 目录 | **React Web 前端** | — | **不移植**。NagaAgent 使用 PyQt5 桌面 UI，不需要 Web 前端 |

**攻略智能体不具备、需要新建的能力：**
- 屏幕截图/视觉识别（攻略智能体是纯文字+图片上传，不能主动截屏）
- 游戏操作/代操（攻略智能体只回答问题，不操作游戏）
- 实时画面感知（攻略智能体不感知用户当前游戏状态）
- Live2D 角色交互（攻略智能体是 Web 界面，无角色形象）

### 7.4 复用统计总结

```
┌────────────────────────────────────────────────────────────────┐
│                    功能来源分布                                  │
├──────────────┬──────────┬──────────────────────────────────────┤
│  来源        │ 功能数量  │ 典型能力                              │
├──────────────┼──────────┼──────────────────────────────────────┤
│ N.E.K.O.     │ 6 项     │ 截图、DPI 适配、AI 视觉分析、          │
│ (直接复用)   │ ~700 行   │ 去重、意图分析、Prompt 参考           │
├──────────────┼──────────┼──────────────────────────────────────┤
│ 攻略智能体   │ 10 项    │ RAG 检索、向量库、知识图谱、           │
│ (整体移植)   │ ~3000 行  │ 意图路由、Prompt 配置、计算引擎、      │
│              │          │ 数据爬虫、SSE 流式、QQ Bot            │
├──────────────┼──────────┼──────────────────────────────────────┤
│ NagaAgent    │ 2 项     │ OCR 文字定位（修复）、                 │
│ (自有修复)   │          │ 模板匹配（修复）                       │
├──────────────┼──────────┼──────────────────────────────────────┤
│ 全新开发     │ 6 项     │ 操作验证、状态追踪、画面监控、          │
│              │          │ 游戏识别、代操状态机、游戏脚本系统      │
├──────────────┼──────────┼──────────────────────────────────────┤
│ 不移植       │ 3 项     │ 用户认证系统、Web 前端、               │
│ (攻略智能体) │          │ 消息持久化模型（用 NagaAgent 自有）    │
└──────────────┴──────────┴──────────────────────────────────────┘

复用比例：约 70% 的功能可从两个项目借用/移植，约 30% 需全新开发。
全新开发的部分集中在「操控闭环」——验证、状态追踪、监控、任务编排，
这恰好是两个项目都缺失的核心差异化能力。
```

---

## 八、技术实现要点

### 8.1 关键接口定义

#### 屏幕操控 Agent API（新增）

```
POST /agent/game/start_task
  Body: { task_type: "auto_stage", game: "arknights", params: {...} }
  Response: { task_id: "uuid", status: "planning" }

POST /agent/game/stop_task
  Body: { task_id: "uuid" }
  Response: { status: "stopped" }

GET  /agent/game/task_status/{task_id}
  Response: {
    status: "executing",
    current_step: 3,
    total_steps: 7,
    last_screenshot: "base64...",
    message: "正在选择关卡..."
  }

POST /agent/game/screenshot_analyze
  Body: { screenshot: "base64...", question: "画面中有什么按钮？" }
  Response: { analysis: "...", elements: [...] }
```

#### 攻略引擎 API（新增）

```
POST /guide/ask
  Body: GuideRequest { content, images, auto_screenshot, game_context }
  Response: SSE stream — { type: "content"/"reference", data: ... }

POST /guide/ask_sync
  Body: GuideRequest
  Response: { answer: "...", references: [...] }

GET  /guide/games
  Response: [{ id: "arknights", name: "明日方舟", enabled: true }, ...]

POST /guide/knowledge/search
  Body: { game: "arknights", query: "银灰", top_k: 5 }
  Response: { results: [...] }
```

### 8.2 配置扩展

在 NagaAgent `config.json` 中新增以下配置节：

```json
{
  "game_vision": {
    "enabled": true,
    "vision_models": {
      "primary": "gemini-2.0-flash",
      "secondary": "claude-sonnet-4-5-20250929",
      "fallback": "glm-4.5v"
    },
    "auto_switch_on_failure": true,
    "max_retries_per_model": 2,
    "screenshot_library": "mss",
    "template_match_threshold": 0.85,
    "ocr_engine": "paddleocr",
    "coordinate_system": "normalized_1000"
  },

  "game_control": {
    "enabled": true,
    "input_mode": "pyautogui",
    "min_action_interval_ms": 500,
    "max_retries_per_step": 3,
    "max_consecutive_failures": 3,
    "emergency_stop_hotkey": "escape",
    "require_user_confirmation": true,
    "sensitive_actions": ["purchase", "gacha", "delete"],
    "operation_log_screenshots": true
  },

  "guide_engine": {
    "enabled": true,
    "embedding_model": "BAAI/bge-base-zh-v1.5",
    "vector_db": "chromadb",
    "vector_db_path": "./guide_engine/knowledge_base/embeddings",
    "neo4j_uri": "bolt://localhost:7687",
    "neo4j_user": "neo4j",
    "neo4j_password": "",
    "default_top_k": 5,
    "score_threshold": 0.5,
    "llm_provider": "gemini",
    "llm_model_free": "gemini-2.5-flash",
    "llm_model_premium": "gemini-2.5-pro",
    "auto_detect_game": true,
    "auto_screenshot_for_guide": true
  }
}
```

### 8.3 独占执行器

屏幕操作必须串行执行（同一时刻只能有一个操作在控制鼠标/键盘）：

```python
class ExclusiveExecutor:
    """独占执行器 — 确保屏幕操作串行化"""

    def __init__(self):
        self._lock = asyncio.Lock()
        self._current_task: Optional[str] = None

    async def execute(self, task_id: str, action: Callable):
        async with self._lock:
            self._current_task = task_id
            try:
                result = await action()
                return result
            finally:
                self._current_task = None

    @property
    def is_busy(self) -> bool:
        return self._lock.locked()

    @property
    def current_task(self) -> Optional[str]:
        return self._current_task
```

---

## 八、用户体验设计

### 8.1 交互模式

#### 模式一：边玩边问（攻略伴玩）

```
用户正在玩游戏，NagaAgent 窗口在侧边或叠加层

用户（文字/语音）："这个 Boss 弱火吗？"

NagaAgent 自动：
  1. 截取当前游戏画面
  2. 识别 Boss 名称
  3. 查询攻略知识库
  4. Live2D 角色播报回答

角色："这个是深渊使徒·激流，弱火和冰哦~
      推荐用胡桃或者宵宫，记得带个盾！"
```

#### 模式二：托管代操

```
用户："帮我把今天的日常刷了吧"

NagaAgent：
  1. 识别当前游戏
  2. 列出可执行的日常任务
  3. 用户确认

角色："好的~ 明日方舟今天要做的：
      ✓ 基建换班
      ✓ 公开招募刷新
      ✓ 剿灭作战
      要全部帮你搞定吗？"

用户："嗯"

角色："收到！那我开始了哦~"
      [开始代操，实时播报进度]

角色："基建换班搞定了~ 接下来去公开招募..."
角色："公招发现一个高资干员标签组合，要我帮你选吗？"
```

#### 模式三：主动提示

```
NagaAgent 后台监控检测到游戏事件：

角色："检测到你的体力快溢出了哦，要帮你刷几把吗？"
角色："限时活动还有2天结束，你还没打完第三章呢~"
```

### 8.2 UI 新增元素

```
┌─────────────────────────────────────────┐
│  NagaAgent 主窗口                        │
│                                         │
│  ┌───────────────────────────────────┐  │
│  │        Live2D 角色区域            │  │
│  │    [游戏状态指示灯] 🟢 明日方舟    │  │  ← 新增：游戏识别状态
│  └───────────────────────────────────┘  │
│                                         │
│  ┌───────────────────────────────────┐  │
│  │        对话区域                    │  │
│  │  ...                              │  │
│  └───────────────────────────────────┘  │
│                                         │
│  ┌───────────────────────────────────┐  │
│  │  输入区域                          │  │
│  │  [文字输入] [截图] [代操] [攻略]   │  │  ← 新增：快捷操作按钮
│  └───────────────────────────────────┘  │
│                                         │
│  ┌───────────────────────────────────┐  │
│  │  操控面板（代操模式时展开）         │  │  ← 新增：操控状态面板
│  │  任务：自动刷本 1-7               │  │
│  │  进度：[████████░░] 8/10          │  │
│  │  状态：正在等待战斗结束...         │  │
│  │  [暂停] [停止] [接管]             │  │
│  └───────────────────────────────────┘  │
└─────────────────────────────────────────┘
```

### 8.3 快捷键

| 快捷键 | 功能 |
|--------|------|
| `Esc` | 紧急停止所有代操操作 |
| `Ctrl+Shift+S` | 手动截图当前画面发送给 NagaAgent |
| `Ctrl+Shift+G` | 快速打开攻略问答（自动截图 + 输入框） |
| `Ctrl+Shift+A` | 切换代操模式开/关 |

---

## 九、分阶段交付计划

### P0 阶段：基础修复（让屏幕操控跑起来）

**目标**：修复 7 项已知缺陷，实现单步操作可用

| 任务 | 具体内容 |
|------|---------|
| Bug-1 | 实现 `run_instruction()` 真实 AI 循环：截图→分析→决策→操作 |
| Bug-2 | 实现 `find_element_by_text()` 基于 OCR + `find_element_by_image()` 基于模板匹配 |
| Bug-3 | 坐标解析失败时抛出异常而非静默返回 (0,0) |
| Bug-4 | 重写 AI 视觉 Prompt，采用结构化 JSON 输出约束 |
| Bug-5 | 运行时检测屏幕分辨率替代硬编码 1920x1080 |
| Bug-6 | 修复未实现方法调用导致的运行时崩溃 |
| Bug-7 | 初始化 `self.planner` 或移除死代码路径 |
| 复用 | 从 N.E.K.O. 移植 DPI 适配代码和 `_ScaledPyAutoGUI` |

**验收标准**：
- 单步操作成功率 >= 70%
- 点击精度：0% 误点左上角 (0,0)
- 所有代码路径无崩溃

---

### P1 阶段：核心能力建设

**目标**：三层视觉感知 + 多步骤任务 + 攻略引擎集成

| 模块 | 任务 |
|------|------|
| **视觉感知** | 实现三层管线（模板→OCR→AI），复用 N.E.K.O. screenshot_utils |
| **操作验证** | 实现 verifier.py 分层验证（像素差异 + AI） |
| **状态追踪** | 实现 state.py 多步骤上下文管理 |
| **独占执行** | 实现 ExclusiveExecutor 串行化屏幕操作 |
| **游戏识别** | 实现 game_detector.py 三层游戏识别 |
| **任务编排** | 实现 screen_agent.py 主循环 + 任务状态机 |
| **攻略引擎** | 从攻略智能体移植 RAG 检索、意图路由、计算引擎 |
| **MCP 工具** | 新增 agent_game_guide / agent_game_control / agent_game_vision |
| **API 层** | 新增游戏操控 API + 攻略查询 API |
| **意图增强** | 改造 conversation_analyzer 支持游戏/攻略/操控意图 |
| **脚本系统** | 实现脚本引擎 + YAML 脚本配置 + 大模型/脚本协作分工 + 异常升级机制 |
| **代操模式** | 实现完整代操流程 + 进度播报 + 异常处理（优先走脚本，异常走大模型） |

**验收标准**：
- 单步操作成功率 >= 85%
- 多步骤（3-5步）任务完成率 >= 70%
- 已知按钮定位延迟 < 200ms（模板路径）
- 未知界面分析延迟 < 5s（AI 路径）
- 攻略问答端到端可用，支持文字 + 截图输入
- 代操模式可完成至少 1 款游戏的日常任务

---

### P2 阶段：深度融合与体验优化

**目标**：上下文感知攻略 + 主动提示 + 角色反应 + 多游戏模板

| 模块 | 任务 |
|------|------|
| **上下文攻略** | 根据当前游戏画面自动推送相关攻略信息 |
| **主动监控** | 后台监控游戏状态变化，触发主动提示 |
| **脚本系统扩展** | 为更多游戏补充脚本化固定流程 |
| **多游戏模板** | 为已支持的 9 款游戏制作 UI 模板和操作流程 |
| **自定义流程** | 用户可录制/编辑自定义操作流程 |
| **QQ Bot 联动** | 攻略引擎同时支持 NagaAgent 桌面端和 QQ Bot |
| **数据统计** | 操作日志、成功率统计、耗时分析 |

**验收标准**：
- 监控检测延迟 < 500ms
- >= 3 款游戏有完整配置模板
- 脚本覆盖率：常用日常流程 >= 80% 可脚本化执行
- 自定义流程可创建可执行

---

## 十、风险与应对

| 风险 | 概率 | 影响 | 应对策略 |
|------|------|------|---------|
| AI 视觉模型坐标不准确 | 高 | 高 | 三层感知管线降级；模板匹配覆盖常用界面；坐标缓存 |
| 游戏更新导致 UI 变化 | 高 | 中 | 模板库定期更新；AI 视觉作为兜底；社区贡献模板 |
| 反作弊系统误判 | 中 | 高 | 不尝试绕过；提前检测并提示用户；仅用标准输入 API |
| API 调用成本过高 | 中 | 中 | 分层策略优先免费方案；像素验证减少 80% AI 调用 |
| 多游戏适配工作量大 | 高 | 中 | 优先支持 2-3 款核心游戏；通用框架 + 游戏配置分离 |
| 网络延迟影响操控体验 | 中 | 中 | 本地模板/OCR 优先；AI 调用异步化；预加载策略 |

---

## 十一、技术依赖与环境

### 11.1 新增依赖

| 包名 | 用途 | 说明 |
|------|------|------|
| `mss` | 屏幕截图 | 替代 pyautogui.screenshot，性能更优 |
| `paddleocr` | OCR 识别 | 中文识别优于 Tesseract（可选） |
| `chromadb` | 向量数据库 | 攻略知识库检索（本地轻量级） |
| `sentence-transformers` | 文本嵌入 | BAAI/bge-base-zh-v1.5 中文嵌入模型 |
| `google-generativeai` | Gemini API | 视觉模型 + 攻略 LLM |
| `anthropic` | Claude API | Computer Use 视觉模型（可选） |

### 11.2 基础设施

| 服务 | 用途 | 必需性 |
|------|------|--------|
| Neo4j | 知识图谱（GRAG + 游戏关系） | 已有，扩展游戏数据 |
| ChromaDB | 攻略向量检索 | 新增，本地嵌入式运行 |
| Redis | 缓存（可选） | 可选，用于坐标缓存/操作限速 |

---

## 十二、成功指标

| 指标 | P0 目标 | P1 目标 | P2 目标 |
|------|---------|---------|---------|
| 单步操作成功率 | >= 70% | >= 85% | >= 90% |
| 多步骤任务完成率 | N/A | >= 70% | >= 80% |
| 攻略问答准确率 | N/A | >= 80% | >= 85% |
| 已知元素定位延迟 | < 500ms | < 200ms | < 100ms |
| 未知界面分析延迟 | < 10s | < 5s | < 3s |
| AI 调用次数/任务 | N/A | <= 步骤数 x 1.5 | <= 步骤数 x 1.2 |
| 用户满意度 | 可用 | 好用 | 爱用 |

---

## 十三、附录

### 附录 A：已支持游戏列表（来源于攻略智能体）

| 游戏 | ID | 攻略引擎 | 视觉操控 | 代操任务 |
|------|-----|---------|---------|---------|
| 明日方舟 | arknights | 已有 | P1 优先 | 日常/基建/公招 |
| 原神 | genshin-impact | 已有 | P1 优先 | 日常/派遣/菜单 |
| 崩坏：星穹铁道 | honkai-star-rail | 已有 | P1 | 日常/模拟宇宙 |
| 鸣潮 | wuthering-waves | 已有 | P2 | 日常 |
| 绝区零 | zenless-zone-zero | 已有 | P2 | 日常 |
| 战双帕弥什 | punishing-gray-raven | 已有 | P2 | 日常 |
| 赛马娘 | uma-musume | 已有 | P2 | 训练/比赛 |
| 舰队收藏 | kantai-collection | 已有 | P2 | 远征/演习 |

### 附录 B：关键文件路径对照

| 组件 | 现有路径 | 新增/修改 |
|------|---------|-----------|
| 屏幕操控 Agent | `agentserver/agent_computer_control/` | 重构 |
| 视觉分析 MCP | `mcpserver/agent_vision/` | 扩展 |
| 攻略引擎 | N/A（独立项目 `C:\攻略智能体 (2)\backend\`） | 新增 `guide_engine/` |
| 游戏攻略 MCP | N/A | 新增 `mcpserver/agent_game_guide/` |
| 游戏操控 MCP | N/A | 新增 `mcpserver/agent_game_control/` |
| 游戏监控 MCP | N/A | 新增 `mcpserver/agent_game_monitor/` |
| 游戏 UI 模板 | N/A | 新增 `game_templates/` |
| 配置文件 | `config.json` | 新增 game_vision / game_control / guide_engine 节 |
| N.E.K.O. 参考 | `C:\naga\屏幕识别\Xiao8\` | 复用约 700 行 |
| 攻略智能体参考 | `C:\攻略智能体 (2)\backend\app\` | 移植核心服务 |

### 附录 C：术语表

| 术语 | 含义 |
|------|------|
| **GRAG** | Graph-based Retrieval Augmented Generation，NagaAgent 的图谱记忆系统 |
| **RAG** | Retrieval Augmented Generation，检索增强生成 |
| **MCP** | Model Context Protocol，模型上下文协议（NagaAgent 工具扩展机制） |
| **三层视觉感知** | 模板匹配 → OCR → AI 视觉模型的逐级升级策略 |
| **独占执行器** | 确保屏幕操作串行化的锁机制 |
| **代操模式** | NagaAgent 获得授权后自主操作游戏的模式 |
| **N.E.K.O.** | 参考项目（Xiao8），Steam 发布的猫娘桌面助手 |

---

> **文档结束**
>
> 本文档基于 NagaAgent v4.0 现有架构、屏幕识别模块分析报告（Claude/GPT/Gemini 三方建议）、攻略智能体项目（9 游戏 RAG 系统）以及 N.E.K.O. 参考实现编写。
