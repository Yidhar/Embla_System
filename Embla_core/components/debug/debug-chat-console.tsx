"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  fetchDebugRouteBridge,
  fetchPromptTemplate,
  fetchPromptTemplates,
  fetchDebugHealth,
  fetchDebugSystemInfo,
  savePromptTemplate,
  sendDebugChatMessage,
  type DebugRouteBridgePayload,
  type DebugRouteDecision,
  type DebugChatReply,
  type DebugHealthPayload,
  type PromptTemplateMeta,
  type DebugSystemInfoPayload,
} from "@/lib/api/debug-chat";
import { formatIsoDateTime, formatNumber, type AppLang } from "@/lib/i18n";

type DebugChatConsoleProps = {
  lang: AppLang;
};

type ChatItem = {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  reasoning?: string;
  timestamp: string;
};

const PAGE_COPY: Record<
  AppLang,
  {
    title: string;
    subtitle: string;
    cards: {
      health: string;
      agentReady: string;
      backendVersion: string;
      apiKey: string;
      session: string;
    };
    words: {
      healthy: string;
      unhealthy: string;
      ready: string;
      notReady: string;
      configured: string;
      notConfigured: string;
      none: string;
      probe: string;
      probing: string;
      resetSession: string;
      send: string;
      sending: string;
      placeholder: string;
      emptyChat: string;
      assistant: string;
      user: string;
      system: string;
      reasoning: string;
      lastProbe: string;
      probeFailed: string;
      noReasoning: string;
      inputRequired: string;
      requestFailed: string;
      noRouteDecision: string;
      noRouteEvents: string;
      routeBridgeLoadFailed: string;
      unknown: string;
    };
    route: {
      title: string;
      subtitle: string;
      latestDecision: string;
      bridgeSnapshot: string;
      path: string;
      delegationIntent: string;
      promptProfile: string;
      injectionMode: string;
      riskLevel: string;
      clarifyBudget: string;
      budgetEscalated: string;
      budgetReason: string;
      outerSession: string;
      coreSession: string;
      executionSession: string;
      coreSessionCreated: string;
      coreSessionExists: string;
      lastExecutionSession: string;
      lastCoreEscalationAt: string;
      recentEvents: string;
      eventPath: string;
      eventPromptProfile: string;
      eventTimestamp: string;
      eventSource: string;
    };
    prompts: {
      title: string;
      subtitle: string;
      template: string;
      refresh: string;
      loading: string;
      updatedAt: string;
      tokenEstimate: string;
      content: string;
      save: string;
      saving: string;
      empty: string;
      selectRequired: string;
      listFailed: string;
      loadFailed: string;
      saveFailed: string;
      saveSuccess: string;
    };
  }
