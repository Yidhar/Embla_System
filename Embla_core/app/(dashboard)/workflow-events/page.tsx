import { SignalCard, type SignalState } from "@/components/cards/signal-card";
import { fetchIncidentsLatest, fetchWorkflowEvents } from "@/lib/api/ops";
import {
  formatIsoDateTime,
  formatNumber,
  resolveLangFromSearchParams,
  translateSignalState,
  type AppLang,
} from "@/lib/i18n";

export const dynamic = "force-dynamic";

type WorkflowPageProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

const PAGE_COPY: Record<
  AppLang,
  {
    cards: {
      outboxPending: { title: string; note: string };
      oldestAge: { title: string; note: string };
      leaseLost: { title: string; note: string };
      toolStatus: { title: string; note: string };
      incidentsTotal: { title: string; note: string };
      criticalIncidents: { title: string; note: string };
      warningIncidents: { title: string; note: string };
      latestIncident: { title: string; note: string };
    };
    sections: {
      recentCriticalEvents: string;
      incidentFeed: string;
      eventPostureSummary: string;
      incidentCounters: string;
      eventCounters: string;
      logContextStats: string;
    };
    columns: {
      time: string;
      type: string;
      payload: string;
      severity: string;
      source: string;
      summary: string;
    };
    words: {
      seconds: string;
      visible: string;
      idle: string;
      noToolEvent: string;
      noCriticalEvents: string;
      noIncidents: string;
      unknown: string;
    };
  }
> = {
  en: {
    cards: {
      outboxPending: { title: "Outbox Pending", note: "Pending events in workflow DB" },
      oldestAge: { title: "Oldest Age", note: "Oldest pending event age" },
      leaseLost: { title: "Lease Lost", note: "Lease loss events in scanned window" },
      toolStatus: { title: "Tool Status", note: "Current tool processing state" },
      incidentsTotal: { title: "Incidents Total", note: "Events + evidence gate incidents" },
      criticalIncidents: { title: "Critical Incidents", note: "Critical incident count in current window" },
      warningIncidents: { title: "Warning Incidents", note: "Warning incident count in current window" },
      latestIncident: { title: "Latest Incident", note: "Most recent incident timestamp" },
    },
    sections: {
      recentCriticalEvents: "Recent Critical Events",
      incidentFeed: "Incident Feed",
      eventPostureSummary: "Event Posture Summary",
      incidentCounters: "Incident Counters",
      eventCounters: "Event Counters",
      logContextStats: "Log Context Stats",
    },
    columns: {
      time: "Time",
      type: "Type",
      payload: "Payload",
      severity: "Severity",
      source: "Source",
      summary: "Summary",
    },
    words: {
      seconds: "s",
      visible: "VISIBLE",
      idle: "IDLE",
      noToolEvent: "No active tool event",
      noCriticalEvents: "No critical events in current scan window.",
      noIncidents: "No incidents in current scan window.",
      unknown: "unknown",
    },
  },
  "zh-CN": {
    cards: {
      outboxPending: { title: "Outbox 待处理", note: "工作流数据库中的待处理事件" },
      oldestAge: { title: "最老事件时长", note: "最老待处理事件年龄" },
      leaseLost: { title: "租约丢失", note: "扫描窗口内租约丢失次数" },
      toolStatus: { title: "工具状态", note: "当前工具处理状态" },
      incidentsTotal: { title: "事件总数", note: "运行事件 + 证据门禁异常" },
      criticalIncidents: { title: "严重事件", note: "当前窗口内严重事件数量" },
      warningIncidents: { title: "告警事件", note: "当前窗口内告警事件数量" },
      latestIncident: { title: "最新事件", note: "最近一次事件时间" },
    },
    sections: {
      recentCriticalEvents: "最近关键事件",
      incidentFeed: "事件流",
      eventPostureSummary: "事件态势摘要",
      incidentCounters: "事件计数器",
      eventCounters: "事件分类计数",
      logContextStats: "日志上下文统计",
    },
    columns: {
      time: "时间",
      type: "类型",
      payload: "载荷",
      severity: "级别",
      source: "来源",
      summary: "摘要",
    },
    words: {
      seconds: "秒",
      visible: "可见",
      idle: "空闲",
      noToolEvent: "当前无活动工具事件",
      noCriticalEvents: "当前扫描窗口内无关键事件。",
      noIncidents: "当前扫描窗口内无事件。",
      unknown: "未知",
    },
  },
};

function toState(status: string): SignalState {
  const normalized = String(status || "unknown").toLowerCase();
  if (normalized === "ok" || normalized === "healthy") {
    return "healthy";
  }
  if (normalized === "warning") {
    return "warning";
  }
  if (normalized === "critical") {
    return "critical";
  }
  return "unknown";
}

