import { SignalCard, type SignalState } from "@/components/cards/signal-card";
import { MetricBar, type MetricBarTone } from "@/components/charts/metric-bar";
import { fetchIncidentsLatest, fetchRuntimePosture, fetchWorkflowEvents } from "@/lib/api/ops";
import {
  formatIsoDateTime,
  formatNumber,
  formatPercentRatio,
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
      eventDbRows: { title: string; note: string };
      eventDbPartitions: { title: string; note: string };
      eventDbSize: { title: string; note: string };
      eventDbLatest: { title: string; note: string };
    };
    sections: {
      recentCriticalEvents: string;
      incidentFeed: string;
      eventDatabase: string;
      eventDatabasePartitions: string;
      eventDatabaseTopics: string;
      eventPostureSummary: string;
      runtimeCrossSignals: string;
      incidentCounters: string;
      incidentPromptSafety: string;
      eventCounters: string;
      logContextStats: string;
    };
    metricLabels: {
      readonlyWriteExposure: string;
      outerReadonlyHitRate: string;
      pathCRouteShare: string;
      shellToCoreDispatch: string;
      pathBBudgetEscalation: string;
      coreSessionCreation: string;
      routeQuality: string;
    };
    columns: {
      time: string;
      type: string;
      partition: string;
      topic: string;
      rows: string;
      latest: string;
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
      dataSourceOffline: string;
      noCriticalEvents: string;
      noIncidents: string;
      unknown: string;
      sampleCount: string;
      exposureCount: string;
      hitCount: string;
      dispatchToCoreRate: string;
      escalatedCount: string;
      createdCount: string;
      shellReadonlyRatio: string;
      shellClarifyRatio: string;
      coreExecutionRatio: string;
      routeQualityReason: string;
      trend: string;
      volatility: string;
      noRows: string;
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
      eventDbRows: { title: "Event DB Rows", note: "Total rows in topic_event table" },
      eventDbPartitions: { title: "DB Partitions", note: "Distinct partition_ym count" },
      eventDbSize: { title: "DB Size", note: "Current events DB file size" },
      eventDbLatest: { title: "Latest DB Event", note: "Most recent event timestamp in DB" },
    },
    sections: {
      recentCriticalEvents: "Recent Critical Events",
      incidentFeed: "Incident Feed",
      eventDatabase: "Event Database",
      eventDatabasePartitions: "Partition Distribution",
      eventDatabaseTopics: "Top Topics",
      eventPostureSummary: "Event Posture Summary",
      runtimeCrossSignals: "Runtime Cross-Page Signals",
      incidentCounters: "Incident Counters",
      incidentPromptSafety: "Incident Prompt Safety Snapshot",
      eventCounters: "Event Counters",
      logContextStats: "Log Context Stats",
    },
    metricLabels: {
      readonlyWriteExposure: "Readonly Write Exposure",
      outerReadonlyHitRate: "Shell Readonly Hit Rate",
      pathCRouteShare: "Core Execution Route Share",
      shellToCoreDispatch: "Shell to Core Dispatch",
      pathBBudgetEscalation: "Shell Clarify Budget Escalation",
      coreSessionCreation: "Core Execution Session Creation",
      routeQuality: "Route Quality",
    },
    columns: {
      time: "Time",
      type: "Type",
      partition: "Partition",
      topic: "Topic",
      rows: "Rows",
      latest: "Latest",
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
      dataSourceOffline: "Dashboard data source is unavailable. Check backend startup and API base configuration.",
      noCriticalEvents: "No critical events in current scan window.",
      noIncidents: "No incidents in current scan window.",
      unknown: "unknown",
      sampleCount: "Sample count",
      exposureCount: "Exposure count",
      hitCount: "Hit count",
      dispatchToCoreRate: "Dispatch to core",
      escalatedCount: "Escalated count",
      createdCount: "Created count",
      shellReadonlyRatio: "Shell Readonly",
      shellClarifyRatio: "Shell Clarify",
      coreExecutionRatio: "Core Execution",
      routeQualityReason: "Reason",
      trend: "Trend",
      volatility: "Volatility",
      noRows: "No rows.",
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
      eventDbRows: { title: "事件库行数", note: "topic_event 表总行数" },
      eventDbPartitions: { title: "分区数量", note: "partition_ym 去重数量" },
      eventDbSize: { title: "事件库大小", note: "当前 events DB 文件体积" },
      eventDbLatest: { title: "最新 DB 事件", note: "数据库中最近事件时间" },
    },
    sections: {
      recentCriticalEvents: "最近关键事件",
      incidentFeed: "事件流",
      eventDatabase: "事件数据库",
      eventDatabasePartitions: "分区分布",
      eventDatabaseTopics: "主题热点",
      eventPostureSummary: "事件态势摘要",
      runtimeCrossSignals: "运行态跨页信号",
      incidentCounters: "事件计数器",
      incidentPromptSafety: "事件 Prompt 安全快照",
      eventCounters: "事件分类计数",
      logContextStats: "日志上下文统计",
    },
    metricLabels: {
      readonlyWriteExposure: "只读写工具暴露率",
      outerReadonlyHitRate: "Shell 只读命中率",
      pathCRouteShare: "Core 执行路由占比",
      shellToCoreDispatch: "Shell 到 Core 转交率",
      pathBBudgetEscalation: "Shell 澄清预算升级率",
      coreSessionCreation: "Core 执行会话新建率",
      routeQuality: "路由质量",
    },
    columns: {
      time: "时间",
      type: "类型",
      partition: "分区",
      topic: "主题",
      rows: "行数",
      latest: "最近时间",
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
      dataSourceOffline: "仪表盘数据源不可用，请检查后端是否启动以及 API 地址配置。",
      noCriticalEvents: "当前扫描窗口内无关键事件。",
      noIncidents: "当前扫描窗口内无事件。",
      unknown: "未知",
      sampleCount: "样本数",
      exposureCount: "暴露次数",
      hitCount: "命中次数",
      dispatchToCoreRate: "转交 Core 比例",
      escalatedCount: "升级次数",
      createdCount: "新建次数",
      shellReadonlyRatio: "Shell 只读",
      shellClarifyRatio: "Shell 澄清",
      coreExecutionRatio: "Core 执行",
      routeQualityReason: "原因",
      trend: "趋势",
      volatility: "波动率",
      noRows: "暂无数据。",
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

function asRecord(value: unknown): Record<string, unknown> {
  if (typeof value === "object" && value !== null) {
    return value as Record<string, unknown>;
  }
  return {};
}

function toRatio(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  return null;
}

function toPercent(value: unknown, lang: AppLang): string {
  return formatPercentRatio(value, lang, 1, "--");
}

function toFiniteNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) {
      return parsed;
    }
  }
  return null;
}

