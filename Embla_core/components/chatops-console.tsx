"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { EmptyState, GlassPanel } from "@/components/dashboard-ui";
import { cx } from "@/lib/format";
import { AppLocale, createTranslator } from "@/lib/i18n";
import { buildBrowserApiUrl, extractApiErrorMessage } from "@/lib/client-api";
import { ChatSessionMessage } from "@/lib/types";

type ChatOpsConsoleProps = {
  locale: AppLocale;
  selectedSessionId?: string;
  initialMessages?: ChatSessionMessage[];
};

export function ChatOpsConsole({ locale, selectedSessionId = "", initialMessages = [] }: ChatOpsConsoleProps) {
  const t = createTranslator(locale);
  const router = useRouter();
  const [sessionId, setSessionId] = useState(selectedSessionId);
  const [messages, setMessages] = useState<ChatSessionMessage[]>(initialMessages);
  const [draft, setDraft] = useState("");
  const [reasoning, setReasoning] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setSessionId(selectedSessionId);
    setMessages(initialMessages);
    setReasoning("");
    setError(null);
  }, [initialMessages, selectedSessionId]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const nextDraft = draft.trim();
    if (!nextDraft || pending) {
      return;
    }

    setPending(true);
    setError(null);

    try {
      const response = await fetch(buildBrowserApiUrl("/v1/chat"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: nextDraft,
          session_id: sessionId || undefined,
          stream: false
        })
      });
      const payload = (await response.json()) as {
        detail?: string;
        response?: string;
        reasoning_content?: string | null;
        session_id?: string | null;
      };
      if (!response.ok) {
        throw new Error(extractApiErrorMessage(payload, t("chatops.console.submitError")));
      }

      const effectiveSessionId = String(payload.session_id ?? sessionId ?? "").trim();
      setMessages((current) => [
        ...current,
        { role: "user", content: nextDraft },
        { role: "assistant", content: String(payload.response ?? "") }
      ]);
      setReasoning(String(payload.reasoning_content ?? ""));
      setDraft("");
      setSessionId(effectiveSessionId);
      if (effectiveSessionId) {
        router.replace(`/chatops?session_id=${encodeURIComponent(effectiveSessionId)}`);
      }
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : t("chatops.console.submitError"));
    } finally {
      setPending(false);
    }
  }

  function handleResetSession() {
    setSessionId("");
    setMessages([]);
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