function toNumber(value: unknown, lang: AppLang, suffix = ""): string {
  const formatted = formatNumber(value, lang, { maximumFractionDigits: 2, fallback: "--" });
  if (formatted === "--") {
    return formatted;
  }
  return `${formatted}${suffix}`;
}

export default async function WorkflowEventsPage({ searchParams }: WorkflowPageProps) {
  const lang = await resolveLangFromSearchParams(searchParams);
  const copy = PAGE_COPY[lang];
  const [payload, incidentsPayload] = await Promise.all([fetchWorkflowEvents(), fetchIncidentsLatest()]);
  const summary = payload?.data?.summary;
  const toolStatus = payload?.data?.tool_status || {};
  const eventCounters = payload?.data?.event_counters || {};
  const recentEvents = payload?.data?.recent_critical_events || [];
  const logStats = payload?.data?.log_context_statistics || {};

  const incidentsSummary = incidentsPayload?.data?.summary;
  const incidents = incidentsPayload?.data?.incidents || [];

  const outboxPending = summary?.outbox_pending;
  const oldestPendingAge = summary?.oldest_pending_age_seconds;
  const leaseLost = Number(eventCounters.LeaseLost || 0);
  const state = toState(payload?.severity || "unknown");
  const incidentsState = toState(incidentsPayload?.severity || "unknown");
  const latestIncidentText = formatIsoDateTime(incidentsSummary?.latest_incident_at, lang, "--");

  return (
    <div className="space-y-6">
      <section className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
        <SignalCard
          title={copy.cards.outboxPending.title}
          value={toNumber(outboxPending, lang)}
          note={copy.cards.outboxPending.note}
          state={state}
          stateLabel={translateSignalState(state, lang)}
        />
        <SignalCard
          title={copy.cards.oldestAge.title}
          value={toNumber(oldestPendingAge, lang, copy.words.seconds)}
          note={copy.cards.oldestAge.note}
          state={state}
          stateLabel={translateSignalState(state, lang)}
        />
        <SignalCard
          title={copy.cards.leaseLost.title}
          value={formatNumber(leaseLost, lang, { maximumFractionDigits: 0 })}
          note={copy.cards.leaseLost.note}
          state={leaseLost > 0 ? "warning" : state}
          stateLabel={translateSignalState(leaseLost > 0 ? "warning" : state, lang)}
        />
        <SignalCard
          title={copy.cards.toolStatus.title}
          value={toolStatus.visible ? copy.words.visible : copy.words.idle}
          note={String(toolStatus.message || copy.words.noToolEvent)}
          state={toolStatus.visible ? "warning" : state}
          stateLabel={translateSignalState(toolStatus.visible ? "warning" : state, lang)}
        />
      </section>

      <section className="grid grid-cols-1 gap-4 xl:grid-cols-4">
        <SignalCard
          title={copy.cards.incidentsTotal.title}
          value={formatNumber(incidentsSummary?.total_incidents || 0, lang, { maximumFractionDigits: 0 })}
          note={copy.cards.incidentsTotal.note}
          state={incidentsState}
          stateLabel={translateSignalState(incidentsState, lang)}
        />
        <SignalCard
          title={copy.cards.criticalIncidents.title}
          value={formatNumber(incidentsSummary?.critical_incidents || 0, lang, { maximumFractionDigits: 0 })}
          note={copy.cards.criticalIncidents.note}
          state={Number(incidentsSummary?.critical_incidents || 0) > 0 ? "critical" : incidentsState}
          stateLabel={translateSignalState(Number(incidentsSummary?.critical_incidents || 0) > 0 ? "critical" : incidentsState, lang)}
        />
        <SignalCard
          title={copy.cards.warningIncidents.title}
          value={formatNumber(incidentsSummary?.warning_incidents || 0, lang, { maximumFractionDigits: 0 })}
          note={copy.cards.warningIncidents.note}
          state={Number(incidentsSummary?.warning_incidents || 0) > 0 ? "warning" : incidentsState}
          stateLabel={translateSignalState(Number(incidentsSummary?.warning_incidents || 0) > 0 ? "warning" : incidentsState, lang)}
        />
        <SignalCard
          title={copy.cards.latestIncident.title}
          value={latestIncidentText}
          note={copy.cards.latestIncident.note}
          state={incidentsState}
          stateLabel={translateSignalState(incidentsState, lang)}
        />
      </section>

      <section className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <article className="glass-card p-6">
          <p className="text-[10px] font-bold uppercase tracking-[0.25em] text-gray-500">{copy.sections.recentCriticalEvents}</p>
          <div className="mt-4 overflow-auto rounded-2xl bg-white/70 p-3">
            <table className="min-w-full text-left text-xs text-gray-700">
              <thead>
                <tr className="border-b border-gray-200/80">
                  <th className="px-2 py-2 uppercase tracking-[0.2em]">{copy.columns.time}</th>
                  <th className="px-2 py-2 uppercase tracking-[0.2em]">{copy.columns.type}</th>
                  <th className="px-2 py-2 uppercase tracking-[0.2em]">{copy.columns.payload}</th>
                </tr>
              </thead>
              <tbody>
                {recentEvents.slice(0, 25).map((item, idx) => (
                  <tr key={`${item.timestamp}-${item.event_type}-${idx}`} className="border-b border-gray-100/70 align-top">
                    <td className="px-2 py-2 font-mono">{formatIsoDateTime(item.timestamp, lang, "--")}</td>
                    <td className="px-2 py-2">{item.event_type || "-"}</td>
                    <td className="px-2 py-2">
                      <pre className="whitespace-pre-wrap text-[10px]">
                        {JSON.stringify(item.payload_excerpt || {}, null, 2)}
                      </pre>
                    </td>
                  </tr>
                ))}
                {(!payload || recentEvents.length === 0) && (
                  <tr>
                    <td colSpan={3} className="px-2 py-3 text-gray-500">
                      {copy.words.noCriticalEvents}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </article>

        <article className="glass-card p-6">
          <p className="text-[10px] font-bold uppercase tracking-[0.25em] text-gray-500">{copy.sections.incidentFeed}</p>
          <div className="mt-4 overflow-auto rounded-2xl bg-white/70 p-3">
            <table className="min-w-full text-left text-xs text-gray-700">
              <thead>
                <tr className="border-b border-gray-200/80">
                  <th className="px-2 py-2 uppercase tracking-[0.2em]">{copy.columns.severity}</th>
                  <th className="px-2 py-2 uppercase tracking-[0.2em]">{copy.columns.source}</th>
                  <th className="px-2 py-2 uppercase tracking-[0.2em]">{copy.columns.summary}</th>
                </tr>
              </thead>
              <tbody>
                {incidents.slice(0, 25).map((item, idx) => (
                  <tr key={`${item.timestamp}-${item.summary}-${idx}`} className="border-b border-gray-100/70 align-top">
                    <td className="px-2 py-2 uppercase">{String(item.severity || copy.words.unknown)}</td>
                    <td className="px-2 py-2">{String(item.source || "-")}</td>
                    <td className="px-2 py-2">
                      <p>{String(item.summary || "-")}</p>
                      <p className="mt-1 font-mono text-[10px] text-gray-500">{formatIsoDateTime(item.timestamp, lang, "--")}</p>
                    </td>
                  </tr>
                ))}
                {(!incidentsPayload || incidents.length === 0) && (
                  <tr>
                    <td colSpan={3} className="px-2 py-3 text-gray-500">
                      {copy.words.noIncidents}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </article>
      </section>

      <section className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <article className="glass-card p-6">
          <p className="text-[10px] font-bold uppercase tracking-[0.25em] text-gray-500">{copy.sections.eventPostureSummary}</p>
          <div className="mt-4 space-y-3 text-xs text-gray-700">
            <div className="rounded-xl bg-white/70 p-3">
              <p className="font-bold uppercase tracking-[0.2em] text-gray-500">{copy.sections.eventCounters}</p>
              <pre className="mt-2 whitespace-pre-wrap">{JSON.stringify(eventCounters, null, 2)}</pre>
            </div>
            <div className="rounded-xl bg-white/70 p-3">
              <p className="font-bold uppercase tracking-[0.2em] text-gray-500">{copy.sections.logContextStats}</p>
              <pre className="mt-2 whitespace-pre-wrap">{JSON.stringify(logStats, null, 2)}</pre>
            </div>
          </div>
        </article>

        <article className="glass-card p-6">
          <p className="text-[10px] font-bold uppercase tracking-[0.25em] text-gray-500">{copy.sections.incidentCounters}</p>
          <div className="mt-4 rounded-xl bg-white/70 p-3 text-xs text-gray-700">
            <pre className="whitespace-pre-wrap">
              {JSON.stringify(
                {
                  severity: incidentsPayload?.severity || copy.words.unknown,
                  reason_code: incidentsPayload?.reason_code || "",
                  reason_text: incidentsPayload?.reason_text || "",
                  event_counters: incidentsPayload?.data?.event_counters || {},
                  events_scanned: incidentsPayload?.data?.events_scanned || 0,
                },
                null,
                2,
              )}
            </pre>
          </div>
        </article>
      </section>
    </div>
  );
}