function toStorageSize(value: unknown, lang: AppLang): string {
  const bytes = toFiniteNumber(value);
  if (bytes === null || bytes < 0) {
    return "--";
  }
  if (bytes >= 1024 ** 3) {
    const gb = bytes / 1024 ** 3;
    return `${formatNumber(gb, lang, { maximumFractionDigits: 2, fallback: "--" })} GB`;
  }
  if (bytes >= 1024 ** 2) {
    const mb = bytes / 1024 ** 2;
    return `${formatNumber(mb, lang, { maximumFractionDigits: 2, fallback: "--" })} MB`;
  }
  if (bytes >= 1024) {
    const kb = bytes / 1024;
    return `${formatNumber(kb, lang, { maximumFractionDigits: 2, fallback: "--" })} KB`;
  }
  return `${formatNumber(bytes, lang, { maximumFractionDigits: 0, fallback: "--" })} B`;
}

function toTone(state: SignalState): MetricBarTone {
  if (state === "healthy") {
    return "healthy";
  }
  if (state === "warning") {
    return "warning";
  }
  if (state === "critical") {
    return "critical";
  }
  return "unknown";
}

function stateToRatio(state: SignalState): number {
  if (state === "healthy") {
    return 1;
  }
  if (state === "warning") {
    return 0.6;
  }
  if (state === "critical") {
    return 0.25;
  }
  return 0;
}

