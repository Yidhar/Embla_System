import Link from "next/link";

import { ChatOpsWorkspace } from "@/components/chatops-workspace";
import { EmptyState, GlassPanel, MetricCard, MetricGrid, PageHeader } from "@/components/dashboard-ui";
import { getChatRouteSessionState, getChatSessionDetail, getChatSessions, getShellToolCatalog } from "@/lib/api/ops";
import { cx, formatNumber, formatTimestamp } from "@/lib/format";
import { createTranslator, humanizeEnum } from "@/lib/i18n";
import { getRequestLocale } from "@/lib/request-locale";
import { numberValue } from "@/lib/view-models";

type ChatOpsPageProps = {
  searchParams?: Promise<{ session_id?: string | string[] | undefined }>;
};

function resolveSessionId(rawValue: string | string[] | undefined) {
  if (Array.isArray(rawValue)) {
    return String(rawValue[0] ?? "").trim();
  }
  return String(rawValue ?? "").trim();
}

export default async function ChatOpsPage({ searchParams }: ChatOpsPageProps) {
  const locale = await getRequestLocale();
  const t = createTranslator(locale);
  const resolvedSearchParams = searchParams ? await searchParams : {};
  const requestedSessionId = resolveSessionId(resolvedSearchParams?.session_id);
  const sessions = await getChatSessions();
  const sessionId = requestedSessionId || sessions[0]?.session_id || "";

  const [routeState, sessionDetail, shellToolCatalog] = await Promise.all([
    sessionId ? getChatRouteSessionState(sessionId) : Promise.resolve(null),
    sessionId ? getChatSessionDetail(sessionId) : Promise.resolve(null),
    getShellToolCatalog()
  ]);
  const heartbeatSummary = routeState?.child_heartbeat_summary ?? {};
  const descendantSessionCount = numberValue(heartbeatSummary.session_count);
  const sessionsWithHeartbeats = numberValue(heartbeatSummary.sessions_with_heartbeats);
  const activeHeartbeatTaskCount = numberValue(heartbeatSummary.task_count);

  const severity = numberValue(heartbeatSummary.blocked_count) > 0
    ? "critical"
    : numberValue(heartbeatSummary.critical_count) > 0
      ? "critical"
      : numberValue(heartbeatSummary.warning_count) > 0
        ? "warning"
        : routeState
          ? "ok"
          : sessions.length > 0
            ? "warning"
            : "unknown";

  const selectedRounds = numberValue(sessionDetail?.conversation_rounds ?? sessionDetail?.session_info?.conversation_rounds);
  const initialMessages = sessionDetail?.messages?.slice(-12) ?? [];

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={t("chatops.header.eyebrow")}
        title={t("chatops.header.title")}
        description={t("chatops.header.description")}
        severity={severity}
        locale={locale}
      />

      <MetricGrid>
        <MetricCard
          title={t("chatops.metrics.totalSessions.title")}
          value={formatNumber(sessions.length, 0, locale)}
          description={t("chatops.metrics.totalSessions.description")}
          severity={sessions.length > 0 ? "ok" : "unknown"}
          locale={locale}
        />
        <MetricCard
          title={t("chatops.metrics.selectedRounds.title")}
          value={formatNumber(selectedRounds, 0, locale)}
          description={t("chatops.metrics.selectedRounds.description")}
          severity={sessionId ? "ok" : "unknown"}
          locale={locale}
        />
        <MetricCard
          title={t("chatops.metrics.childSessions.title")}
          value={formatNumber(descendantSessionCount, 0, locale)}
          description={t("chatops.metrics.childSessions.description", {
            withHeartbeats: formatNumber(sessionsWithHeartbeats, 0, locale),
            taskCount: formatNumber(activeHeartbeatTaskCount, 0, locale)
          })}
          severity={severity}
          locale={locale}
        />
        <MetricCard
          title={t("chatops.metrics.routeSemantic.title")}
          value={humanizeEnum(locale, "routeSemantic", routeState?.state?.last_route_semantic ?? "unknown")}
          description={t("chatops.metrics.routeSemantic.description")}
          severity={routeState ? "ok" : "unknown"}
          locale={locale}
        />
      </MetricGrid>

      <div className="grid gap-6 xl:grid-cols-[0.95fr_1.05fr]">
        <GlassPanel
          eyebrow={t("chatops.sessionDirectory.eyebrow")}
          title={t("chatops.sessionDirectory.title")}
          description={t("chatops.sessionDirectory.description")}
        >
          {sessions.length === 0 ? (
            <EmptyState
              title={t("chatops.sessionDirectory.emptyTitle")}
              description={t("chatops.sessionDirectory.emptyDescription")}
            />
          ) : (
            <div className="space-y-3">
              {sessions.map((session) => {
                const active = session.session_id === sessionId;
                return (
                  <Link
                    key={session.session_id}
                    href={`/chatops?session_id=${encodeURIComponent(session.session_id)}`}
                    className={cx(
                      "block rounded-[24px] border p-4 transition",
                      active
                        ? "border-slate-900/15 bg-slate-900 text-white shadow-[0_18px_42px_-28px_rgba(15,23,42,0.75)]"
                        : "border-white/70 bg-white/75 hover:bg-white/90"
                    )}
                  >
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <p className="text-sm font-semibold break-all">{session.session_id}</p>
                      <div className="flex items-center gap-2 text-xs">
                        {session.temporary ? (
                          <span className={cx("rounded-full border px-3 py-1", active ? "border-white/20 bg-white/10 text-white/80" : "border-white/70 bg-white text-slate-500")}>
                            {t("chatops.sessionDirectory.temporary")}
                          </span>
                        ) : null}
                        <span className={cx(active ? "text-white/70" : "text-slate-400")}>{formatTimestamp(session.last_active_at, locale)}</span>
                      </div>
                    </div>
                    <div className={cx("mt-3 flex flex-wrap gap-4 text-xs", active ? "text-white/70" : "text-slate-400")}>
                      <span>{t("chatops.sessionDirectory.rounds", { rounds: String(numberValue(session.conversation_rounds)) })}</span>
                      <span>{t("chatops.sessionDirectory.messages", { messages: String(numberValue(session.message_count)) })}</span>
                      <span>{session.agent_type || t("common.label.unknown")}</span>
                    </div>
                    <p className={cx("mt-3 text-sm leading-6", active ? "text-white/85" : "text-slate-500")}>
                      {session.last_message || t("chatops.sessionDirectory.noMessage")}
                    </p>
                  </Link>
                );
              })}
            </div>
          )}
        </GlassPanel>

        <ChatOpsWorkspace
          locale={locale}
          selectedSessionId={sessionId}
          initialMessages={initialMessages}
          initialTools={shellToolCatalog.tools}
          initialRouteState={routeState}
        />
      </div>
    </div>
  );
}
