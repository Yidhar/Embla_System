export const SUPPORTED_LOCALES = ["zh-CN", "en-US"] as const;
export type AppLocale = (typeof SUPPORTED_LOCALES)[number];

export const DEFAULT_LOCALE: AppLocale = "zh-CN";
export const LOCALE_COOKIE_NAME = "embla_locale";

type TranslationLeaf = string;
type TranslationTree = {
  [key: string]: TranslationLeaf | TranslationTree;
};

type TranslationCatalog = Record<AppLocale, TranslationTree>;

const zhCNMessages = {
    common: {
      meta: {
        title: "Embla Core Dashboard",
        description: "Embla System 用户监控前端，聚焦 Runtime / MCP / Memory / Workflow。"
      },
      status: {
        ok: "稳定",
        warning: "关注",
        critical: "严重",
        unknown: "未知"
      },
      mode: {
        live: "实时接口",
        degraded: "降级接口",
        "local-fallback": "本地快照",
        mock: "示例数据"
      },
      locale: {
        label: "语言",
        zhCN: "简体中文",
        enUS: "English"
      },
      label: {
        updatedAt: "更新于 {timestamp}",
        none: "无",
        unknown: "未知",
        running: "运行中",
        noDescription: "暂无描述",
        manageable: "可直接在管理区继续维护。",
        queryFailed: "查询失败",
        loading: "加载中…"
      },
      empty: {
        noCriticalEventsTitle: "暂无关键事件",
        noCriticalEventsDescription: "当前没有需要用户重点关注的事件。",
        noGraphSampleTitle: "暂无图谱采样",
        noGraphSampleDescription: "等待五元组写入后，这里会显示最近关系网络。"
      }
    },
    layout: {
      brandEyebrow: "Embla Core",
      brandTitle: "用户监控看板",
      brandDescription: "首页聚焦 Runtime + MCP + Memory + Workflow，避免把用户暴露在运维细枝末节里。",
      nav: {
        runtimePosture: { label: "Runtime Posture", description: "首屏态势总览" },
        mcpFabric: { label: "MCP Fabric", description: "MCP / Tool / Skill 管理" },
        memoryGraph: { label: "Memory Graph", description: "图谱与召回状态" },
        workflowEvents: { label: "Workflow & Events", description: "队列、事件、上下文" },
        incidents: { label: "Incidents", description: "最近风险与修复入口" },
        evidence: { label: "Evidence", description: "次级验收与证据" },
        chatops: { label: "ChatOps", description: "外层沟通与会话观测" },
        agentConfig: { label: "Agent Config", description: "子代理类型与提示词配置" },
        settings: { label: "Settings", description: "系统与运行时配置总览" }
      }
    },
    mcpFabric: {
      header: {
        eyebrow: "Fabric Visible",
        title: "MCP Fabric",
        description: "面向用户可理解的能力织网视图：把本地 Tools、MCP 服务/MCP Tools、Skills 的库存和服务健康拆开展示。"
      },
      metrics: {
        tools: { title: "Tools", description: "AI 当前可使用的本地工具面，包含 memory/native 与热注册 dynamic tools。" },
        mcpServices: { title: "MCP Services", description: "当前识别到的 MCP 服务数。" },
        mcpTools: { title: "MCP Tools", description: "已从 MCP 服务发现并注册到运行时的工具数。" },
        skills: { title: "Skills", description: "本地已发现的技能数量。" }
      },
      serviceMatrix: {
        eyebrow: "Service Matrix",
        title: "服务列表",
        description: "来源与状态同屏显示，用户可以直观看到当前能力面是“在线”“已配置”还是只是“已发现”。",
        empty: "当前没有可展示的 MCP 服务。"
      },
      trustBoundary: {
        eyebrow: "Trust Boundary",
        title: "状态解读",
        description: "把 MCP 的复杂性翻译给普通用户：是可用、待验证、还是需要人工关注。",
        statusBreakdown: "状态分层",
        sourceBreakdown: "来源分层",
        rejected: "Rejected",
        rejectedDescription: "被策略拒绝的插件 manifest 数量。",
        isolated: "Isolated",
        isolatedDescription: "隔离 worker 中运行的服务数量。"
      }
    },
    chatops: {
      header: {
        eyebrow: "Session Pulse",
        title: "ChatOps",
        description: "这里同时展示全部会话目录、选中会话的 Shell/Core 路由状态，以及一个面向外层操作者的测试聊天入口。"
      },
      sessionDirectory: {
        eyebrow: "Session Directory",
        title: "全部会话",
        description: "不再依赖被动输入 session_id；页面会直接列出当前后端保留的所有会话，并允许你切换到任意一个会话继续观察或接管沟通。",
        emptyTitle: "当前没有会话",
        emptyDescription: "后端尚未保留任何聊天会话。你可以直接在右侧发起一次测试聊天创建新会话。",
        temporary: "临时",
        rounds: "{rounds} 轮",
        messages: "{messages} 条消息",
        noMessage: "暂无最近消息摘要"
      },
      waiting: {
        eyebrow: "Waiting Input",
        title: "尚未选择会话",
        description: "先从左侧列表选择一个会话，或直接通过右侧测试聊天创建新会话。",
        emptyTitle: "等待会话",
        emptyDescription: "会话列表为空时，可直接在右侧输入消息并发送。"
      },
      lookupMiss: {
        eyebrow: "Lookup Miss",
        title: "未找到路由状态",
        description: "当前会话存在，但后端没有返回 route snapshot。这通常意味着该会话还没有进入 Shell/Core 路由链，或者相关状态已被清理。",
        emptyTitle: "路由状态不可用",
        emptyDescription: "未能读取 session_id={sessionId} 的 route state。"
      },
      metrics: {
        totalSessions: { title: "Total Sessions", description: "当前后端保留的全部会话数。" },
        selectedRounds: { title: "Selected Rounds", description: "当前选中会话的对话轮数。" },
        childSessions: { title: "子会话数", description: "当前选中路由下观测到的后代会话数（其中 {withHeartbeats} 个带 heartbeat，{taskCount} 个活跃任务）。" },
        routeSemantic: { title: "Route Semantic", description: "当前 Shell/Core 路由语义。" }
      },
      console: {
        eyebrow: "Outer Channel",
        title: "外层沟通接口",
        description: "这是面向操作者的测试聊天通道。你可以继续当前选中会话，也可以清空后直接发起一个新会话。",
        currentSession: "当前绑定会话",
        noSession: "将创建新会话",
        sessionHint: "留空时会由后端自动创建新的 Shell 会话。",
        toolSurface: "Shell 工具面",
        toolSurfaceDescription: "这里展示当前对外 Shell 通道可用的工具清单；流式会话启动时会与后端运行时再次对齐。",
        toolCount: "{count} 个工具",
        toolEmpty: "当前没有可展示的 Shell 工具。",
        emptyTitle: "还没有聊天记录",
        emptyDescription: "从这里发送一条消息，就可以验证外层对话链路是否正常。",
        placeholder: "输入一条测试消息，例如：请总结当前 runtime posture。",
        submit: "发送测试消息",
        submitting: "发送中…",
        submitHint: "会直接调用 /v1/chat/stream，以 Shell 流式链路启动会话并把 session_id 自动切回当前页面。",
        submitError: "测试聊天失败",
        startNew: "新会话",
        reasoning: "Reasoning",
        user: "用户",
        assistant: "助手"
      },
      heartbeat: {
        eyebrow: "Heartbeat",
        title: "子任务心跳",
        description: "这里展示当前子任务的 heartbeat 投影，而不是最终 execution receipt。",
        emptyTitle: "暂无 heartbeat",
        emptyDescription: "当前会话没有活跃子任务 heartbeat，可能仍停留在 Shell 只读链路，或子任务已经结束。",
        noMessage: "暂无附加说明"
      },
      routeSnapshot: {
        eyebrow: "Route Snapshot",
        title: "最近路由状态",
        description: "这里保留选中会话的 session state 与最近 route snapshot，方便判断当前是否已经 handoff 到 Core。",
        shellSession: "Shell Session",
        coreExecutionSession: "Core Execution Session",
        recentRouteEvents: "Recent Route Events",
        noHandoff: "尚未 handoff",
        routeEvent: "RouteEvent"
      }
    },
    settings: {
      header: {
        eyebrow: "Control Surface",
        title: "系统设置",
        description: "这里聚焦 Embla System 的框架级设置；MCP 安装与 Agent 提示词配置分别收敛到专门页面，并通过高级展开栏承载低频设置。",
        agentConfigCta: "打开 Agent 配置"
      },
      metrics: {
        apiVersion: { title: "API Version", description: "当前后端 API 版本。" },
        promptTemplates: { title: "Prompt Templates", description: "当前可发现的提示词模板数量。" },
        agentProfiles: { title: "Agent Profiles", description: "已启用 Agent Profile / 总 Profile 数量。" },
        apiKey: { title: "API Key", description: "当前主 API Key 是否已经配置。" }
      },
      sections: {
        runtime: {
          eyebrow: "Runtime Registry",
          title: "运行时注册信息",
          description: "查看 Agent Profile 注册表、允许角色和提示词模板目录，确认控制面是否暴露了足够的配置面。"
        },
        config: {
          eyebrow: "Config Snapshot",
          title: "配置快照",
          description: "这里展示当前配置快照的关键键名，方便快速判断系统配置是否已经装载到位。"
        }
      },
      labels: {
        configured: "已配置",
        notConfigured: "未配置",
        registryPath: "注册表路径",
        allowedRoles: "允许角色",
        promptTemplates: "提示词模板",
        availableServices: "可用服务数量",
        configKeys: "配置根键",
        emblaSystemKeys: "embla_system 键"
      }
    },
    agentConfig: {
      header: {
        eyebrow: "Dynamic Profiles",
        title: "Agent 配置",
        description: "集中维护子代理的 agent_type、生命周期角色、提示词块与工具配置，让新的子代理类型能被运行时动态索引并立即用于 spawn。"
      },
      metrics: {
        totalProfiles: { title: "Total Profiles", description: "当前注册表中的 Agent Profile 总数。" },
        enabledProfiles: { title: "Enabled Profiles", description: "当前处于启用状态的 Agent Profile 数量。" },
        defaultProfiles: { title: "Role Defaults", description: "每个生命周期角色的默认 Profile 数量。" },
        promptTemplates: { title: "Prompt Templates", description: "当前可供 Agent Profile 选择的提示词模板数量。" }
      },
      registry: {
        eyebrow: "Registry",
        title: "Profile 列表",
        description: "左侧列出所有 agent_type，支持 builtin / 默认角色 / 启停状态同屏查看。",
        newProfile: "新建 Profile",
        emptyTitle: "暂无 Agent Profile",
        emptyDescription: "当前注册表为空。你可以立即新建一个 agent_type。",
        defaultBadge: "默认",
        builtinBadge: "内置",
        disabledBadge: "停用",
        promptBlocks: "{count} 个 prompt block",
        customTools: "custom tools"
      },
      editor: {
        eyebrow: "Editor",
        title: "编辑 Profile",
        description: "编辑完成后会直接写入后端 agent profile 注册表；后续 `spawn_child_agent(agent_type=...)` 会即时使用这些配置。"
      },
      form: {
        agentType: "Agent Type",
        agentTypeRequired: "agent_type 不能为空",
        role: "Lifecycle Role",
        label: "显示名称",
        description: "说明",
        promptBlocks: "Prompt Blocks",
        promptBlocksPlaceholder: "agents/review/code_reviewer.md",
        promptBlocksHint: "每行一个相对路径，根目录默认为系统 canonical prompts root。",
        toolProfile: "Tool Profile",
        toolSubset: "Tool Subset",
        toolSubsetHint: "逗号分隔；仅在你想覆写 tool_profile 时填写。",
        promptsRoot: "Prompts Root",
        promptsRootPlaceholder: "留空则使用系统默认 prompts root",
        promptsRootHint: "通常无需填写；只有在你明确要把该 profile 指向另一套 prompt 资产时才覆盖。",
        enabled: "启用",
        defaultForRole: "设为该角色默认",
        save: "保存 Profile",
        saving: "保存中…",
        delete: "删除 Profile",
        deleting: "删除中…",
        reset: "重置",
        saveSuccess: "Agent Profile 已保存。",
        deleteSuccess: "Agent Profile 已删除。",
        error: "Agent Profile 操作失败"
      },
      preview: {
        eyebrow: "Preview",
        title: "Prompt 预览",
        description: "这里展示当前 Profile 引用的 prompt block 预览，方便直观看到子代理会加载哪些提示词块。",
        emptyTitle: "暂无 Prompt 预览",
        emptyDescription: "先选择一个已有 Profile，或保存带有 prompt block 的新 Profile。",
        missing: "文件不存在",
        noContent: "没有可展示的内容预览"
      },
      catalog: {
        eyebrow: "Reference",
        title: "可选目录",
        description: "右侧同时给出当前 tool profile 预设和提示词模板目录，方便你直接填充新的 agent_type。",
        toolProfiles: "Tool Profiles",
        promptTemplates: "Prompt Templates"
      }
    },
    management: {
      mcp: {
        eyebrow: "Official MCP",
        title: "安装官方 MCP 服务",
        description: "把官方 MCP stdio 服务写入项目根目录的 mcp_servers.json，并尝试热重载当前运行时。当前控件仅支持 command / args / env 形式的本地子进程服务。",
        placeholder: "服务名称，例如 fetch",
        submit: "安装 / 更新 MCP",
        submitting: "写入中…",
        submitSuccess: "官方 MCP 配置已写入。",
        submitError: "写入官方 MCP 配置失败",
        catalogTitle: "发现源",
        catalogDescription: "官方 Registry 是 canonical source；终端用户通常会通过官方示例仓库或社区目录来挑选具体服务。",
        presetsTitle: "快速预设",
        presetUse: "载入",
        presetFetch: "Fetch",
        presetFilesystem: "Filesystem",
        presetGit: "Git",
        presetMemory: "Memory"
      },
      skill: {
        eyebrow: "Skill Import",
        title: "导入本地 Skill",
        description: "创建一个本地 SKILL.md，供 Embla 运行时按需发现与加载。",
        placeholder: "技能名称，例如 repo-review",
        defaultContent: "---\nname: custom-skill\ndescription: 用户自定义技能\nversion: 1.0.0\nauthor: User\ntags:\n  - custom\nenabled: true\n---\n\n# Skill\n\n在这里填写技能说明。\n",
        submit: "导入 Skill",
        submitting: "写入中…",
        submitSuccess: "Skill 已导入。",
        submitError: "导入 Skill 失败"
      }
    },
    runtimePosture: {
      header: {
        eyebrow: "Runtime Posture",
        title: "运行时总体态势",
        description: "把 rollout、租约、队列、锁与磁盘水位汇总到首页，帮助你快速判断当前执行面是否稳定。"
      },
      metrics: {
        rollout: { title: "Runtime Rollout", description: "当前 rollout 配置比例 {percent}%。" },
        failOpen: { title: "Fail-open Budget", description: "剩余预算 {budget}，阻断占比 {blocked}。" },
        lease: { title: "Lease TTL", description: "租约状态 {state}，fencing epoch {epoch}。" },
        queue: { title: "Queue Depth", description: "最老待处理项已等待 {age}。" },
        lock: { title: "Lock State", description: "当前 fencing epoch {epoch}。" },
        disk: { title: "Disk Watermark", description: "当前可用磁盘约 {freeGb} GB。" }
      },
      sections: {
        agentFleet: {
          eyebrow: "Agent Fleet",
          title: "Agent 舰队与执行面",
          description: "观察 Shell/Core 路由、角色分布和工具状态，快速判断本轮执行链是否在按预期推进。",
          observedAgents: "Observed Agents",
          totalObserved: "当前观测到的 Agent 数。",
          latestRole: "最新角色",
          ongoingTasks: "Ongoing Tasks",
          ongoingTasksFootnote: "结合 Workflow 与 Memory 推导的进行中任务量。",
          deferredCount: "Deferred Count",
          toolStatus: "当前工具状态",
          noToolStatus: "当前没有可见的工具状态。",
          roleBreakdown: "角色分布",
          noRoleBreakdown: "暂无角色分布数据",
          shellToCore: "Shell → Core 派发",
          readonlyHit: "Shell 只读命中",
          bridgeReject: "执行桥拒绝"
        },
        memoryReadiness: {
          eyebrow: "Memory Readiness",
          title: "记忆就绪度",
          description: "对五元组图谱、向量索引和任务积压做同屏观察，判断召回能力是否可用。",
          recallReadiness: "Recall Readiness",
          knowledgeGraph: "Knowledge Graph",
          knowledgeGraphDescription: "活跃任务 {activeTasks}，向量索引状态 {indexState}。",
          knowledgeGraphFootnote: "当前图谱采样边数 {sampleSize}。"
        },
        toolSurface: {
          eyebrow: "Tool Surface",
          title: "能力表面",
          description: "把 MCP、Skills 与验收证据放在同一层看，帮助判断当前执行面可用能力是否完整。",
          mcpServices: "MCP Services",
          skills: "Skills",
          skillsDescription: "本地 Skill 库存可直接被运行时按需发现。",
          evidenceReadiness: "Evidence Readiness",
          evidenceReadinessDescription: "必需报告通过数与缺失项共同反映验收准备度。",
          sourceBreakdown: "来源分布",
          statusBreakdown: "状态分布"
        },
        eventsAndRisks: {
          eyebrow: "Events & Risks",
          title: "关键事件与风险",
          description: "最近关键事件与 incident 会汇聚到这里，便于快速确认系统是否进入异常路径。"
        }
      }
    },
    workflowEvents: {
      header: {
        eyebrow: "Workflow Pulse",
        title: "Workflow 与事件流",
        description: "把队列、租约、锁状态和会话级 heartbeat 放在一起，帮助排查执行链路卡点。"
      },
      metrics: {
        outboxPending: { title: "Outbox Pending", description: "当前仍在等待发送或处理的事件数量。" },
        oldestPending: { title: "Oldest Pending", description: "队列中最老待处理项的等待时长。" },
        leaseState: { title: "Lease State", description: "当前 runtime lease 的状态。" },
        lockState: { title: "Lock State", description: "当前全局锁或关键互斥锁的状态。" }
      },
      criticalLane: {
        eyebrow: "Critical Lane",
        title: "关键事件时间线",
        description: "按时间顺序查看最近 critical / warning 事件，优先处理真正影响执行的信号。"
      },
      contextPulse: {
        eyebrow: "Context Pulse",
        title: "上下文脉冲",
        description: "聚合消息上下文、事件数据库与 Agent heartbeat，帮助判断当前上下文是否仍在前进。",
        messageContext: "Message Context",
        messageContextDescription: "当前日志上下文中保留的消息总数。",
        eventDbRows: "Event DB Rows",
        eventDbRowsDescription: "事件数据库中累计写入的行数。",
        currentToolStatus: "当前工具状态",
        noToolStatus: "当前没有可见的工具状态。",
        agentHeartbeats: "Agent Heartbeats",
        active: "活跃任务",
        warning: "关注",
        critical: "严重",
        blocked: "阻断",
        heartbeatSummary: "{withHeartbeats}/{sessions} 个会话存在 heartbeat，最高陈旧等级 {level}。",
        noHeartbeatMessage: "暂无心跳附加说明",
        noHeartbeats: "当前没有可见的子任务 heartbeat。",
        noHeartbeatTasksYet: "当前没有活跃的子任务 heartbeat；上方摘要仍会保留已观测到的子会话统计。",
        keyCounters: "关键计数器"
      }
    },
    memoryGraph: {
      header: {
        eyebrow: "Memory Graph",
        title: "会话级记忆图谱",
        description: "展示 L2 五元组图谱、召回状态和热点关系，帮助你验证记忆抽取是否正常工作。"
      },
      metrics: {
        recallReadiness: "召回就绪度",
        quintuples: { title: "Quintuples", description: "当前已写入的五元组总量。" },
        activeTasks: { title: "Active Tasks", description: "当前仍在运行的记忆抽取 / 写入任务数。" },
        vectorIndex: { title: "Vector Index", description: "向量索引是否已就绪并可服务召回。" }
      },
      graphCanvas: {
        eyebrow: "Graph Canvas",
        title: "图谱采样",
        description: "最近写入的关系样本会以轻量图形式展示，便于快速查看事实连接结构。"
      },
      hotspots: {
        eyebrow: "Hotspots",
        title: "热点关系与实体",
        description: "找出当前最频繁出现的关系、实体，以及任务执行状态。",
        relation: "关系热点",
        entity: "实体热点",
        pending: "待处理",
        running: "运行中",
        failed: "失败"
      }
    },
    incidents: {
      header: {
        eyebrow: "Incident Desk",
        title: "事件与风险",
        description: "集中查看最近的风险、异常和报告路径，帮助你尽快定位需要处理的问题。"
      },
      latest: {
        eyebrow: "Latest Incidents",
        title: "最近事件",
        description: "按时间顺序展示最新 incident 摘要和关联报告路径。"
      }
    },
    evidence: {
      header: {
        eyebrow: "Evidence Index",
        title: "验收证据",
        description: "把必需报告和缺失项集中展示，便于判断本轮执行是否达到可交付状态。"
      },
      metrics: {
        requiredTotal: { title: "Required Reports", description: "本轮要求的必需报告总数。" },
        requiredPassed: { title: "Required Passed", description: "已通过 gate 的必需报告数量。" },
        hardMissing: { title: "Hard Missing", description: "缺失会直接阻断验收的必需证据项数量。" },
        softMissing: { title: "Soft Missing", description: "可补齐但暂不阻断的缺失证据项数量。" }
      },
      reportIndex: {
        eyebrow: "Report Index",
        title: "报告索引",
        description: "列出当前证据报告的路径、gate 等级和状态。"
      }
    },
    memorySearch: {
      eyebrow: "Memory Search",
      title: "记忆检索",
      description: "直接按关键词查询五元组，验证记忆写入是否可被检索与召回。",
      placeholder: "输入关键词，使用逗号分隔，例如 agent, workflow",
      submit: "查询",
      submitting: "查询中…",
      initialMeta: "输入关键词后开始查询。",
      resultMeta: "共找到 {total} 条结果，耗时 {elapsed} ms。",
      emptyTitle: "暂无检索结果",
      emptyDescription: "尝试调整关键词，或等待更多五元组写入。",
      unknownType: "未知类型"
    },
    viewModels: {
      recall: {
        ready: "索引就绪",
        warming: "索引预热中",
        description: "基于索引状态、图谱规模与任务背压推导的召回就绪度。"
      },
      services: {
        online: "{available}/{total} 在线",
        discovered: "已发现 {total} 个"
      }
    },
    enums: {
      leaseState: {
        expired: "已过期",
        near_expiry: "临近过期",
        healthy: "正常",
        missing: "缺失",
        unknown: "未知"
      },
      lockState: {
        idle: "空闲",
        held: "已持有",
        near_expiry: "临近过期",
        expired: "已过期",
        missing: "缺失",
        unknown: "未知"
      },
      staleLevel: {
        none: "无",
        fresh: "新鲜",
        warning: "关注",
        critical: "严重",
        blocked: "阻断",
        unknown: "未知"
      },
      routeSemantic: {
        shell_readonly: "Shell 只读",
        shell_clarify: "Shell 澄清",
        core_execution: "Core 执行",
        unknown: "未知"
      },
      mcpStatus: {
        online: "在线",
        offline: "离线",
        configured: "已配置",
        missing_command: "缺少命令",
        available: "可用",
        unknown: "未知"
      },
      generic: {
        unknown: "未知",
        running: "运行中"
      }
    }
};