export default async function WorkflowEventsPage({ searchParams }: WorkflowPageProps) {
  const lang = await resolveLangFromSearchParams(searchParams);
  const copy = PAGE_COPY[lang];
  const [payload, incidentsPayload, runtimePayload] = await Promise.all([
    fetchWorkflowEvents(),
    fetchIncidentsLatest(),
    fetchRuntimePosture(),
  ]);
  const dataSourceConnected = Boolean(payload && incidentsPayload && runtimePayload);
  const summary = payload?.data?.summary;
  const toolStatus = payload?.data?.tool_status || {};
  const eventCounters = payload?.data?.event_counters || {};
  const recentEvents = payload?.data?.recent_critical_events || [];
  const eventDatabase = payload?.data?.event_database;
  const eventDbPartitions = Array.isArray(eventDatabase?.partitions) ? eventDatabase.partitions : [];
  const eventDbTopics = Array.isArray(eventDatabase?.top_topics) ? eventDatabase.top_topics : [];
  const logStats = payload?.data?.log_context_statistics || {};

  const incidentsSummary = incidentsPayload?.data?.summary;
  const incidents = incidentsPayload?.data?.incidents || [];
  const runtimeMetrics = runtimePayload?.data?.metrics || {};
  const runtimeSummary = asRecord(runtimePayload?.data?.summary);
  const readonlyExposureMetric =
    typeof runtimeMetrics.readonly_write_tool_exposure_rate === "object" && runtimeMetrics.readonly_write_tool_exposure_rate
      ? runtimeMetrics.readonly_write_tool_exposure_rate
      : {};
  const shellReadonlyMetric =
    typeof runtimeMetrics.shell_readonly_hit_rate === "object" && runtimeMetrics.shell_readonly_hit_rate
      ? runtimeMetrics.shell_readonly_hit_rate
      : {};
  const routeSemanticDistributionMetric =
    typeof runtimeMetrics.agent_route_semantic_distribution === "object" && runtimeMetrics.agent_route_semantic_distribution
      ? runtimeMetrics.agent_route_semantic_distribution
      : {};
  const shellToCoreDispatchMetric =
    typeof runtimeMetrics.shell_to_core_dispatch_rate === "object" && runtimeMetrics.shell_to_core_dispatch_rate
      ? runtimeMetrics.shell_to_core_dispatch_rate
      : {};
  const shellClarifyBudgetEscalationMetric =
    typeof runtimeMetrics.shell_clarify_budget_escalation_rate === "object" &&
    runtimeMetrics.shell_clarify_budget_escalation_rate
      ? runtimeMetrics.shell_clarify_budget_escalation_rate
      : {};
  const coreExecutionSessionCreationMetric =
    typeof runtimeMetrics.core_execution_session_creation_rate === "object" &&
    runtimeMetrics.core_execution_session_creation_rate
      ? runtimeMetrics.core_execution_session_creation_rate
      : {};
  const runtimeRouteQuality = asRecord(runtimeSummary.route_quality);
  const runtimeRouteQualityTrend = asRecord(runtimeRouteQuality.trend);
  const incidentPromptSafety = asRecord(incidentsSummary?.runtime_prompt_safety);
  const incidentReadonlyExposure = asRecord(incidentPromptSafety.readonly_write_tool_exposure_rate);
  const incidentShellReadonlyHit = asRecord(incidentPromptSafety.shell_readonly_hit_rate);
  const incidentRouteDistribution = asRecord(incidentPromptSafety.agent_route_semantic_distribution);
  const incidentShellToCoreDispatch = asRecord(
    incidentPromptSafety.shell_to_core_dispatch_rate,
  );
  const incidentShellClarifyBudgetEscalation = asRecord(incidentPromptSafety.shell_clarify_budget_escalation_rate);
  const incidentCoreSessionCreation = asRecord(incidentPromptSafety.core_execution_session_creation_rate);
  const incidentRouteQuality = asRecord(incidentPromptSafety.route_quality);
  const incidentRouteQualityTrend = asRecord(incidentRouteQuality.trend);
  const runtimeRouteSemanticRatios = asRecord(
    (routeSemanticDistributionMetric as { route_semantic_ratios?: unknown }).route_semantic_ratios,
  );
  const runtimeShellReadonlyRatio = runtimeRouteSemanticRatios.shell_readonly;
  const runtimeShellClarifyRatio = runtimeRouteSemanticRatios.shell_clarify;
  const runtimeCoreExecutionRatio = runtimeRouteSemanticRatios.core_execution;
  const incidentRouteSemanticRatios = asRecord(
    (incidentRouteDistribution as { route_semantic_ratios?: unknown }).route_semantic_ratios,
  );
  const incidentShellReadonlyRatio = incidentRouteSemanticRatios.shell_readonly;
  const incidentShellClarifyRatio = incidentRouteSemanticRatios.shell_clarify;
  const incidentCoreExecutionRatio = incidentRouteSemanticRatios.core_execution;

  const outboxPending = summary?.outbox_pending;
  const oldestPendingAge = summary?.oldest_pending_age_seconds;
  const leaseLost = Number(eventCounters.LeaseLost || 0);
  const state = toState(payload?.severity || "unknown");
  const incidentsState = toState(incidentsPayload?.severity || "unknown");
  const readonlyExposureState = toState(String((readonlyExposureMetric as { status?: unknown }).status || "unknown"));
  const shellReadonlyState = toState(String((shellReadonlyMetric as { status?: unknown }).status || "unknown"));
  const routeDistributionState = toState(
    String((routeSemanticDistributionMetric as { status?: unknown }).status || "unknown"),
  );
  const shellToCoreDispatchState = toState(
    String((shellToCoreDispatchMetric as { status?: unknown }).status || "unknown"),
  );
  const pathBBudgetEscalationState = toState(
    String((shellClarifyBudgetEscalationMetric as { status?: unknown }).status || "unknown"),
  );
  const coreSessionCreationState = toState(
    String((coreExecutionSessionCreationMetric as { status?: unknown }).status || "unknown"),
  );
  const runtimeRouteQualityState = toState(String(runtimeRouteQuality.status || "unknown"));
  const incidentRouteQualityState = toState(String(incidentRouteQuality.status || "unknown"));
  const runtimeRouteQualityDirection = String(runtimeRouteQualityTrend.direction || copy.words.unknown);
  const incidentRouteQualityDirection = String(incidentRouteQualityTrend.direction || copy.words.unknown);
  const latestIncidentText = formatIsoDateTime(incidentsSummary?.latest_incident_at, lang, "--");
  const eventDbState = toState(String(eventDatabase?.status || summary?.event_db_status || "unknown"));
  const eventDbLatestText = formatIsoDateTime(eventDatabase?.latest_timestamp || summary?.event_db_latest_at, lang, "--");
  const incidentsTotalValue = formatNumber(incidentsSummary?.total_incidents, lang, {
    maximumFractionDigits: 0,
    fallback: "--",
  });
  const incidentsCriticalValue = formatNumber(incidentsSummary?.critical_incidents, lang, {
    maximumFractionDigits: 0,
    fallback: "--",
  });
  const incidentsWarningValue = formatNumber(incidentsSummary?.warning_incidents, lang, {
    maximumFractionDigits: 0,
    fallback: "--",
  });
  const eventDbRowsValue = formatNumber(eventDatabase?.total_rows ?? summary?.event_db_rows, lang, {
    maximumFractionDigits: 0,
    fallback: "--",
  });
  const eventDbPartitionsValue = formatNumber(eventDatabase?.partition_count ?? summary?.event_db_partitions, lang, {
    maximumFractionDigits: 0,
    fallback: "--",
  });

  return (
    <div className="space-y-6">
      {!dataSourceConnected && (
        <article className="rounded-3xl border border-amber-300/60 bg-amber-50/80 px-5 py-4 text-sm text-amber-900 shadow-[inset_0_1px_0_rgba(255,255,255,0.5)]">
          {copy.words.dataSourceOffline}
        </article>
      )}
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
          value={incidentsTotalValue}
          note={copy.cards.incidentsTotal.note}
          state={incidentsState}
          stateLabel={translateSignalState(incidentsState, lang)}
        />
        <SignalCard
          title={copy.cards.criticalIncidents.title}
          value={incidentsCriticalValue}
          note={copy.cards.criticalIncidents.note}
          state={Number(incidentsSummary?.critical_incidents || 0) > 0 ? "critical" : incidentsState}
          stateLabel={translateSignalState(Number(incidentsSummary?.critical_incidents || 0) > 0 ? "critical" : incidentsState, lang)}
        />
        <SignalCard
          title={copy.cards.warningIncidents.title}
          value={incidentsWarningValue}
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

      <section className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
        <SignalCard
          title={copy.cards.eventDbRows.title}
          value={eventDbRowsValue}
          note={copy.cards.eventDbRows.note}
          state={eventDbState}
          stateLabel={translateSignalState(eventDbState, lang)}
        />
        <SignalCard
          title={copy.cards.eventDbPartitions.title}
          value={eventDbPartitionsValue}
          note={copy.cards.eventDbPartitions.note}
          state={eventDbState}
          stateLabel={translateSignalState(eventDbState, lang)}
        />
        <SignalCard
          title={copy.cards.eventDbSize.title}
          value={toStorageSize(eventDatabase?.size_bytes, lang)}
          note={copy.cards.eventDbSize.note}
          state={eventDbState}
          stateLabel={translateSignalState(eventDbState, lang)}
        />
        <SignalCard
          title={copy.cards.eventDbLatest.title}
          value={eventDbLatestText}
          note={copy.cards.eventDbLatest.note}
          state={eventDbState}
          stateLabel={translateSignalState(eventDbState, lang)}
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
          <p className="text-[10px] font-bold uppercase tracking-[0.25em] text-gray-500">{copy.sections.eventDatabasePartitions}</p>
          <div className="mt-4 overflow-auto rounded-2xl bg-white/70 p-3">
            <table className="min-w-full text-left text-xs text-gray-700">
              <thead>
                <tr className="border-b border-gray-200/80">
                  <th className="px-2 py-2 uppercase tracking-[0.2em]">{copy.columns.partition}</th>
                  <th className="px-2 py-2 uppercase tracking-[0.2em]">{copy.columns.rows}</th>
                  <th className="px-2 py-2 uppercase tracking-[0.2em]">{copy.columns.latest}</th>
                </tr>
              </thead>
              <tbody>
                {eventDbPartitions.slice(0, 20).map((item, idx) => (
                  <tr key={`${item.partition_ym}-${idx}`} className="border-b border-gray-100/70 align-top">
                    <td className="px-2 py-2 font-mono">{String(item.partition_ym || "-")}</td>
                    <td className="px-2 py-2">{formatNumber(item.row_count || 0, lang, { maximumFractionDigits: 0 })}</td>
                    <td className="px-2 py-2 font-mono">{formatIsoDateTime(item.latest_timestamp, lang, "--")}</td>
                  </tr>
                ))}
                {eventDbPartitions.length === 0 && (
                  <tr>
                    <td colSpan={3} className="px-2 py-3 text-gray-500">
                      {copy.words.noRows}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </article>

        <article className="glass-card p-6">
          <p className="text-[10px] font-bold uppercase tracking-[0.25em] text-gray-500">{copy.sections.eventDatabaseTopics}</p>
          <div className="mt-4 overflow-auto rounded-2xl bg-white/70 p-3">
            <table className="min-w-full text-left text-xs text-gray-700">
              <thead>
                <tr className="border-b border-gray-200/80">
                  <th className="px-2 py-2 uppercase tracking-[0.2em]">{copy.columns.topic}</th>
                  <th className="px-2 py-2 uppercase tracking-[0.2em]">{copy.columns.rows}</th>
                  <th className="px-2 py-2 uppercase tracking-[0.2em]">{copy.columns.latest}</th>
                </tr>
              </thead>
              <tbody>
                {eventDbTopics.slice(0, 20).map((item, idx) => (
                  <tr key={`${item.topic}-${idx}`} className="border-b border-gray-100/70 align-top">
                    <td className="px-2 py-2">{String(item.topic || "-")}</td>
                    <td className="px-2 py-2">{formatNumber(item.row_count || 0, lang, { maximumFractionDigits: 0 })}</td>
                    <td className="px-2 py-2 font-mono">{formatIsoDateTime(item.latest_timestamp, lang, "--")}</td>
                  </tr>
                ))}
                {eventDbTopics.length === 0 && (
                  <tr>
                    <td colSpan={3} className="px-2 py-3 text-gray-500">
                      {copy.words.noRows}
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
              <p className="font-bold uppercase tracking-[0.2em] text-gray-500">{copy.sections.runtimeCrossSignals}</p>
              <div className="mt-2 grid grid-cols-1 gap-3">
                <MetricBar
                  label={copy.metricLabels.readonlyWriteExposure}
                  value={toPercent((readonlyExposureMetric as { value?: unknown }).value, lang)}
                  ratio={
                    typeof (readonlyExposureMetric as { value?: unknown }).value === "number"
                      ? ((readonlyExposureMetric as { value?: number }).value ?? null)
                      : null
                  }
                  tone={toTone(readonlyExposureState)}
                  right={
                    <span>
                      {copy.words.sampleCount} {toNumber((readonlyExposureMetric as { sample_count?: unknown }).sample_count, lang)}
                    </span>
                  }
                  hint={`${copy.words.exposureCount}: ${toNumber((readonlyExposureMetric as { exposure_count?: unknown }).exposure_count, lang)}`}
                />
                <MetricBar
                  label={copy.metricLabels.outerReadonlyHitRate}
                  value={toPercent((shellReadonlyMetric as { value?: unknown }).value, lang)}
                  ratio={
                    typeof (shellReadonlyMetric as { value?: unknown }).value === "number"
                      ? ((shellReadonlyMetric as { value?: number }).value ?? null)
                      : null
                  }
                  tone={toTone(shellReadonlyState)}
                  hint={`${copy.words.hitCount}: ${toNumber((shellReadonlyMetric as { hit_count?: unknown }).hit_count, lang)}`}
                />
                <MetricBar
                  label={copy.metricLabels.pathCRouteShare}
                  value={toPercent(runtimeCoreExecutionRatio, lang)}
                  ratio={toRatio(runtimeCoreExecutionRatio)}
                  tone={toTone(routeDistributionState)}
                  right={
                    <span>
                      {copy.words.sampleCount}{" "}
                      {toNumber((routeSemanticDistributionMetric as { sample_count?: unknown }).sample_count, lang)}
                    </span>
                  }
                  hint={`${copy.words.shellReadonlyRatio}: ${toPercent(runtimeShellReadonlyRatio, lang)} · ${copy.words.shellClarifyRatio}: ${toPercent(runtimeShellClarifyRatio, lang)} · ${copy.words.coreExecutionRatio}: ${toPercent(runtimeCoreExecutionRatio, lang)}`}
                />
                <MetricBar
                  label={copy.metricLabels.shellToCoreDispatch}
                  value={toPercent((shellToCoreDispatchMetric as { value?: unknown }).value, lang)}
                  ratio={toRatio((shellToCoreDispatchMetric as { value?: unknown }).value)}
                  tone={toTone(shellToCoreDispatchState)}
                  right={
                    <span>
                      {copy.words.sampleCount} {toNumber((shellToCoreDispatchMetric as { sample_count?: unknown }).sample_count, lang)}
                    </span>
                  }
                  hint={`${copy.words.dispatchToCoreRate}: ${toPercent((shellToCoreDispatchMetric as { value?: unknown }).value, lang)}`}
                />
                <MetricBar
                  label={copy.metricLabels.pathBBudgetEscalation}
                  value={toPercent((shellClarifyBudgetEscalationMetric as { value?: unknown }).value, lang)}
                  ratio={toRatio((shellClarifyBudgetEscalationMetric as { value?: unknown }).value)}
                  tone={toTone(pathBBudgetEscalationState)}
                  right={
                    <span>
                      {copy.words.sampleCount}{" "}
                      {toNumber((shellClarifyBudgetEscalationMetric as { sample_count?: unknown }).sample_count, lang)}
                    </span>
                  }
                  hint={`${copy.words.escalatedCount}: ${toNumber((shellClarifyBudgetEscalationMetric as { escalated_count?: unknown }).escalated_count, lang)}`}
                />
                <MetricBar
                  label={copy.metricLabels.coreSessionCreation}
                  value={toPercent((coreExecutionSessionCreationMetric as { value?: unknown }).value, lang)}
                  ratio={toRatio((coreExecutionSessionCreationMetric as { value?: unknown }).value)}
                  tone={toTone(coreSessionCreationState)}
                  right={
                    <span>
                      {copy.words.sampleCount}{" "}
                      {toNumber((coreExecutionSessionCreationMetric as { sample_count?: unknown }).sample_count, lang)}
                    </span>
                  }
                  hint={`${copy.words.createdCount}: ${toNumber((coreExecutionSessionCreationMetric as { created_count?: unknown }).created_count, lang)}`}
                />
                <MetricBar
                  label={copy.metricLabels.routeQuality}
                  value={String(runtimeRouteQuality.status || copy.words.unknown).toUpperCase()}
                  ratio={stateToRatio(runtimeRouteQualityState)}
                  tone={toTone(runtimeRouteQualityState)}
                  hint={`${copy.words.routeQualityReason}: ${String(runtimeRouteQuality.reason_text || "--")} · ${copy.words.trend}: ${runtimeRouteQualityDirection} · ${copy.words.volatility}: ${toNumber(runtimeRouteQualityTrend.volatility, lang)}`}
                />
              </div>
            </div>
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
          <div className="mt-4 space-y-3 text-xs text-gray-700">
            <div className="rounded-xl bg-white/70 p-3">
              <p className="font-bold uppercase tracking-[0.2em] text-gray-500">{copy.sections.incidentPromptSafety}</p>
              <div className="mt-2 grid grid-cols-1 gap-3">
                <MetricBar
                  label={copy.metricLabels.readonlyWriteExposure}
                  value={toPercent(incidentReadonlyExposure.value, lang)}
                  ratio={toRatio(incidentReadonlyExposure.value)}
                  tone={toTone(toState(String(incidentReadonlyExposure.status || "unknown")))}
                  right={
                    <span>
                      {copy.words.sampleCount} {toNumber(incidentReadonlyExposure.sample_count, lang)}
                    </span>
                  }
                  hint={`${copy.words.exposureCount}: ${toNumber(incidentReadonlyExposure.exposure_count, lang)}`}
                />
                <MetricBar
                  label={copy.metricLabels.outerReadonlyHitRate}
                  value={toPercent(incidentShellReadonlyHit.value, lang)}
                  ratio={toRatio(incidentShellReadonlyHit.value)}
                  tone={toTone(toState(String(incidentShellReadonlyHit.status || "unknown")))}
                  hint={`${copy.words.hitCount}: ${toNumber(incidentShellReadonlyHit.hit_count, lang)}`}
                />
                <MetricBar
                  label={copy.metricLabels.pathCRouteShare}
                  value={toPercent(incidentCoreExecutionRatio, lang)}
                  ratio={toRatio(incidentCoreExecutionRatio)}
                  tone={toTone(toState(String(incidentRouteDistribution.status || "unknown")))}
                  right={
                    <span>
                      {copy.words.sampleCount} {toNumber(incidentRouteDistribution.sample_count, lang)}
                    </span>
                  }
                  hint={`${copy.words.shellReadonlyRatio}: ${toPercent(incidentShellReadonlyRatio, lang)} · ${copy.words.shellClarifyRatio}: ${toPercent(incidentShellClarifyRatio, lang)} · ${copy.words.coreExecutionRatio}: ${toPercent(incidentCoreExecutionRatio, lang)}`}
                />
                <MetricBar
                  label={copy.metricLabels.shellToCoreDispatch}
                  value={toPercent(incidentShellToCoreDispatch.value, lang)}
                  ratio={toRatio(incidentShellToCoreDispatch.value)}
                  tone={toTone(toState(String(incidentShellToCoreDispatch.status || "unknown")))}
                  right={
                    <span>
                      {copy.words.sampleCount} {toNumber(incidentShellToCoreDispatch.sample_count, lang)}
                    </span>
                  }
                  hint={`${copy.words.dispatchToCoreRate}: ${toPercent(incidentShellToCoreDispatch.value, lang)}`}
                />
                <MetricBar
                  label={copy.metricLabels.pathBBudgetEscalation}
                  value={toPercent(incidentShellClarifyBudgetEscalation.value, lang)}
                  ratio={toRatio(incidentShellClarifyBudgetEscalation.value)}
                  tone={toTone(toState(String(incidentShellClarifyBudgetEscalation.status || "unknown")))}
                  right={
                    <span>
                      {copy.words.sampleCount} {toNumber(incidentShellClarifyBudgetEscalation.sample_count, lang)}
                    </span>
                  }
                  hint={`${copy.words.escalatedCount}: ${toNumber(incidentShellClarifyBudgetEscalation.escalated_count, lang)}`}
                />
                <MetricBar
                  label={copy.metricLabels.coreSessionCreation}
                  value={toPercent(incidentCoreSessionCreation.value, lang)}
                  ratio={toRatio(incidentCoreSessionCreation.value)}
                  tone={toTone(toState(String(incidentCoreSessionCreation.status || "unknown")))}
                  right={
                    <span>
                      {copy.words.sampleCount} {toNumber(incidentCoreSessionCreation.sample_count, lang)}
                    </span>
                  }
                  hint={`${copy.words.createdCount}: ${toNumber(incidentCoreSessionCreation.created_count, lang)}`}
                />
                <MetricBar
                  label={copy.metricLabels.routeQuality}
                  value={String(incidentRouteQuality.status || copy.words.unknown).toUpperCase()}
                  ratio={stateToRatio(incidentRouteQualityState)}
                  tone={toTone(incidentRouteQualityState)}
                  hint={`${copy.words.routeQualityReason}: ${String(incidentRouteQuality.reason_text || "--")} · ${copy.words.trend}: ${incidentRouteQualityDirection} · ${copy.words.volatility}: ${toNumber(incidentRouteQualityTrend.volatility, lang)}`}
                />
              </div>
            </div>

            <div className="rounded-xl bg-white/70 p-3 text-xs text-gray-700">
              <pre className="whitespace-pre-wrap">
                {JSON.stringify(
                  {
                    severity: incidentsPayload?.severity || copy.words.unknown,
                    reason_code: incidentsPayload?.reason_code || "",
                    reason_text: incidentsPayload?.reason_text || "",
                    event_counters: incidentsPayload?.data?.event_counters || {},
                    events_scanned: incidentsPayload?.data?.events_scanned || 0,
                    runtime_prompt_safety: incidentPromptSafety,
                  },
                  null,
                  2,
                )}
              </pre>
            </div>
          </div>
        </article>
      </section>
    </div>
  );
}
