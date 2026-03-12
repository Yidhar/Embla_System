"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { EmptyState, GlassPanel } from "@/components/dashboard-ui";
import { cx } from "@/lib/format";
import { AppLocale, createTranslator } from "@/lib/i18n";
import { buildBrowserApiUrl, extractApiErrorMessage } from "@/lib/client-api";
import { ChatSessionMessage, ShellToolDefinition } from "@/lib/types";

type ChatOpsConsoleProps = {
  locale: AppLocale;
  selectedSessionId?: string;
  initialMessages?: ChatSessionMessage[];
  initialTools?: ShellToolDefinition[];
};

type StreamEventPayload = Record<string, unknown>;

function normalizeShellToolDefinitions(input: unknown): ShellToolDefinition[] {
  if (!Array.isArray(input)) {
    return [];
  }
  const normalized: ShellToolDefinition[] = [];
  for (const item of input) {
    if (!item || typeof item !== "object") {
      continue;
    }
    const row = item as Record<string, unknown>;
    const name = String(row.name ?? "").trim();
    if (!name) {
      continue;
    }
    normalized.push({
      name,
      description: String(row.description ?? "").trim(),
      parameters: row.parameters && typeof row.parameters === "object" && !Array.isArray(row.parameters)
        ? (row.parameters as Record<string, unknown>)
        : {}
    });
  }
  return normalized;
}

function getEventText(payload: StreamEventPayload) {
  const text = payload.text;
  if (typeof text === "string") {
    return text;
  }
  if (typeof payload.message === "string") {
    return payload.message;
  }
  if (typeof payload.error === "string") {
    return payload.error;
  }
  return "";
}

function consumeSseFrames(
  chunk: string,
  onEvent: (payload: StreamEventPayload) => void
) {
  const normalized = chunk.replace(/\r\n/g, "\n");
  const frames = normalized.split("\n\n");
  const remainder = frames.pop() ?? "";

  for (const frame of frames) {
    const lines = frame
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean);
    const dataLines = lines
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trim());
    if (dataLines.length === 0) {
      continue;
    }
    const payloadText = dataLines.join("\n");
    if (!payloadText || payloadText === "[DONE]") {
      continue;
    }
    try {
      const payload = JSON.parse(payloadText) as StreamEventPayload;
      onEvent(payload);
    } catch {
      continue;
    }
  }

  return remainder;
}