const enUSMessages: typeof zhCNMessages = {
    common: {
      meta: {
        title: "Embla Core Dashboard",
        description: "Embla System dashboard focused on Runtime / MCP / Memory / Workflow."
      },
      status: {
        ok: "Healthy",
        warning: "Warning",
        critical: "Critical",
        unknown: "Unknown"
      },
      mode: {
        live: "Live API",
        degraded: "Degraded API",
        "local-fallback": "Local Snapshot",
        mock: "Mock Data"
      },
      locale: {
        label: "Language",
        zhCN: "简体中文",
        enUS: "English"
      },
      label: {
        updatedAt: "Updated {timestamp}",
        none: "None",
        unknown: "Unknown",
        running: "Running",
        noDescription: "No description yet.",
        manageable: "Continue maintenance from the management panel.",
        queryFailed: "Request failed",
        loading: "Loading…"
      },
      empty: {
        noCriticalEventsTitle: "No critical events",
        noCriticalEventsDescription: "There are no events requiring attention right now.",
        noGraphSampleTitle: "No graph sample",
        noGraphSampleDescription: "Recent relationships will appear here after quintuples are written."
      }
    },
    layout: {
      brandEyebrow: "Embla Core",
      brandTitle: "User Operations Dashboard",
      brandDescription: "The home surface stays focused on Runtime + MCP + Memory + Workflow instead of low-level operations noise.",
      nav: {
        runtimePosture: { label: "Runtime Posture", description: "Primary runtime overview" },
        mcpFabric: { label: "MCP Fabric", description: "Manage MCP / Tool / Skills" },
        memoryGraph: { label: "Memory Graph", description: "Graph and recall health" },
        workflowEvents: { label: "Workflow & Events", description: "Queue, events, and context" },
        incidents: { label: "Incidents", description: "Recent risks and fixes" },
        evidence: { label: "Evidence", description: "Secondary acceptance evidence" },
        chatops: { label: "ChatOps", description: "Outer communication channel" },
        agentConfig: { label: "Agent Config", description: "Child agent prompt and profile registry" },
        settings: { label: "Settings", description: "System and runtime configuration overview" }
      }
    },
    mcpFabric: {
      header: {
        eyebrow: "Fabric Visible",
        title: "MCP Fabric",
        description: "A user-facing capability map that separates local Tools, MCP services/MCP tools, and Skills inventory from service health."
      },
      metrics: {
        tools: { title: "Tools", description: "Local tools currently usable by the AI runtime, including memory/native and hot-registered dynamic tools." },
        mcpServices: { title: "MCP Services", description: "Number of MCP services currently discovered." },
        mcpTools: { title: "MCP Tools", description: "Tools discovered from MCP services and registered into the runtime." },
        skills: { title: "Skills", description: "Number of discovered local skills." }
      },
      serviceMatrix: {
        eyebrow: "Service Matrix",
        title: "Services",
        description: "Source and status are shown together so users can immediately tell whether capability is online, configured, or merely discovered.",
        empty: "There are no MCP services to display right now."
      },
      trustBoundary: {
        eyebrow: "Trust Boundary",
        title: "Status guide",
        description: "Translates MCP complexity for end users: usable, pending validation, or requiring attention.",
        statusBreakdown: "Status breakdown",
        sourceBreakdown: "Source breakdown",
        rejected: "Rejected",
        rejectedDescription: "Number of plugin manifests rejected by policy.",
        isolated: "Isolated",
        isolatedDescription: "Number of services running inside isolated workers."
      }
    },
    chatops: {
      header: {
        eyebrow: "Session Pulse",
        title: "ChatOps",
        description: "This page shows the full session directory, the selected session's Shell/Core route state, and an outer operator-facing chat channel for quick testing."
      },
      sessionDirectory: {
        eyebrow: "Session Directory",
        title: "All sessions",
        description: "Instead of waiting for a manually pasted session_id, the page lists every retained backend session and lets you switch to any session for inspection or takeover.",
        emptyTitle: "No sessions yet",
        emptyDescription: "The backend is not retaining any chat sessions right now. You can start one immediately from the test chat panel on the right.",
        temporary: "Temporary",
        rounds: "{rounds} rounds",
        messages: "{messages} messages",
        noMessage: "No recent message summary"
      },
      waiting: {
        eyebrow: "Waiting Input",
        title: "No session selected",
        description: "Pick a session from the left, or create a new one from the outer chat channel.",
        emptyTitle: "Waiting for a session",
        emptyDescription: "If the list is empty, send a message from the right-hand panel to create a fresh session."
      },
      lookupMiss: {
        eyebrow: "Lookup Miss",
        title: "Route state unavailable",
        description: "The session exists, but the backend did not return a route snapshot. That usually means the session never entered the Shell/Core route path, or the related state was already cleaned up.",
        emptyTitle: "Route state unavailable",
        emptyDescription: "Unable to read route state for session_id={sessionId}."
      },
      metrics: {
        totalSessions: { title: "Total Sessions", description: "All sessions currently retained by the backend." },
        selectedRounds: { title: "Selected Rounds", description: "Conversation rounds in the selected session." },
        childSessions: { title: "Child Sessions", description: "Observed descendant sessions under the selected route ({withHeartbeats} with heartbeats, {taskCount} active tasks)." },
        routeSemantic: { title: "Route Semantic", description: "Current Shell/Core route semantic." }
      },
      console: {
        eyebrow: "Outer Channel",
        title: "Outer communication channel",
        description: "This is the operator-facing test chat surface. You can continue the selected session or clear it and start a brand new one.",
        currentSession: "Bound session",
        noSession: "A new session will be created",
        sessionHint: "When blank, the backend will automatically create a fresh Shell session.",
        toolSurface: "Shell tool surface",
        toolSurfaceDescription: "Shows the tools currently available to the external Shell channel. Stream startup re-syncs this list with the backend runtime.",
        toolCount: "{count} tools",
        toolEmpty: "No Shell tools are available to display right now.",
        emptyTitle: "No chat transcript yet",
        emptyDescription: "Send one message here to verify that the outer conversation path is healthy.",
        placeholder: "Type a test message, for example: summarize the current runtime posture.",
        submit: "Send test message",
        submitting: "Sending…",
        submitHint: "This calls /v1/chat/stream directly, starts the session through the Shell streaming path, and switches the page to the returned session_id automatically.",
        submitError: "Test chat failed",
        startNew: "New session",
        reasoning: "Reasoning",
        user: "User",
        assistant: "Assistant"
      },
      heartbeat: {
        eyebrow: "Heartbeat",
        title: "Child task heartbeats",
        description: "This panel shows the heartbeat projection of child tasks rather than the final execution receipt.",
        emptyTitle: "No heartbeat",
        emptyDescription: "This session has no active child-task heartbeat. It may still be on a Shell readonly path or the child task may already be complete.",
        noMessage: "No additional detail"
      },
      routeSnapshot: {
        eyebrow: "Route Snapshot",
        title: "Recent route state",
        description: "The selected session state and recent route snapshot are kept together so you can tell whether handoff to Core has happened.",
        shellSession: "Shell Session",
        coreExecutionSession: "Core Execution Session",
        recentRouteEvents: "Recent Route Events",
        noHandoff: "No handoff yet",
        routeEvent: "RouteEvent"
      }
    },
    settings: {
      header: {
        eyebrow: "Control Surface",
        title: "Settings",
        description: "This page focuses on framework-level Embla System settings; MCP installation and agent prompt/profile maintenance now live on dedicated pages, with lower-frequency options tucked into an advanced drawer.",
        agentConfigCta: "Open Agent Config"
      },
      metrics: {
        apiVersion: { title: "API Version", description: "Current backend API version." },
        promptTemplates: { title: "Prompt Templates", description: "Number of prompt templates currently discoverable." },
        agentProfiles: { title: "Agent Profiles", description: "Enabled agent profiles versus total profiles." },
        apiKey: { title: "API Key", description: "Whether the primary API key is configured." }
      },
      sections: {
        runtime: {
          eyebrow: "Runtime Registry",
          title: "Runtime registry snapshot",
          description: "Inspect the agent profile registry, allowed lifecycle roles, and prompt-template inventory to confirm the control plane exposes the expected configuration surface."
        },
        config: {
          eyebrow: "Config Snapshot",
          title: "Configuration snapshot",
          description: "This section shows high-level config keys so you can quickly confirm the loaded runtime shape without diving into raw files."
        }
      },
      labels: {
        configured: "Configured",
        notConfigured: "Not configured",
        registryPath: "Registry path",
        allowedRoles: "Allowed roles",
        promptTemplates: "Prompt templates",
        availableServices: "Available services",
        configKeys: "Config root keys",
        emblaSystemKeys: "embla_system keys"
      }
    },
    agentConfig: {
      header: {
        eyebrow: "Dynamic Profiles",
        title: "Agent Config",
        description: "Manage child-agent agent_type entries, lifecycle roles, prompt blocks, and tool configuration so new child-agent types can be indexed dynamically and used immediately at spawn time."
      },
      metrics: {
        totalProfiles: { title: "Total Profiles", description: "Total number of agent profiles in the registry." },
        enabledProfiles: { title: "Enabled Profiles", description: "Number of agent profiles currently enabled." },
        defaultProfiles: { title: "Role Defaults", description: "Number of profiles currently marked as the default for a lifecycle role." },
        promptTemplates: { title: "Prompt Templates", description: "Prompt templates currently available to agent profiles." }
      },
      registry: {
        eyebrow: "Registry",
        title: "Profile list",
        description: "Browse every agent_type on the left with builtin, role-default, and enabled-state badges visible at a glance.",
        newProfile: "New Profile",
        emptyTitle: "No agent profiles yet",
        emptyDescription: "The registry is empty. Create a new agent_type to get started.",
        defaultBadge: "Default",
        builtinBadge: "Builtin",
        disabledBadge: "Disabled",
        promptBlocks: "{count} prompt blocks",
        customTools: "custom tools"
      },
      editor: {
        eyebrow: "Editor",
        title: "Edit profile",
        description: "Saving writes directly into the backend agent profile registry; subsequent `spawn_child_agent(agent_type=...)` calls pick up the change immediately."
      },
      form: {
        agentType: "Agent Type",
        agentTypeRequired: "agent_type is required",
        role: "Lifecycle Role",
        label: "Display Label",
        description: "Description",
        promptBlocks: "Prompt Blocks",
        promptBlocksPlaceholder: "agents/review/code_reviewer.md",
        promptBlocksHint: "One relative path per line. The root defaults to the system canonical prompts root.",
        toolProfile: "Tool Profile",
        toolSubset: "Tool Subset",
        toolSubsetHint: "Comma-separated; fill this only when you want to override the tool profile.",
        promptsRoot: "Prompts Root",
        promptsRootPlaceholder: "Leave blank to use the system default prompts root",
        promptsRootHint: "Usually leave this empty; override it only when this profile must point at a different prompt asset root.",
        enabled: "Enabled",
        defaultForRole: "Set as role default",
        save: "Save Profile",
        saving: "Saving…",
        delete: "Delete Profile",
        deleting: "Deleting…",
        reset: "Reset",
        saveSuccess: "Agent profile saved.",
        deleteSuccess: "Agent profile deleted.",
        error: "Agent profile operation failed"
      },
      preview: {
        eyebrow: "Preview",
        title: "Prompt preview",
        description: "This area previews the prompt blocks referenced by the current profile so you can see exactly what a child agent will load.",
        emptyTitle: "No prompt preview yet",
        emptyDescription: "Select an existing profile or save a new profile with prompt blocks first.",
        missing: "Missing file",
        noContent: "No preview content available"
      },
      catalog: {
        eyebrow: "Reference",
        title: "Available catalog",
        description: "Tool-profile presets and prompt-template inventory are shown together so you can fill a new agent_type without leaving the page.",
        toolProfiles: "Tool Profiles",
        promptTemplates: "Prompt Templates"
      }
    },
    management: {
      mcp: {
        eyebrow: "Official MCP",
        title: "Install official MCP service",
        description: "Writes an official MCP stdio server entry into the project-root mcp_servers.json and attempts a hot reload of the current runtime. The current control supports local subprocess servers via command / args / env.",
        placeholder: "Server name, for example fetch",
        submit: "Install / Update MCP",
        submitting: "Writing…",
        submitSuccess: "Official MCP config written.",
        submitError: "Failed to write official MCP config",
        catalogTitle: "Discovery sources",
        catalogDescription: "The official Registry is the canonical source; end users usually discover concrete servers through the official examples repo or community directories.",
        presetsTitle: "Quick presets",
        presetUse: "Load",
        presetFetch: "Fetch",
        presetFilesystem: "Filesystem",
        presetGit: "Git",
        presetMemory: "Memory"
      },
      skill: {
        eyebrow: "Skill Import",
        title: "Import local skill",
        description: "Creates a local SKILL.md so the Embla runtime can discover and load it on demand.",
        placeholder: "Skill name, for example repo-review",
        defaultContent: "---\nname: custom-skill\ndescription: User custom skill\nversion: 1.0.0\nauthor: User\ntags:\n  - custom\nenabled: true\n---\n\n# Skill\n\nDescribe the skill here.\n",
        submit: "Import Skill",
        submitting: "Writing…",
        submitSuccess: "Skill imported.",
        submitError: "Failed to import skill"
      }
    },
    runtimePosture: {
      header: {
        eyebrow: "Runtime Posture",
        title: "Runtime posture overview",
        description: "Rollout, lease, queue, lock, and disk watermark are summarized on one page so you can judge runtime stability quickly."
      },
      metrics: {
        rollout: { title: "Runtime Rollout", description: "Configured rollout ratio is currently {percent}%." },
        failOpen: { title: "Fail-open Budget", description: "Remaining budget {budget}, blocked ratio {blocked}." },
        lease: { title: "Lease TTL", description: "Lease state {state}, fencing epoch {epoch}." },
        queue: { title: "Queue Depth", description: "The oldest pending item has been waiting for {age}." },
        lock: { title: "Lock State", description: "Current fencing epoch {epoch}." },
        disk: { title: "Disk Watermark", description: "Approximately {freeGb} GB of disk space is currently free." }
      },
      sections: {
        agentFleet: {
          eyebrow: "Agent Fleet",
          title: "Agent fleet and execution surface",
          description: "Observe Shell/Core routing, role mix, and tool status to tell whether the current execution chain is progressing as expected.",
          observedAgents: "Observed Agents",
          totalObserved: "Number of agents currently observed.",
          latestRole: "Latest role",
          ongoingTasks: "Ongoing Tasks",
          ongoingTasksFootnote: "Tasks inferred from Workflow and Memory signals.",
          deferredCount: "Deferred Count",
          toolStatus: "Current tool status",
          noToolStatus: "No visible tool status right now.",
          roleBreakdown: "Role breakdown",
          noRoleBreakdown: "No role distribution data yet",
          shellToCore: "Shell → Core dispatch",
          readonlyHit: "Shell readonly hit",
          bridgeReject: "Execution bridge reject"
        },
        memoryReadiness: {
          eyebrow: "Memory Readiness",
          title: "Memory readiness",
          description: "Watch the quintuple graph, vector index, and task backlog together to decide whether recall is usable.",
          recallReadiness: "Recall Readiness",
          knowledgeGraph: "Knowledge Graph",
          knowledgeGraphDescription: "Active tasks {activeTasks}, vector index state {indexState}.",
          knowledgeGraphFootnote: "Current graph sample edge count {sampleSize}."
        },
        toolSurface: {
          eyebrow: "Tool Surface",
          title: "Capability surface",
          description: "View MCP, skills, and acceptance evidence together to judge whether the runtime has a complete usable capability surface.",
          mcpServices: "MCP Services",
          skills: "Skills",
          skillsDescription: "Local skill inventory that the runtime can discover on demand.",
          evidenceReadiness: "Evidence Readiness",
          evidenceReadinessDescription: "Passed required reports and missing items together indicate acceptance readiness.",
          sourceBreakdown: "Source breakdown",
          statusBreakdown: "Status breakdown"
        },
        eventsAndRisks: {
          eyebrow: "Events & Risks",
          title: "Events and risks",
          description: "Recent critical events and incidents are merged here so you can quickly confirm whether the system has entered an abnormal path."
        }
      }
    },
    workflowEvents: {
      header: {
        eyebrow: "Workflow Pulse",
        title: "Workflow and event flow",
        description: "Queue state, lease state, lock state, and session heartbeats are shown together to help diagnose where execution is stuck."
      },
      metrics: {
        outboxPending: { title: "Outbox Pending", description: "Number of events still waiting to be sent or processed." },
        oldestPending: { title: "Oldest Pending", description: "How long the oldest pending item has been waiting in the queue." },
        leaseState: { title: "Lease State", description: "Current runtime lease state." },
        lockState: { title: "Lock State", description: "Current global or critical mutex state." }
      },
      criticalLane: {
        eyebrow: "Critical Lane",
        title: "Critical event timeline",
        description: "Review recent critical and warning events in time order so you can handle execution-impacting signals first."
      },
      contextPulse: {
        eyebrow: "Context Pulse",
        title: "Context pulse",
        description: "Aggregates message context, event database state, and agent heartbeats so you can see whether the working context is still moving forward.",
        messageContext: "Message Context",
        messageContextDescription: "Total messages retained in the current log context.",
        eventDbRows: "Event DB Rows",
        eventDbRowsDescription: "Total rows written into the event database.",
        currentToolStatus: "Current tool status",
        noToolStatus: "No visible tool status right now.",
        agentHeartbeats: "Agent Heartbeats",
        active: "Active tasks",
        warning: "Warning",
        critical: "Critical",
        blocked: "Blocked",
        heartbeatSummary: "{withHeartbeats}/{sessions} sessions currently have heartbeats, highest stale level {level}.",
        noHeartbeatMessage: "No heartbeat detail",
        noHeartbeats: "There are no visible child-task heartbeats right now.",
        noHeartbeatTasksYet: "There are no active child-task heartbeats right now; the summary above still reflects observed descendant sessions.",
        keyCounters: "Key counters"
      }
    },
    memoryGraph: {
      header: {
        eyebrow: "Memory Graph",
        title: "Session memory graph",
        description: "Shows the L2 quintuple graph, recall posture, and hotspot relations so you can verify that memory extraction is working."
      },
      metrics: {
        recallReadiness: "Recall Readiness",
        quintuples: { title: "Quintuples", description: "Total number of quintuples currently written." },
        activeTasks: { title: "Active Tasks", description: "Memory extraction or write tasks that are still running." },
        vectorIndex: { title: "Vector Index", description: "Whether the vector index is ready to serve recall." }
      },
      graphCanvas: {
        eyebrow: "Graph Canvas",
        title: "Graph sample",
        description: "Recently written relation samples are rendered as a lightweight graph so you can inspect fact connectivity quickly."
      },
      hotspots: {
        eyebrow: "Hotspots",
        title: "Hotspot relations and entities",
        description: "Highlights the most frequent relations, entities, and current task execution states.",
        relation: "Relation hotspots",
        entity: "Entity hotspots",
        pending: "Pending",
        running: "Running",
        failed: "Failed"
      }
    },
    incidents: {
      header: {
        eyebrow: "Incident Desk",
        title: "Incidents and risks",
        description: "Centralizes recent risks, anomalies, and report paths so you can find what needs attention quickly."
      },
      latest: {
        eyebrow: "Latest Incidents",
        title: "Recent incidents",
        description: "Shows the newest incident summaries and linked report paths in time order."
      }
    },
    evidence: {
      header: {
        eyebrow: "Evidence Index",
        title: "Acceptance evidence",
        description: "Keeps required reports and missing items on one page so you can tell whether this run is ready to ship."
      },
      metrics: {
        requiredTotal: { title: "Required Reports", description: "Total number of required reports for this run." },
        requiredPassed: { title: "Required Passed", description: "Required reports that already passed their gate." },
        hardMissing: { title: "Hard Missing", description: "Missing evidence items that directly block acceptance." },
        softMissing: { title: "Soft Missing", description: "Missing evidence items that should be filled in but do not block acceptance yet." }
      },
      reportIndex: {
        eyebrow: "Report Index",
        title: "Report index",
        description: "Lists current evidence report paths, gate levels, and statuses."
      }
    },
    memorySearch: {
      eyebrow: "Memory Search",
      title: "Memory search",
      description: "Search quintuples by keyword directly to verify that memory writes can be queried and recalled.",
      placeholder: "Enter keywords separated by commas, for example agent, workflow",
      submit: "Search",
      submitting: "Searching…",
      initialMeta: "Enter keywords to start searching.",
      resultMeta: "Found {total} results in {elapsed} ms.",
      emptyTitle: "No search results",
      emptyDescription: "Try different keywords, or wait for more quintuples to be written.",
      unknownType: "Unknown type"
    },
    viewModels: {
      recall: {
        ready: "Index ready",
        warming: "Index warming",
        description: "Recall readiness derived from index state, graph size, and task backpressure."
      },
      services: {
        online: "{available}/{total} online",
        discovered: "{total} discovered"
      }
    },
    enums: {
      leaseState: {
        expired: "Expired",
        near_expiry: "Near expiry",
        healthy: "Healthy",
        missing: "Missing",
        unknown: "Unknown"
      },
      lockState: {
        idle: "Idle",
        held: "Held",
        near_expiry: "Near expiry",
        expired: "Expired",
        missing: "Missing",
        unknown: "Unknown"
      },
      staleLevel: {
        none: "None",
        fresh: "Fresh",
        warning: "Warning",
        critical: "Critical",
        blocked: "Blocked",
        unknown: "Unknown"
      },
      routeSemantic: {
        shell_readonly: "Shell readonly",
        shell_clarify: "Shell clarify",
        core_execution: "Core execution",
        unknown: "Unknown"
      },
      mcpStatus: {
        online: "Online",
        offline: "Offline",
        configured: "Configured",
        missing_command: "Missing command",
        available: "Available",
        unknown: "Unknown"
      },
      generic: {
        unknown: "Unknown",
        running: "Running"
      }
    }
};