> = {
  en: {
    title: "Debug Chat",
    subtitle: "Lightweight conversation channel for liveness checks and backend debugging.",
    cards: {
      health: "API Health",
      agentReady: "Agent Ready",
      backendVersion: "Backend Version",
      apiKey: "API Key",
      session: "Session ID",
    },
    words: {
      healthy: "healthy",
      unhealthy: "unhealthy",
      ready: "ready",
      notReady: "not ready",
      configured: "configured",
      notConfigured: "not configured",
      none: "none",
      probe: "Probe",
      probing: "Probing...",
      resetSession: "Reset Session",
      send: "Send",
      sending: "Sending...",
      placeholder: "Type a debug prompt...",
      emptyChat: "No message yet. Send one probe question to verify backend conversation path.",
      assistant: "Assistant",
      user: "User",
      system: "System",
      reasoning: "Reasoning",
      lastProbe: "Last probe",
      probeFailed: "Probe failed: backend not reachable.",
      noReasoning: "No reasoning content.",
      inputRequired: "Message cannot be empty.",
      requestFailed: "Request failed",
      noRouteDecision: "No route decision yet. Send one message to observe routing.",
      noRouteEvents: "No route events yet.",
      routeBridgeLoadFailed: "Failed to load route bridge snapshot",
      unknown: "unknown",
    },
    route: {
      title: "Route Observability",
      subtitle: "Expose outer/core routing decision and session bridge for debugging.",
      latestDecision: "Latest Decision",
      bridgeSnapshot: "Session Bridge",
      path: "Path",
      delegationIntent: "Delegation Intent",
      promptProfile: "Prompt Profile",
      injectionMode: "Injection Mode",
      riskLevel: "Risk Level",
      clarifyBudget: "Clarify Budget",
      budgetEscalated: "Budget Escalated",
      budgetReason: "Escalation Reason",
      outerSession: "Outer Session",
      coreSession: "Core Session",
      executionSession: "Execution Session",
      coreSessionCreated: "Core Session Created",
      coreSessionExists: "Core Session Exists",
      lastExecutionSession: "Last Execution Session",
      lastCoreEscalationAt: "Last Core Escalation",
      recentEvents: "Recent Route Events",
      eventPath: "Path",
      eventPromptProfile: "Prompt Profile",
      eventTimestamp: "Timestamp",
      eventSource: "Source",
    },
    prompts: {
      title: "Prompts Hub",
      subtitle: "Centralized prompt template management for runtime debugging.",
      template: "Template",
      refresh: "Refresh",
      loading: "Loading prompt template...",
      updatedAt: "Updated at",
      tokenEstimate: "Estimated Tokens",
      content: "Prompt Content",
      save: "Save Prompt",
      saving: "Saving...",
      empty: "No prompt template found.",
      selectRequired: "Please select a prompt template.",
      listFailed: "Failed to load prompt template list.",
      loadFailed: "Failed to load prompt template.",
      saveFailed: "Failed to save prompt template.",
      saveSuccess: "Prompt template saved.",
    },
  },
  "zh-CN": {
    title: "调试会话",
    subtitle: "用于存活验证与后端调试的轻量对话通道。",
    cards: {
      health: "API 健康",
      agentReady: "Agent 就绪",
      backendVersion: "后端版本",
      apiKey: "API 密钥",
      session: "会话 ID",
    },
    words: {
      healthy: "健康",
      unhealthy: "异常",
      ready: "就绪",
      notReady: "未就绪",
      configured: "已配置",
      notConfigured: "未配置",
      none: "无",
      probe: "探测",
      probing: "探测中...",
      resetSession: "重置会话",
      send: "发送",
      sending: "发送中...",
      placeholder: "输入一条调试消息...",
      emptyChat: "暂无消息。发送一条探测问题以验证会话链路。",
      assistant: "助手",
      user: "用户",
      system: "系统",
      reasoning: "思考内容",
      lastProbe: "上次探测",
      probeFailed: "探测失败：后端不可达。",
      noReasoning: "无思考内容。",
      inputRequired: "消息不能为空。",
      requestFailed: "请求失败",
      noRouteDecision: "暂无路由决策。发送一条消息后可查看分流结果。",
      noRouteEvents: "暂无路由事件。",
      routeBridgeLoadFailed: "加载路由桥接快照失败",
      unknown: "未知",
    },
    route: {
      title: "路由可观测性",
      subtitle: "展示 outer/core 路由决策与会话桥接状态，便于调试。",
      latestDecision: "最新决策",
      bridgeSnapshot: "会话桥接",
      path: "路径",
      delegationIntent: "委派意图",
      promptProfile: "Prompt 配置",
      injectionMode: "注入模式",
      riskLevel: "风险等级",
      clarifyBudget: "澄清预算",
      budgetEscalated: "预算升级",
      budgetReason: "升级原因",
      outerSession: "外层会话",
      coreSession: "核心会话",
      executionSession: "执行会话",
      coreSessionCreated: "核心会话新建",
      coreSessionExists: "核心会话存在",
      lastExecutionSession: "最近执行会话",
      lastCoreEscalationAt: "最近升级时间",
      recentEvents: "最近路由事件",
      eventPath: "路径",
      eventPromptProfile: "Prompt 配置",
      eventTimestamp: "时间",
      eventSource: "来源",
    },
    prompts: {
      title: "Prompts 管理",
      subtitle: "集中管理运行时提示词模板，用于调试与运维。",
      template: "模板",
      refresh: "刷新",
      loading: "正在加载提示词模板...",
      updatedAt: "更新时间",
      tokenEstimate: "预估 Token",
      content: "Prompt 内容",
      save: "保存 Prompt",
      saving: "保存中...",
      empty: "未发现可用的提示词模板。",
      selectRequired: "请先选择提示词模板。",
      listFailed: "加载提示词模板列表失败。",
      loadFailed: "加载提示词模板失败。",
      saveFailed: "保存提示词模板失败。",
      saveSuccess: "提示词模板已保存。",
    },
  },
};