export function ChatOpsConsole({
  locale,
  selectedSessionId = "",
  initialMessages = [],
  initialTools = []
}: ChatOpsConsoleProps) {
  const t = createTranslator(locale);
  const router = useRouter();
  const [sessionId, setSessionId] = useState(selectedSessionId);
  const [messages, setMessages] = useState<ChatSessionMessage[]>(initialMessages);
  const [availableTools, setAvailableTools] = useState<ShellToolDefinition[]>(initialTools);
  const [draft, setDraft] = useState("");
  const [reasoning, setReasoning] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setSessionId(selectedSessionId);
    setMessages(initialMessages);
    setAvailableTools(initialTools);
    setReasoning("");
    setError(null);
  }, [initialMessages, initialTools, selectedSessionId]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const nextDraft = draft.trim();
    if (!nextDraft || pending) {
      return;
    }

    setPending(true);
    setError(null);
    setReasoning("");
    setMessages((current) => [
      ...current,
      { role: "user", content: nextDraft },
      { role: "assistant", content: "" }
    ]);
    setDraft("");

    try {
      const response = await fetch(buildBrowserApiUrl("/v1/chat/stream"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: nextDraft,
          session_id: sessionId || undefined,
          stream: true,
          stream_protocol: "sse_json_v1"
        })
      });
      if (!response.ok) {
        const rawText = await response.text();
        let payload: unknown = rawText;
        try {
          payload = JSON.parse(rawText) as unknown;
        } catch {
          payload = { detail: rawText };
        }
        throw new Error(extractApiErrorMessage(payload, t("chatops.console.submitError")));
      }
      if (!response.body) {
        throw new Error(t("chatops.console.submitError"));
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let effectiveSessionId = String(sessionId ?? "").trim();

      const applyAssistantText = (text: string) => {
        if (!text) {
          return;
        }
        setMessages((current) => {
          const next = [...current];
          for (let index = next.length - 1; index >= 0; index -= 1) {
            if (String(next[index]?.role).toLowerCase() === "assistant") {
              next[index] = {
                ...next[index],
                content: `${String(next[index]?.content ?? "")}${text}`
              };
              return next;
            }
          }
          next.push({ role: "assistant", content: text });
          return next;
        });
      };

      const handlePayload = (payload: StreamEventPayload) => {
        const eventType = String(payload.type ?? "").trim();
        if (eventType === "session_meta") {
          effectiveSessionId = String(payload.session_id ?? effectiveSessionId ?? "").trim();
          setSessionId(effectiveSessionId);
          return;
        }
        if (eventType === "available_tools") {
          setAvailableTools(normalizeShellToolDefinitions(payload.tools));
          return;
        }
        if (eventType === "content") {
          applyAssistantText(getEventText(payload));
          return;
        }
        if (eventType === "reasoning") {
          const text = getEventText(payload);
          if (text) {
            setReasoning((current) => `${current}${text}`);
          }
          return;
        }
        if (eventType === "error") {
          const text = getEventText(payload) || t("chatops.console.submitError");
          setError(text);
        }
      };

      while (true) {
        const { value, done } = await reader.read();
        if (done) {
          buffer += decoder.decode();
          buffer = consumeSseFrames(buffer, handlePayload);
          break;
        }
        buffer += decoder.decode(value, { stream: true });
        buffer = consumeSseFrames(buffer, handlePayload);
      }

      if (effectiveSessionId) {
        router.replace(`/chatops?session_id=${encodeURIComponent(effectiveSessionId)}`);
      }
      router.refresh();
    } catch (submitError) {
      setMessages((current) => {
        const next = [...current];
        if (next.length > 0) {
          const last = next[next.length - 1];
          if (String(last.role).toLowerCase() === "assistant" && !String(last.content ?? "").trim()) {
            next.pop();
          }
        }
        return next;
      });
      setError(submitError instanceof Error ? submitError.message : t("chatops.console.submitError"));
    } finally {
      setPending(false);
    }
  }

  function handleResetSession() {
    setSessionId("");
    setMessages([]);
    setAvailableTools(initialTools);
    setReasoning("");
    setError(null);
    router.replace("/chatops");
  }

  return (
    <GlassPanel
      eyebrow={t("chatops.console.eyebrow")}
      title={t("chatops.console.title")}
      description={t("chatops.console.description")}
      actions={
        <button
          type="button"
          onClick={handleResetSession}
          className="rounded-full border border-white/70 bg-white/80 px-3 py-1.5 text-xs font-semibold text-slate-600"
        >
          {t("chatops.console.startNew")}
        </button>
      }
    >
      <div className="space-y-4">
        <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto] md:items-center">
          <div className="soft-inset p-3 text-sm text-slate-600">
            <p className="font-semibold text-slate-900">{t("chatops.console.currentSession")}</p>
            <p className="mt-1 break-all">{sessionId || t("chatops.console.noSession")}</p>
          </div>
          <p className="text-sm text-slate-500">{t("chatops.console.sessionHint")}</p>
        </div>

        <div className="rounded-[20px] border border-white/70 bg-white/70 p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">{t("chatops.console.toolSurface")}</p>
              <p className="mt-2 text-sm text-slate-500">{t("chatops.console.toolSurfaceDescription")}</p>
            </div>
            <span className="rounded-full border border-white/70 bg-white/80 px-3 py-1 text-xs font-semibold text-slate-600">
              {t("chatops.console.toolCount", { count: String(availableTools.length) })}
            </span>
          </div>
          {availableTools.length === 0 ? (
            <p className="mt-3 text-sm text-slate-500">{t("chatops.console.toolEmpty")}</p>
          ) : (
            <div className="mt-3 flex flex-wrap gap-2">
              {availableTools.map((tool) => (
                <span
                  key={tool.name}
                  title={tool.description || tool.name}
                  className="rounded-full border border-white/70 bg-white/80 px-3 py-1 text-xs font-semibold text-slate-700"
                >
                  {tool.name}
                </span>
              ))}
            </div>
          )}
        </div>

        <div className="soft-inset max-h-[360px] space-y-3 overflow-y-auto p-3">
          {messages.length === 0 ? (
            <EmptyState
              title={t("chatops.console.emptyTitle")}
              description={t("chatops.console.emptyDescription")}
            />
          ) : (
            messages.map((message, index) => {
              const isUser = String(message.role).toLowerCase() === "user";
              return (
                <div
                  key={`${message.role}-${index}`}
                  className={cx(
                    "rounded-[20px] border p-3 text-sm leading-6",
                    isUser
                      ? "border-slate-900/10 bg-slate-900 text-white"
                      : "border-white/70 bg-white/80 text-slate-700"
                  )}
                >
                  <p className={cx("text-xs font-semibold uppercase tracking-[0.18em]", isUser ? "text-white/70" : "text-slate-400")}>
                    {isUser ? t("chatops.console.user") : t("chatops.console.assistant")}
                  </p>
                  <p className="mt-2 whitespace-pre-wrap break-words">{message.content}</p>
                </div>
              );
            })
          )}
        </div>

        {reasoning ? (
          <div className="rounded-[20px] border border-white/70 bg-white/70 p-4">
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">{t("chatops.console.reasoning")}</p>
            <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-slate-600">{reasoning}</p>
          </div>
        ) : null}

        <form className="space-y-3" onSubmit={handleSubmit}>
          <div className="soft-inset p-2">
            <textarea
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder={t("chatops.console.placeholder")}
              className="min-h-28 w-full rounded-[16px] border border-white/70 bg-white/80 px-4 py-3 text-sm text-slate-900 outline-none"
              required
            />
          </div>
          <div className="flex flex-wrap items-center justify-between gap-3">
            {error ? <p className="text-sm text-rose-500">{error}</p> : <span className="text-sm text-slate-500">{t("chatops.console.submitHint")}</span>}
            <button
              type="submit"
              disabled={pending}
              className="rounded-xl bg-[#1C1C1E] px-5 py-3 text-sm font-bold text-white shadow-[0_10px_24px_-10px_rgba(0,0,0,0.45)] transition duration-200 ease-embla hover:brightness-110 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {pending ? t("chatops.console.submitting") : t("chatops.console.submit")}
            </button>
          </div>
        </form>
      </div>
    </GlassPanel>
  );
}
