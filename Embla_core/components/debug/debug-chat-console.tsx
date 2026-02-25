"use client";

import { useMemo, useState } from "react";
import {
  fetchDebugHealth,
  fetchDebugSystemInfo,
  sendDebugChatMessage,
  type DebugChatReply,
  type DebugHealthPayload,
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

  const healthText = useMemo(() => {
    if (health?.status === "healthy") {
      return copy.words.healthy;
    }
    return copy.words.unhealthy;
  }, [copy.words.healthy, copy.words.unhealthy, health?.status]);

  const runProbe = async () => {
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
  };

  const resetSession = () => {
    setSessionId("");
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
    const nextSessionId = String(payload.session_id || sessionId || "");
    if (nextSessionId) {
      setSessionId(nextSessionId);
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

      <section className="glass-card p-6 text-xs text-gray-600">
        <p>
          token_hint: {formatNumber(items.length, lang, { maximumFractionDigits: 0, fallback: "--" })} items
        </p>
      </section>
    </div>
  );
}