const messages: TranslationCatalog = {
  "zh-CN": zhCNMessages,
  "en-US": enUSMessages
};

function lookup(tree: TranslationTree, path: string): string | undefined {
  return path.split(".").reduce<TranslationLeaf | TranslationTree | undefined>((current, segment) => {
    if (!current || typeof current === "string") {
      return undefined;
    }
    return current[segment];
  }, tree) as string | undefined;
}

function interpolate(template: string, values?: Record<string, string | number>) {
  if (!values) {
    return template;
  }
  return Object.entries(values).reduce((result, [key, value]) => result.replaceAll(`{${key}}`, String(value)), template);
}

export function normalizeLocale(rawValue?: string | null): AppLocale {
  const value = String(rawValue ?? "").trim().toLowerCase();
  if (!value) {
    return DEFAULT_LOCALE;
  }
  if (value.startsWith("en")) {
    return "en-US";
  }
  if (value.startsWith("zh")) {
    return "zh-CN";
  }
  return DEFAULT_LOCALE;
}

export function matchLocaleFromAcceptLanguage(rawHeader?: string | null): AppLocale {
  return normalizeLocale(rawHeader?.split(",")[0] ?? DEFAULT_LOCALE);
}

export function translate(locale: AppLocale, key: string, values?: Record<string, string | number>): string {
  const localized = lookup(messages[locale], key) ?? lookup(messages[DEFAULT_LOCALE], key) ?? key;
  return interpolate(localized, values);
}

export function createTranslator(locale: AppLocale) {
  return (key: string, values?: Record<string, string | number>) => translate(locale, key, values);
}

export function getLocaleOptions(locale: AppLocale) {
  return [
    { value: "zh-CN" as const, label: translate(locale, "common.locale.zhCN") },
    { value: "en-US" as const, label: translate(locale, "common.locale.enUS") }
  ];
}

export function getStatusLabel(locale: AppLocale, severity: string) {
  return translate(locale, `common.status.${severity}`);
}

export function getModeLabel(locale: AppLocale, mode: string) {
  return translate(locale, `common.mode.${mode}`);
}

export function humanizeEnum(locale: AppLocale, category: string, value: unknown) {
  const normalized = String(value ?? "").trim();
  if (!normalized) {
    return translate(locale, "common.label.unknown");
  }
  const key = normalized.toLowerCase();
  const translated = translate(locale, `enums.${category}.${key}`);
  return translated === `enums.${category}.${key}` ? normalized : translated;
}