function nowIso(): string {
  return new Date().toISOString();
}

function toRoleLabel(role: ChatItem["role"], lang: AppLang): string {
  const copy = PAGE_COPY[lang].words;
  if (role === "assistant") {
    return copy.assistant;
  }
  if (role === "user") {
    return copy.user;
  }
  return copy.system;
}

function shortSessionId(value: string): string {
  if (!value) {
    return "--";
  }
  if (value.length <= 14) {
    return value;
  }
  return `${value.slice(0, 8)}...${value.slice(-4)}`;
}

function estimateTokenCount(content: string): number {
  const text = String(content || "").trim();
  if (!text) {
    return 0;
  }
  return Math.max(1, Math.round(text.length / 4));
}

function formatEpochMs(value: unknown, lang: AppLang): string {
  const normalized = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(normalized) || normalized <= 0) {
    return "--";
  }
  return formatIsoDateTime(new Date(normalized).toISOString(), lang);
}

export function DebugChatConsole({ lang }: DebugChatConsoleProps) {
  const copy = PAGE_COPY[lang];
  const [health, setHealth] = useState<DebugHealthPayload | null>(null);
  const [systemInfo, setSystemInfo] = useState<DebugSystemInfoPayload | null>(null);
  const [probeAt, setProbeAt] = useState<string>("");
  const [probing, setProbing] = useState(false);
  const [sessionId, setSessionId] = useState("");
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [items, setItems] = useState<ChatItem[]>([]);
  const [error, setError] = useState("");
  const [promptTemplates, setPromptTemplates] = useState<PromptTemplateMeta[]>([]);
  const [promptName, setPromptName] = useState("");
  const [promptContent, setPromptContent] = useState("");
  const [promptUpdatedAt, setPromptUpdatedAt] = useState("");
  const [promptLoading, setPromptLoading] = useState(false);
  const [promptSaving, setPromptSaving] = useState(false);
  const [promptError, setPromptError] = useState("");
  const [promptMessage, setPromptMessage] = useState("");
  const [latestRouteDecision, setLatestRouteDecision] = useState<DebugRouteDecision | null>(null);
  const [routeBridge, setRouteBridge] = useState<DebugRouteBridgePayload | null>(null);
  const [routeBridgeError, setRouteBridgeError] = useState("");
  const didAutoProbe = useRef(false);
  const didAutoLoadPrompts = useRef(false);

  const healthText = useMemo(() => {
    if (health?.status === "healthy") {
      return copy.words.healthy;
    }
    return copy.words.unhealthy;
  }, [copy.words.healthy, copy.words.unhealthy, health?.status]);

  const runProbe = useCallback(async () => {
    setProbing(true);
    setError("");
    const [healthPayload, systemInfoPayload] = await Promise.all([fetchDebugHealth(), fetchDebugSystemInfo()]);
    setProbing(false);
    setProbeAt(nowIso());
    setHealth(healthPayload);
    setSystemInfo(systemInfoPayload);
    if (!healthPayload || !systemInfoPayload) {
      setError(copy.words.probeFailed);
    }
  }, [copy.words.probeFailed]);

  const loadPromptTemplate = useCallback(
    async (name: string) => {
      setPromptLoading(true);
      setPromptError("");
      setPromptMessage("");
      const result = await fetchPromptTemplate(name);
      setPromptLoading(false);
      if (!result.ok || !result.data) {
        setPromptError(`${copy.prompts.loadFailed} ${result.error || "--"}`);
        return;
      }
      setPromptName(String(result.data.name || name));
      setPromptContent(String(result.data.content || ""));
      setPromptUpdatedAt(String(result.data.meta?.updated_at || ""));
    },
    [copy.prompts.loadFailed],
  );

  const loadPromptTemplateList = useCallback(async () => {
    setPromptLoading(true);
    setPromptError("");
    setPromptMessage("");
    const result = await fetchPromptTemplates();
    if (!result.ok) {
      setPromptLoading(false);
      setPromptTemplates([]);
      setPromptError(`${copy.prompts.listFailed} ${result.error || "--"}`);
      return;
    }

    const templates = result.prompts;
    setPromptTemplates(templates);
    if (templates.length === 0) {
      setPromptLoading(false);
      setPromptName("");
      setPromptContent("");
      setPromptUpdatedAt("");
      return;
    }

    const preferred = templates.find((item) => item.name === "conversation_style_prompt");
    const nextName = (promptName && templates.some((item) => item.name === promptName) ? promptName : preferred?.name || templates[0]?.name || "").trim();
    if (!nextName) {
      setPromptLoading(false);
      return;
    }
    await loadPromptTemplate(nextName);
  }, [copy.prompts.listFailed, loadPromptTemplate, promptName]);

  const loadRouteBridge = useCallback(
    async (activeSessionId: string) => {
      const normalizedSessionId = String(activeSessionId || "").trim();
      if (!normalizedSessionId) {
        setRouteBridge(null);
        setRouteBridgeError("");
        return;
      }
      const result = await fetchDebugRouteBridge({ sessionId: normalizedSessionId, limit: 8 });
      if (!result.ok || !result.data) {
        setRouteBridge(null);
        setRouteBridgeError(`${copy.words.routeBridgeLoadFailed}: ${result.error || "--"}`);
        return;
      }
      setRouteBridge(result.data);
      setRouteBridgeError("");
    },
    [copy.words.routeBridgeLoadFailed],
  );

  useEffect(() => {
    if (didAutoProbe.current) {
      return;
    }
    didAutoProbe.current = true;
    void runProbe();
  }, [runProbe]);

  useEffect(() => {
    if (didAutoLoadPrompts.current) {
      return;
    }
    didAutoLoadPrompts.current = true;
    void loadPromptTemplateList();
  }, [loadPromptTemplateList]);

  useEffect(() => {
    if (!sessionId) {
      setRouteBridge(null);
      setRouteBridgeError("");
      return;
    }
    void loadRouteBridge(sessionId);
  }, [loadRouteBridge, sessionId]);

  const resetSession = () => {
    setSessionId("");
    setLatestRouteDecision(null);
    setRouteBridge(null);
    setRouteBridgeError("");
    setItems((prev) => [
      ...prev,
      {
        id: `sys-${Date.now()}`,
        role: "system",
        content: copy.words.resetSession,
        timestamp: nowIso(),
      },
    ]);
  };

  const sendMessage = async () => {
    const text = input.trim();
    if (!text) {
      setError(copy.words.inputRequired);
      return;
    }
    setSending(true);
    setError("");

    const userItem: ChatItem = {
      id: `user-${Date.now()}`,
      role: "user",
      content: text,
      timestamp: nowIso(),
    };
    setItems((prev) => [...prev, userItem]);
    setInput("");

    const result = await sendDebugChatMessage({ message: text, sessionId: sessionId || undefined });
    setSending(false);

    if (!result.ok || !result.data) {
      const errText = `${copy.words.requestFailed}: ${result.error || "--"}`;
      setError(errText);
      setItems((prev) => [
        ...prev,
        {
          id: `sys-error-${Date.now()}`,
          role: "system",
          content: errText,
          timestamp: nowIso(),
        },
      ]);
      return;
    }

    const payload: DebugChatReply = result.data;
    setLatestRouteDecision(payload.route_decision || null);
    const nextSessionId = String(payload.session_id || sessionId || "");
    if (nextSessionId) {
      setSessionId(nextSessionId);
      if (nextSessionId === sessionId) {
        await loadRouteBridge(nextSessionId);
      }
    }

    setItems((prev) => [
      ...prev,
      {
        id: `assistant-${Date.now()}`,
        role: "assistant",
        content: String(payload.response || ""),
        reasoning: String(payload.reasoning_content || ""),
        timestamp: nowIso(),
      },
    ]);
  };

  const savePrompt = async () => {
    const normalizedName = promptName.trim();
    if (!normalizedName) {
      setPromptError(copy.prompts.selectRequired);
      return;
    }
    setPromptSaving(true);
    setPromptError("");
    setPromptMessage("");
    const result = await savePromptTemplate({
      name: normalizedName,
      content: promptContent,
    });
    setPromptSaving(false);
    if (!result.ok) {
      setPromptError(`${copy.prompts.saveFailed} ${result.error || "--"}`);
      return;
    }
    setPromptMessage(copy.prompts.saveSuccess);
    await loadPromptTemplateList();
  };

  const routeEvents = Array.isArray(routeBridge?.recent_route_events) ? routeBridge.recent_route_events : [];
  const clarifyTurns = Number(latestRouteDecision?.path_b_clarify_turns ?? routeBridge?.state?.path_b_clarify_turns ?? 0);
  const clarifyLimit = Number(latestRouteDecision?.path_b_clarify_limit ?? routeBridge?.state?.path_b_clarify_limit ?? 0);

  return (
    <div className="space-y-6">
      <section className="glass-card p-6">
        <p className="text-[10px] font-bold uppercase tracking-[0.25em] text-gray-500">{copy.title}</p>
        <h2 className="mt-2 text-2xl font-extrabold tracking-tight text-[#1c1c1e]">{copy.subtitle}</h2>
        <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-5">
          <div className="rounded-xl bg-white/70 px-3 py-2 text-xs text-gray-700">
            {copy.cards.health}: <span className="font-bold">{healthText}</span>
          </div>
          <div className="rounded-xl bg-white/70 px-3 py-2 text-xs text-gray-700">
            {copy.cards.agentReady}:{" "}
            <span className="font-bold">{health?.agent_ready ? copy.words.ready : copy.words.notReady}</span>
          </div>
          <div className="rounded-xl bg-white/70 px-3 py-2 text-xs text-gray-700">
            {copy.cards.backendVersion}: <span className="font-bold">{systemInfo?.version || "--"}</span>
          </div>
          <div className="rounded-xl bg-white/70 px-3 py-2 text-xs text-gray-700">
            {copy.cards.apiKey}:{" "}
            <span className="font-bold">{systemInfo?.api_key_configured ? copy.words.configured : copy.words.notConfigured}</span>
          </div>
          <div className="rounded-xl bg-white/70 px-3 py-2 text-xs text-gray-700">
            {copy.cards.session}: <span className="font-bold">{shortSessionId(sessionId || copy.words.none)}</span>
          </div>
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => void runProbe()}
            disabled={probing}
            className="rounded-xl border border-gray-200/60 bg-white/80 px-4 py-2 text-xs font-bold uppercase tracking-[0.18em] text-gray-700 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-60"
          >
            {probing ? copy.words.probing : copy.words.probe}
          </button>
          <button
            type="button"
            onClick={resetSession}
            className="rounded-xl border border-white/70 bg-[#1c1c1e] px-4 py-2 text-xs font-bold uppercase tracking-[0.18em] text-white active:scale-[0.98]"
          >
            {copy.words.resetSession}
          </button>
          <span className="text-xs text-gray-500">
            {copy.words.lastProbe}: {probeAt ? formatIsoDateTime(probeAt, lang) : "--"}
          </span>
        </div>
        {error ? <p className="mt-3 text-sm text-rose-600">{error}</p> : null}
      </section>

      <section className="glass-card p-6">
        <div className="space-y-3">
          <label className="block">
            <textarea
              value={input}
              onChange={(event) => setInput(event.target.value)}
              placeholder={copy.words.placeholder}
              className="h-24 w-full rounded-2xl border border-gray-200/60 bg-white/80 p-4 text-sm text-gray-700 outline-none"
            />
          </label>
          <div className="flex items-center justify-end">
            <button
              type="button"
              onClick={() => void sendMessage()}
              disabled={sending}
              className="rounded-xl border border-white/70 bg-[#1c1c1e] px-4 py-2 text-xs font-bold uppercase tracking-[0.18em] text-white active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {sending ? copy.words.sending : copy.words.send}
            </button>
          </div>
        </div>
      </section>

      <section className="glass-card p-6">
        {items.length === 0 ? (
          <p className="text-sm text-gray-500">{copy.words.emptyChat}</p>
        ) : (
          <div className="space-y-3">
            {items.map((item, idx) => (
              <article key={`${item.id}-${idx}`} className="rounded-2xl border border-gray-200/60 bg-white/80 p-4">
                <div className="flex items-center justify-between gap-3">
                  <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-gray-500">{toRoleLabel(item.role, lang)}</p>
                  <p className="text-[10px] font-mono text-gray-500">{formatIsoDateTime(item.timestamp, lang)}</p>
                </div>
                <p className="mt-2 whitespace-pre-wrap text-sm text-gray-700">{item.content || "--"}</p>
                {item.role === "assistant" ? (
                  <details className="mt-3 rounded-xl bg-white/70 p-3 text-xs text-gray-700">
                    <summary className="cursor-pointer font-bold">{copy.words.reasoning}</summary>
                    <pre className="mt-2 whitespace-pre-wrap font-mono text-[11px]">
                      {item.reasoning ? item.reasoning : copy.words.noReasoning}
                    </pre>
                  </details>
                ) : null}
              </article>
            ))}
          </div>
        )}
      </section>

      <section className="glass-card p-6">
        <p className="text-[10px] font-bold uppercase tracking-[0.25em] text-gray-500">{copy.route.title}</p>
        <p className="mt-2 text-sm text-gray-600">{copy.route.subtitle}</p>
        <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
          <article className="rounded-2xl border border-gray-200/60 bg-white/80 p-4">
            <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-gray-500">{copy.route.latestDecision}</p>
            {!latestRouteDecision ? (
              <p className="mt-3 text-sm text-gray-500">{copy.words.noRouteDecision}</p>
            ) : (
              <div className="mt-3 space-y-2 text-xs text-gray-700">
                <p>
                  {copy.route.path}: <span className="font-mono font-semibold">{latestRouteDecision.path || copy.words.unknown}</span>
                </p>
                <p>
                  {copy.route.delegationIntent}:{" "}
                  <span className="font-mono font-semibold">{latestRouteDecision.delegation_intent || copy.words.unknown}</span>
                </p>
                <p>
                  {copy.route.promptProfile}:{" "}
                  <span className="font-mono font-semibold">{latestRouteDecision.prompt_profile || copy.words.unknown}</span>
                </p>
                <p>
                  {copy.route.injectionMode}:{" "}
                  <span className="font-mono font-semibold">{latestRouteDecision.injection_mode || copy.words.unknown}</span>
                </p>
                <p>
                  {copy.route.riskLevel}: <span className="font-mono font-semibold">{latestRouteDecision.risk_level || copy.words.unknown}</span>
                </p>
                <p>
                  {copy.route.clarifyBudget}:{" "}
                  <span className="font-mono font-semibold">
                    {formatNumber(clarifyTurns, lang, { maximumFractionDigits: 0, fallback: "0" })}/
                    {formatNumber(clarifyLimit, lang, { maximumFractionDigits: 0, fallback: "0" })}
                  </span>
                </p>
                <p>
                  {copy.route.budgetEscalated}:{" "}
                  <span className="font-mono font-semibold">{String(Boolean(latestRouteDecision.path_b_budget_escalated))}</span>
                </p>
                <p>
                  {copy.route.budgetReason}:{" "}
                  <span className="font-mono font-semibold">{latestRouteDecision.path_b_budget_reason || "--"}</span>
                </p>
                <p>
                  {copy.route.outerSession}:{" "}
                  <span className="font-mono font-semibold">{shortSessionId(String(latestRouteDecision.outer_session_id || ""))}</span>
                </p>
                <p>
                  {copy.route.coreSession}:{" "}
                  <span className="font-mono font-semibold">{shortSessionId(String(latestRouteDecision.core_session_id || ""))}</span>
                </p>
                <p>
                  {copy.route.executionSession}:{" "}
                  <span className="font-mono font-semibold">{shortSessionId(String(latestRouteDecision.execution_session_id || ""))}</span>
                </p>
                <p>
                  {copy.route.coreSessionCreated}:{" "}
                  <span className="font-mono font-semibold">{String(Boolean(latestRouteDecision.core_session_created))}</span>
                </p>
              </div>
            )}
          </article>

          <article className="rounded-2xl border border-gray-200/60 bg-white/80 p-4">
            <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-gray-500">{copy.route.bridgeSnapshot}</p>
            {routeBridge ? (
              <div className="mt-3 space-y-2 text-xs text-gray-700">
                <p>
                  {copy.route.outerSession}: <span className="font-mono font-semibold">{shortSessionId(String(routeBridge.outer_session_id || ""))}</span>
                </p>
                <p>
                  {copy.route.coreSession}: <span className="font-mono font-semibold">{shortSessionId(String(routeBridge.core_session_id || ""))}</span>
                </p>
                <p>
                  {copy.route.executionSession}:{" "}
                  <span className="font-mono font-semibold">{shortSessionId(String(routeBridge.execution_session_id || ""))}</span>
                </p>
                <p>
                  {copy.route.coreSessionExists}: <span className="font-mono font-semibold">{String(Boolean(routeBridge.core_session_exists))}</span>
                </p>
                <p>
                  {copy.route.lastExecutionSession}:{" "}
                  <span className="font-mono font-semibold">{shortSessionId(String(routeBridge.state?.last_execution_session_id || ""))}</span>
                </p>
                <p>
                  {copy.route.lastCoreEscalationAt}:{" "}
                  <span className="font-mono font-semibold">{formatEpochMs(routeBridge.state?.last_core_escalation_at_ms, lang)}</span>
                </p>
              </div>
            ) : (
              <p className="mt-3 text-sm text-gray-500">{copy.words.noRouteDecision}</p>
            )}
            {routeBridgeError ? <p className="mt-3 text-sm text-rose-600">{routeBridgeError}</p> : null}
          </article>
        </div>

        <div className="mt-4 rounded-2xl border border-gray-200/60 bg-white/80 p-4">
          <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-gray-500">{copy.route.recentEvents}</p>
          {routeEvents.length === 0 ? (
            <p className="mt-3 text-sm text-gray-500">{copy.words.noRouteEvents}</p>
          ) : (
            <div className="mt-3 space-y-3">
              {routeEvents.map((item, idx) => (
                <article key={`route-event-${idx}`} className="rounded-xl border border-gray-200/50 bg-white/80 p-3 text-xs text-gray-700">
                  <p>
                    {copy.route.eventTimestamp}: <span className="font-mono">{formatIsoDateTime(item.timestamp, lang)}</span>
                  </p>
                  <p className="mt-1">
                    {copy.route.eventPath}: <span className="font-mono">{item.path || "--"}</span>
                  </p>
                  <p className="mt-1">
                    {copy.route.eventPromptProfile}: <span className="font-mono">{item.prompt_profile || "--"}</span>
                  </p>
                  <p className="mt-1">
                    {copy.route.eventSource}: <span className="font-mono">{item.source || "--"}</span>
                  </p>
                </article>
              ))}
            </div>
          )}
        </div>
      </section>

      <section className="glass-card p-6 text-xs text-gray-600">
        <p>
          token_hint: {formatNumber(items.length, lang, { maximumFractionDigits: 0, fallback: "--" })} items
        </p>
      </section>

      <section className="glass-card p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-[10px] font-bold uppercase tracking-[0.25em] text-gray-500">{copy.prompts.title}</p>
            <p className="mt-2 text-sm text-gray-600">{copy.prompts.subtitle}</p>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => void loadPromptTemplateList()}
              disabled={promptLoading}
              className="rounded-xl border border-gray-200/60 bg-white/80 px-4 py-2 text-xs font-bold uppercase tracking-[0.18em] text-gray-700 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {copy.prompts.refresh}
            </button>
            <button
              type="button"
              onClick={() => void savePrompt()}
              disabled={promptSaving || promptLoading}
              className="rounded-xl border border-white/70 bg-[#1c1c1e] px-4 py-2 text-xs font-bold uppercase tracking-[0.18em] text-white active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {promptSaving ? copy.prompts.saving : copy.prompts.save}
            </button>
          </div>
        </div>

        <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-[240px_1fr]">
          <label className="block">
            <p className="mb-1 text-xs text-gray-600">{copy.prompts.template}</p>
            <select
              value={promptName}
              onChange={(event) => {
                const nextName = event.target.value;
                setPromptName(nextName);
                if (nextName) {
                  void loadPromptTemplate(nextName);
                }
              }}
              className="h-10 w-full rounded-xl border border-white/70 bg-white/85 px-3 text-sm outline-none"
            >
              {promptTemplates.length === 0 ? <option value="">{copy.prompts.empty}</option> : null}
              {promptTemplates.map((item) => (
                <option key={item.name} value={item.name}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>
          <div className="rounded-xl bg-white/80 px-3 py-2 text-xs text-gray-600">
            <p>
              {copy.prompts.updatedAt}: {promptUpdatedAt ? formatIsoDateTime(promptUpdatedAt, lang) : "--"}
            </p>
            <p className="mt-1">
              {copy.prompts.tokenEstimate}: {formatNumber(estimateTokenCount(promptContent), lang, { maximumFractionDigits: 0, fallback: "--" })}
            </p>
          </div>
        </div>

        <label className="mt-4 block">
          <p className="mb-1 text-xs text-gray-600">{copy.prompts.content}</p>
          <textarea
            value={promptContent}
            onChange={(event) => setPromptContent(event.target.value)}
            placeholder={copy.prompts.loading}
            className="h-72 w-full rounded-2xl border border-gray-200/60 bg-white/80 p-4 font-mono text-xs text-gray-700 outline-none"
            spellCheck={false}
          />
        </label>

        {promptLoading ? <p className="mt-3 text-sm text-gray-500">{copy.prompts.loading}</p> : null}
        {promptError ? <p className="mt-3 text-sm text-rose-600">{promptError}</p> : null}
        {promptMessage ? <p className="mt-3 text-sm text-emerald-600">{promptMessage}</p> : null}
      </section>
    </div>
  );
}
