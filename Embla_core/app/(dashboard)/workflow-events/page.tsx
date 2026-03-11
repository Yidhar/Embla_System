import { Activity, AlarmClockCheck, Boxes, Clock3, Speech } from "lucide-react";

import { GlassPanel, MetricCard, MetricGrid, PageHeader, SourceList, TimelineList } from "@/components/dashboard-ui";
import { getRuntimePosture, getWorkflowEvents } from "@/lib/api/ops";
import { formatDurationSeconds, formatNumber } from "@/lib/format";
import { createTranslator, humanizeEnum } from "@/lib/i18n";
import { getRequestLocale } from "@/lib/request-locale";
import { numberValue } from "@/lib/view-models";

export default async function WorkflowEventsPage() {
  const locale = await getRequestLocale();
  const t = createTranslator(locale);
  const [workflow, runtime] = await Promise.all([getWorkflowEvents(), getRuntimePosture()]);
  const counters = workflow.data.event_counters ?? {};
  const heartbeatSummary = workflow.data.heartbeat_supervision?.summary ?? {};
  const heartbeatTasks = workflow.data.heartbeat_supervision?.heartbeats ?? [];

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={t("workflowEvents.header.eyebrow")}
        title={t("workflowEvents.header.title")}
        description={t("workflowEvents.header.description")}
        severity={workflow.severity}
        mode={workflow.meta?.mode}
        locale={locale}
      />

      <MetricGrid>
        <MetricCard
          title={t("workflowEvents.metrics.outboxPending.title")}
          value={formatNumber(numberValue(workflow.data.summary.outbox_pending), 0, locale)}
          description={t("workflowEvents.metrics.outboxPending.description")}
          severity={workflow.data.queue_depth?.status ?? workflow.severity}
          locale={locale}
        />
        <MetricCard
          title={t("workflowEvents.metrics.oldestPending.title")}
          value={formatDurationSeconds(numberValue(workflow.data.summary.oldest_pending_age_seconds))}
          description={t("workflowEvents.metrics.oldestPending.description")}
          severity={workflow.data.queue_depth?.status ?? workflow.severity}
          locale={locale}
        />
        <MetricCard
          title={t("workflowEvents.metrics.leaseState.title")}
          value={humanizeEnum(locale, "leaseState", workflow.data.runtime_lease?.state ?? runtime.data.metrics.runtime_lease?.state ?? "unknown")}
          description={t("workflowEvents.metrics.leaseState.description")}
          severity={workflow.data.runtime_lease?.status ?? runtime.data.metrics.runtime_lease?.status ?? runtime.severity}
          locale={locale}
        />
        <MetricCard
          title={t("workflowEvents.metrics.lockState.title")}
          value={humanizeEnum(locale, "lockState", workflow.data.lock_status?.state ?? "unknown")}
          description={t("workflowEvents.metrics.lockState.description")}
          severity={workflow.data.lock_status?.status ?? workflow.severity}
          locale={locale}
        />
      </MetricGrid>

      <div className="grid gap-6 xl:grid-cols-[1fr_1fr]">
        <GlassPanel
          eyebrow={t("workflowEvents.criticalLane.eyebrow")}
          title={t("workflowEvents.criticalLane.title")}
          description={t("workflowEvents.criticalLane.description")}
        >
          <TimelineList
            items={workflow.data.recent_critical_events.map((item) => ({
              title: item.event_type,
              detail: item.payload_excerpt,
              timestamp: item.timestamp,
              severity: item.event_type === "LeaseLost" ? "critical" : "warning"
            }))}
            locale={locale}
          />
          <SourceList reports={workflow.source_reports} endpoints={workflow.source_endpoints} />
        </GlassPanel>

        <GlassPanel
          eyebrow={t("workflowEvents.contextPulse.eyebrow")}
          title={t("workflowEvents.contextPulse.title")}
          description={t("workflowEvents.contextPulse.description")}
        >
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="soft-inset p-4">
              <div className="flex items-center gap-2 text-slate-500"><Speech className="h-4 w-4" /><span className="text-sm">{t("workflowEvents.contextPulse.messageContext")}</span></div>
              <p className="mt-3 text-2xl font-extrabold text-slate-900">{formatNumber(numberValue(workflow.data.log_context_statistics?.total_messages), 0, locale)}</p>
              <p className="mt-2 text-sm text-slate-500">{t("workflowEvents.contextPulse.messageContextDescription")}</p>
            </div>
            <div className="soft-inset p-4">
              <div className="flex items-center gap-2 text-slate-500"><Boxes className="h-4 w-4" /><span className="text-sm">{t("workflowEvents.contextPulse.eventDbRows")}</span></div>
              <p className="mt-3 text-2xl font-extrabold text-slate-900">{formatNumber(numberValue(workflow.data.summary.event_db_rows), 0, locale)}</p>
              <p className="mt-2 text-sm text-slate-500">{t("workflowEvents.contextPulse.eventDbRowsDescription")}</p>
            </div>
            <div className="soft-inset p-4 sm:col-span-2">
              <div className="flex items-center gap-2 text-slate-500"><AlarmClockCheck className="h-4 w-4" /><span className="text-sm">{t("workflowEvents.contextPulse.currentToolStatus")}</span></div>
              <p className="mt-3 text-base font-semibold text-slate-900">{workflow.data.tool_status?.visible ? workflow.data.tool_status.message : t("workflowEvents.contextPulse.noToolStatus")}</p>
            </div>
            <div className="soft-inset p-4 sm:col-span-2">
              <div className="flex items-center gap-2 text-slate-500"><Activity className="h-4 w-4" /><span className="text-sm">{t("workflowEvents.contextPulse.agentHeartbeats")}</span></div>
              {Number(heartbeatSummary.task_count ?? 0) > 0 ? (
                <>
                  <div className="mt-4 grid gap-3 sm:grid-cols-4">
                    <div className="rounded-[18px] border border-white/70 bg-white/80 p-3">
                      <p className="text-xs uppercase tracking-[0.24em] text-slate-400">{t("workflowEvents.contextPulse.active")}</p>
                      <p className="mt-2 text-xl font-bold text-slate-900">{formatNumber(numberValue(heartbeatSummary.task_count), 0, locale)}</p>
                    </div>
                    <div className="rounded-[18px] border border-white/70 bg-white/80 p-3">
                      <p className="text-xs uppercase tracking-[0.24em] text-slate-400">{t("workflowEvents.contextPulse.warning")}</p>
                      <p className="mt-2 text-xl font-bold text-amber-600">{formatNumber(numberValue(heartbeatSummary.warning_count), 0, locale)}</p>
                    </div>
                    <div className="rounded-[18px] border border-white/70 bg-white/80 p-3">
                      <p className="text-xs uppercase tracking-[0.24em] text-slate-400">{t("workflowEvents.contextPulse.critical")}</p>
                      <p className="mt-2 text-xl font-bold text-rose-600">{formatNumber(numberValue(heartbeatSummary.critical_count), 0, locale)}</p>
                    </div>
                    <div className="rounded-[18px] border border-white/70 bg-white/80 p-3">
                      <p className="text-xs uppercase tracking-[0.24em] text-slate-400">{t("workflowEvents.contextPulse.blocked")}</p>
                      <p className="mt-2 text-xl font-bold text-rose-700">{formatNumber(numberValue(heartbeatSummary.blocked_count), 0, locale)}</p>
                    </div>
                  </div>
                  <p className="mt-3 text-sm text-slate-500">
                    {t("workflowEvents.contextPulse.heartbeatSummary", {
                      withHeartbeats: formatNumber(numberValue(heartbeatSummary.sessions_with_heartbeats), 0, locale),
                      sessions: formatNumber(numberValue(heartbeatSummary.session_count), 0, locale),
                      level: humanizeEnum(locale, "staleLevel", heartbeatSummary.max_stale_level ?? "none")
                    })}
                  </p>
                  <div className="mt-4 grid gap-3 lg:grid-cols-2">
                    {heartbeatTasks.slice(0, 4).map((item) => (
                      <div key={`${item.session_id}-${item.task_id}`} className="rounded-[18px] border border-white/70 bg-white/80 p-3">
                        <div className="flex items-center justify-between gap-3">
                          <p className="text-sm font-semibold text-slate-900">{item.task_id}</p>
                          <span className="text-xs uppercase tracking-[0.18em] text-slate-400">{humanizeEnum(locale, "staleLevel", item.stale_level ?? "fresh")}</span>
                        </div>
                        <p className="mt-2 text-sm text-slate-500">{item.session_id} · {item.stage || item.status || t("common.label.running")}</p>
                        <p className="mt-2 text-sm text-slate-600">{item.message || t("workflowEvents.contextPulse.noHeartbeatMessage")}</p>
                      </div>
                    ))}
                  </div>
                </>
              ) : (
                <p className="mt-3 text-sm text-slate-500">{t("workflowEvents.contextPulse.noHeartbeats")}</p>
              )}
            </div>
            <div className="soft-inset p-4 sm:col-span-2">
              <div className="flex items-center gap-2 text-slate-500"><Clock3 className="h-4 w-4" /><span className="text-sm">{t("workflowEvents.contextPulse.keyCounters")}</span></div>
              <div className="mt-4 grid gap-3 sm:grid-cols-3">
                {Object.entries(counters).map(([name, value]) => (
                  <div key={name} className="rounded-[18px] border border-white/70 bg-white/80 p-3">
                    <p className="text-xs uppercase tracking-[0.24em] text-slate-400">{name}</p>
                    <p className="mt-2 text-xl font-bold text-slate-900">{formatNumber(value, 0, locale)}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </GlassPanel>
      </div>
    </div>
  );
}
