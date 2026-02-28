import { SignalCard, type SignalState } from "@/components/cards/signal-card";
import { MetricBar, type MetricBarTone } from "@/components/charts/metric-bar";
import { fetchEvidenceIndex, fetchIncidentsLatest, fetchRuntimePosture } from "@/lib/api/ops";
import { fetchSystemConfig } from "@/lib/api/system";
import {
  formatIsoDateTime,
  formatNumber,
  formatPercentRatio,
  resolveLangFromSearchParams,
  translateSignalState,
  type AppLang,
} from "@/lib/i18n";

export const dynamic = "force-dynamic";

type RuntimeCard = {
  title: string;
  value: string;
  note: string;
  state: SignalState;
};

type RuntimePageProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

const PAGE_COPY: Record<
  AppLang,
  {
    cards: {
      runtimeRollout: { title: string; note: string };
      failOpen: { title: string; note: string };
      readonlyExposure: { title: string; note: string };
      routeQuality: { title: string; note: string };
      brainstemControlPlane: { title: string; note: string };
      lease: { title: string; note: string };
      queueDepth: { title: string; note: string };
      lockStatus: { title: string; note: string };
      diskWatermark: { title: string; note: string };
    };
    sections: {
      runtimeBudget: string;
      dataSources: string;
      evidenceGates: string;
      requiredEvidence: string;
      leaseGuard: string;
      brainstemGate: string;
      runtimeGovernanceConfig: string;
      summarySnapshot: string;
      recentEvidenceFiles: string;
    };
    metricLabels: {
      rolloutHitRatio: string;
      failOpenUsage: string;
      readonlyWriteExposure: string;
      pathCRouteShare: string;
      pathBBudgetEscalation: string;
      coreSessionCreation: string;
      queuePressure: string;
      diskUsage: string;
      evidenceCoverage: string;
      evidencePassRatio: string;
    };
    words: {
      totalDecisions: string;
      blocked: string;
      budget: string;
      critical: string;
      oldestPendingAge: string;
      gbFree: string;
      sampleCount: string;
      exposureCount: string;
      escalatedCount: string;
      createdCount: string;
      outerReadonlyHitRate: string;
      pathARatio: string;
      pathBRatio: string;
      pathCRatio: string;
      eventsScanned: string;
      missing: string;
      failed: string;
      discoveredRequiredEvidence: string;
      requiredReportsPassed: string;
      noSourceReport: string;
      noEvidenceIndexed: string;
      noRecentEvidenceFile: string;
      state: string;
      owner: string;
      fencingEpoch: string;
      secondsToExpiry: string;
      trend: string;
      volatility: string;
      latestIncident: string;
      heartbeatAge: string;
      staleWarning: string;
      staleCritical: string;
      healthy: string;
      serviceCount: string;
      unhealthyServices: string;
      reasonCode: string;
      reasonText: string;
      tick: string;
      pid: string;
      generatedAt: string;
      auditLedgerFile: string;
      approvalRequiredScopes: string;
      noApprovalScopesConfigured: string;
      noIncidentSignal: string;
      noBrainstemIncident: string;
      seconds: string;
      yes: string;
      no: string;
      none: string;
    };
  }
> = {
  en: {
    cards: {
      runtimeRollout: { title: "Runtime Rollout", note: "SubAgent decision hit ratio" },
      failOpen: { title: "Fail Open", note: "Current fail-open ratio" },
      readonlyExposure: { title: "Readonly Write Exposure", note: "Path-A write-tool leakage ratio" },
      routeQuality: { title: "Route Quality", note: "Unified route-quality guard status" },
      brainstemControlPlane: { title: "Brainstem Control Plane", note: "Daemon heartbeat and managed hosting gate" },
      lease: { title: "Lease", note: "Global orchestrator lease state" },
      queueDepth: { title: "Queue Depth", note: "Pending outbox events" },
      lockStatus: { title: "Lock Status", note: "Global mutex lock health" },
      diskWatermark: { title: "Disk Watermark", note: "Artifact storage usage ratio" },
    },
    sections: {
      runtimeBudget: "Runtime Budget & Pressure",
      dataSources: "Data Sources",
      evidenceGates: "M12 Evidence Gates",
      requiredEvidence: "Required Evidence Reports",
      leaseGuard: "Lease Guard",
      brainstemGate: "Brainstem Control-Plane Gate",
      runtimeGovernanceConfig: "Runtime Governance Config",
      summarySnapshot: "Summary Snapshot",
      recentEvidenceFiles: "Recent Evidence Files",
    },
    metricLabels: {
      rolloutHitRatio: "Rollout Hit Ratio",
      failOpenUsage: "Fail-Open Usage",
      readonlyWriteExposure: "Readonly Write Exposure",
      pathCRouteShare: "Path-C Route Share",
      pathBBudgetEscalation: "Path-B Budget Escalation",
      coreSessionCreation: "Core Session Creation",
      queuePressure: "Queue Pressure",
      diskUsage: "Disk Usage",
      evidenceCoverage: "Evidence Coverage",
      evidencePassRatio: "Evidence Pass Ratio",
    },
    words: {
      totalDecisions: "Total decisions",
      blocked: "Blocked",
      budget: "Budget",
      critical: "Critical",
      oldestPendingAge: "Oldest pending age",
      gbFree: "GB free",
      sampleCount: "Sample count",
      exposureCount: "Exposure count",
      escalatedCount: "Escalated count",
      createdCount: "Created count",
      outerReadonlyHitRate: "Outer readonly hit rate",
      pathARatio: "Path-A",
      pathBRatio: "Path-B",
      pathCRatio: "Path-C",
      eventsScanned: "events_scanned",
      missing: "Missing",
      failed: "Failed",
      discoveredRequiredEvidence: "Discovered required evidence reports",
      requiredReportsPassed: "Required reports currently in passed state",
      noSourceReport: "No source report detected.",
      noEvidenceIndexed: "No evidence report indexed.",
      noRecentEvidenceFile: "No recent evidence file.",
      state: "State",
      owner: "Owner",
      fencingEpoch: "Fencing Epoch",
      secondsToExpiry: "Seconds To Expiry",
      trend: "Trend",
      volatility: "Volatility",
      latestIncident: "Latest incident",
      heartbeatAge: "Heartbeat age",
      staleWarning: "Stale warning",
      staleCritical: "Stale critical",
      healthy: "Healthy",
      serviceCount: "Service count",
      unhealthyServices: "Unhealthy services",
      reasonCode: "Reason code",
      reasonText: "Reason text",
      tick: "Tick",
      pid: "PID",
      generatedAt: "Generated at",
      auditLedgerFile: "Audit ledger file",
      approvalRequiredScopes: "Approval required scopes",
      noApprovalScopesConfigured: "No approval scope configured.",
      noIncidentSignal: "No incident signal detected.",
      noBrainstemIncident: "No brainstem incident in current window.",
      seconds: "s",
      yes: "yes",
      no: "no",
      none: "none",
    },
  },
  "zh-CN": {
    cards: {
      runtimeRollout: { title: "运行分流命中率", note: "SubAgent 决策命中比例" },
      failOpen: { title: "Fail-Open 比例", note: "当前降级放行占比" },
      readonlyExposure: { title: "只读写工具暴露率", note: "Path-A 写工具泄露占比" },
      routeQuality: { title: "路由质量", note: "统一路由质量门禁状态" },
      brainstemControlPlane: { title: "脑干管控面", note: "守护心跳与托管门禁状态" },
      lease: { title: "租约状态", note: "全局调度租约健康状态" },
      queueDepth: { title: "队列深度", note: "待处理 outbox 事件数" },
      lockStatus: { title: "锁状态", note: "全局互斥锁健康度" },
      diskWatermark: { title: "磁盘水位", note: "Artifact 存储使用率" },
    },
    sections: {
      runtimeBudget: "运行预算与压力",
      dataSources: "数据来源",
      evidenceGates: "M12 证据门禁",
      requiredEvidence: "必需证据报告",
      leaseGuard: "租约防护",
      brainstemGate: "脑干管控门禁",
      runtimeGovernanceConfig: "运行治理配置快照",
      summarySnapshot: "摘要快照",
      recentEvidenceFiles: "最近证据文件",
    },
    metricLabels: {
      rolloutHitRatio: "分流命中率",
      failOpenUsage: "Fail-Open 使用率",
      readonlyWriteExposure: "只读写工具暴露率",
      pathCRouteShare: "Path-C 路由占比",
      pathBBudgetEscalation: "Path-B 预算升级率",
      coreSessionCreation: "Core 会话新建率",
      queuePressure: "队列压力",
      diskUsage: "磁盘使用情况",
      evidenceCoverage: "证据覆盖率",
      evidencePassRatio: "证据通过率",
    },
    words: {
      totalDecisions: "总决策数",
      blocked: "已阻断",
      budget: "预算",
      critical: "严重阈值",
      oldestPendingAge: "最老待处理时长",
      gbFree: "GB 可用空间",
      sampleCount: "样本数",
      exposureCount: "暴露次数",
      escalatedCount: "升级次数",
      createdCount: "新建次数",
      outerReadonlyHitRate: "外层只读命中率",
      pathARatio: "Path-A",
      pathBRatio: "Path-B",
      pathCRatio: "Path-C",
      eventsScanned: "events_scanned",
      missing: "缺失",
      failed: "失败",
      discoveredRequiredEvidence: "已发现的必需证据报告",
      requiredReportsPassed: "当前处于通过状态的必需报告",
      noSourceReport: "未检测到来源报告。",
      noEvidenceIndexed: "未索引到证据报告。",
      noRecentEvidenceFile: "暂无最近证据文件。",
      state: "状态",
      owner: "持有者",
      fencingEpoch: "Fencing Epoch",
      secondsToExpiry: "距过期秒数",
      trend: "趋势",
      volatility: "波动率",
      latestIncident: "最新事件",
      heartbeatAge: "心跳年龄",
      staleWarning: "告警阈值",
      staleCritical: "严重阈值",
      healthy: "健康标记",
      serviceCount: "服务数量",
      unhealthyServices: "异常服务",
      reasonCode: "原因码",
      reasonText: "原因说明",
      tick: "心跳计数",
      pid: "进程号",
      generatedAt: "生成时间",
      auditLedgerFile: "审计账本文件",
      approvalRequiredScopes: "需人工审批范围",
      noApprovalScopesConfigured: "未配置审批范围。",
      noIncidentSignal: "未检测到事件信号。",
      noBrainstemIncident: "当前窗口无脑干相关事件。",
      seconds: "秒",
      yes: "是",
      no: "否",
      none: "无",
    },
  },
};

function asRecord(value: unknown): Record<string, unknown> {
  if (typeof value === "object" && value !== null) {
    return value as Record<string, unknown>;
  }
  return {};
}

function asArray(value: unknown): Record<string, unknown>[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter((item): item is Record<string, unknown> => typeof item === "object" && item !== null);
}

function asNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  return null;
}

function asBoolean(value: unknown): boolean | null {
  if (typeof value === "boolean") {
    return value;
  }
  return null;
}

function asText(value: unknown, fallback = "--"): string {
  if (typeof value === "string" && value.trim()) {
    return value;
  }
  if (typeof value === "number" && Number.isFinite(value)) {
    return String(value);
  }
  return fallback;
}

function toPercent(value: unknown, lang: AppLang): string {
  return formatPercentRatio(value, lang, 1, "--");
}

function toNumber(value: unknown, lang: AppLang, maxFractionDigits = 0): string {
  return formatNumber(value, lang, {
    maximumFractionDigits: maxFractionDigits,
    minimumFractionDigits: maxFractionDigits > 0 ? Math.min(maxFractionDigits, 2) : 0,
    fallback: "--",
  });
}

function toState(raw: unknown): SignalState {
  const text = String(raw || "unknown").toLowerCase();
  if (text === "ok" || text === "healthy") {
    return "healthy";
  }
  if (text === "warning" || text === "near_expiry") {
    return "warning";
  }
  if (text === "critical" || text === "expired") {
    return "critical";
  }
  return "unknown";
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

function toEvidenceState(status: unknown, gateLevel: unknown): SignalState {
  const normalizedStatus = String(status || "unknown").toLowerCase();
  const normalizedGate = String(gateLevel || "soft").toLowerCase();
  if (normalizedStatus === "passed") {
    return "healthy";
  }
  if (normalizedStatus === "failed" || normalizedStatus === "missing") {
    return normalizedGate === "hard" ? "critical" : "warning";
  }
  return "unknown";
}

function toneClassForState(state: SignalState): string {
  if (state === "healthy") {
    return "bg-emerald-100 text-emerald-700";
  }
  if (state === "critical") {
    return "bg-rose-100 text-rose-700";
  }
  if (state === "warning") {
    return "bg-amber-100 text-amber-700";
  }
  return "bg-slate-100 text-slate-700";
}

function gateLabel(gateLevel: unknown, lang: AppLang): string {
  const normalized = String(gateLevel || "soft").toLowerCase();
  if (lang === "zh-CN") {
    return normalized === "hard" ? "硬门禁" : "软门禁";
  }
  return normalized === "hard" ? "hard-gate" : "soft-gate";
}

function reportStatusLabel(status: unknown, lang: AppLang): string {
  const normalized = String(status || "unknown").toLowerCase();
  if (lang === "zh-CN") {
    if (normalized === "passed") {
      return "通过";
    }
    if (normalized === "failed") {
      return "失败";
    }
    if (normalized === "missing") {
      return "缺失";
    }
    return "未知";
  }
  return normalized;
}

export default async function RuntimePosturePage({ searchParams }: RuntimePageProps) {
  const lang = await resolveLangFromSearchParams(searchParams);
  const copy = PAGE_COPY[lang];
  const [payload, evidencePayload, incidentsPayload, systemConfig] = await Promise.all([
    fetchRuntimePosture(),
    fetchEvidenceIndex(),
    fetchIncidentsLatest(),
    fetchSystemConfig(),
  ]);
  const metrics = asRecord(payload?.data?.metrics);
  const runtimeRollout = asRecord(metrics.runtime_rollout);
  const runtimeFailOpen = asRecord(metrics.runtime_fail_open);
  const runtimeLease = asRecord(metrics.runtime_lease);
  const queueDepth = asRecord(metrics.queue_depth);
  const lockStatus = asRecord(metrics.lock_status);
  const diskWatermark = asRecord(metrics.disk_watermark_ratio);
  const outerReadonlyHitRate = asRecord(metrics.outer_readonly_hit_rate);
  const readonlyWriteToolExposure = asRecord(metrics.readonly_write_tool_exposure_rate);
  const chatRoutePathDistribution = asRecord(metrics.chat_route_path_distribution);
  const pathBBudgetEscalation = asRecord(metrics.path_b_budget_escalation_rate);
  const coreSessionCreation = asRecord(metrics.core_session_creation_rate);
  const sources = asRecord(payload?.data?.sources);
  const postureSummary = asRecord(payload?.data?.summary);
  const brainstemControlPlane = asRecord(payload?.data?.brainstem_control_plane);
  const emblaSystem = asRecord(asRecord(systemConfig || {}).embla_system);
  const emblaSecurity = asRecord(emblaSystem.security);
  const emblaAuditLedgerFile = asText(emblaSecurity.audit_ledger_file, "scratch/runtime/audit_ledger.jsonl");
  const emblaApprovalRequiredScopes = Array.isArray(emblaSecurity.approval_required_scopes)
    ? emblaSecurity.approval_required_scopes.map((item) => String(item || "").trim()).filter((item) => item.length > 0)
    : [];
  const brainstemStatus = asText(postureSummary.brainstem_control_plane_status, "unknown");
  const routeQuality = asRecord(postureSummary.route_quality);
  const routeQualityTrend = asRecord(routeQuality.trend);

  const evidenceSummary = asRecord(evidencePayload?.data?.summary);
  const requiredReports = asArray(evidencePayload?.data?.required_reports);
  const recentReports = asArray(evidencePayload?.data?.recent_reports);
  const incidentsSummary = asRecord(incidentsPayload?.data?.summary);
  const incidents = asArray(incidentsPayload?.data?.incidents);
  const brainstemIncidents = incidents.filter((item) => String(item.event_type || "").startsWith("Brainstem"));
  const latestBrainstemIncident = brainstemIncidents[0] || null;

  const rolloutValue = asNumber(runtimeRollout.value);
  const failOpenValue = asNumber(runtimeFailOpen.value);
  const failOpenBudget = asNumber(runtimeFailOpen.configured_budget_ratio);
  const diskUsage = asNumber(diskWatermark.value);
  const outerReadonlyHitValue = asNumber(outerReadonlyHitRate.value);
  const readonlyWriteExposureValue = asNumber(readonlyWriteToolExposure.value);
  const readonlyWriteExposureSampleCount = asNumber(readonlyWriteToolExposure.sample_count);
  const readonlyWriteExposureCount = asNumber(readonlyWriteToolExposure.exposure_count);
  const pathRatios = asRecord(chatRoutePathDistribution.path_ratios);
  const pathARatio = asNumber(pathRatios["path-a"]);
  const pathBRatio = asNumber(pathRatios["path-b"]);
  const pathCRatio = asNumber(pathRatios["path-c"]);
  const pathBBudgetEscalationValue = asNumber(pathBBudgetEscalation.value);
  const pathBBudgetEscalatedCount = asNumber(pathBBudgetEscalation.escalated_count);
  const pathBBudgetSampleCount = asNumber(pathBBudgetEscalation.sample_count);
  const coreSessionCreationValue = asNumber(coreSessionCreation.value);
  const coreSessionCreatedCount = asNumber(coreSessionCreation.created_count);
  const coreSessionSampleCount = asNumber(coreSessionCreation.sample_count);
  const routeQualityStatusText = asText(routeQuality.status, "unknown");
  const routeQualityReason = asText(routeQuality.reason_text, "");
  const routeQualityDirection = asText(routeQualityTrend.direction, "unknown");
  const routeQualityVolatility = asNumber(routeQualityTrend.volatility);
  const queuePending = asNumber(queueDepth.value);
  const queueCritical = asNumber(asRecord(queueDepth.thresholds).critical);
  const queueRatio = queuePending !== null && queueCritical && queueCritical > 0 ? queuePending / queueCritical : null;
  const brainstemHeartbeatAge = asNumber(brainstemControlPlane.heartbeat_age_seconds);
  const brainstemStaleWarning = asNumber(brainstemControlPlane.stale_warning_seconds);
  const brainstemStaleCritical = asNumber(brainstemControlPlane.stale_critical_seconds);
  const brainstemHealthy = asBoolean(brainstemControlPlane.healthy);
  const brainstemServiceCount = asNumber(brainstemControlPlane.service_count);
  const brainstemTick = asNumber(brainstemControlPlane.tick);
  const brainstemPid = asNumber(brainstemControlPlane.pid);
  const brainstemGeneratedAtText = formatIsoDateTime(brainstemControlPlane.generated_at, lang, "--");
  const brainstemReasonCode = asText(brainstemControlPlane.reason_code, "unknown");
  const brainstemReasonText = asText(brainstemControlPlane.reason_text, copy.cards.brainstemControlPlane.note);
  const latestBrainstemIncidentAt = formatIsoDateTime(latestBrainstemIncident?.timestamp, lang, "--");
  const latestIncidentAt = formatIsoDateTime(incidentsSummary.latest_incident_at, lang, "--");
  const latestBrainstemIncidentSummary = asText(latestBrainstemIncident?.summary, copy.words.noBrainstemIncident);
  const latestBrainstemIncidentType = asText(latestBrainstemIncident?.event_type, "n/a");
  const brainstemUnhealthyServices = Array.isArray(brainstemControlPlane.unhealthy_services)
    ? brainstemControlPlane.unhealthy_services.map((item) => String(item)).filter((item) => item.trim())
    : [];
  const brainstemHealthyText =
    brainstemHealthy === null ? "--" : brainstemHealthy ? copy.words.yes : copy.words.no;

  const requiredTotal = asNumber(evidenceSummary.required_total);
  const requiredPresent = asNumber(evidenceSummary.required_present);
  const requiredPassed = asNumber(evidenceSummary.required_passed);
  const requiredMissing = asNumber(evidenceSummary.required_missing);
  const requiredFailed = asNumber(evidenceSummary.required_failed);
  const evidenceCoverageRatio =
    requiredTotal !== null && requiredTotal > 0 && requiredPresent !== null ? requiredPresent / requiredTotal : null;
  const evidencePassRatio =
    requiredTotal !== null && requiredTotal > 0 && requiredPassed !== null ? requiredPassed / requiredTotal : null;

  const cards: RuntimeCard[] = [
    {
      title: copy.cards.runtimeRollout.title,
      value: toPercent(rolloutValue, lang),
      note: copy.cards.runtimeRollout.note,
      state: toState(runtimeRollout.status),
    },
    {
      title: copy.cards.failOpen.title,
      value: toPercent(failOpenValue, lang),
      note: copy.cards.failOpen.note,
      state: toState(runtimeFailOpen.status),
    },
    {
      title: copy.cards.readonlyExposure.title,
      value: toPercent(readonlyWriteExposureValue, lang),
      note: copy.cards.readonlyExposure.note,
      state: toState(readonlyWriteToolExposure.status),
    },
    {
      title: copy.cards.routeQuality.title,
      value: routeQualityStatusText.toUpperCase(),
      note:
        routeQualityReason
          ? `${routeQualityReason} · ${copy.words.trend}: ${routeQualityDirection} · ${copy.words.volatility}: ${toNumber(routeQualityVolatility, lang, 2)}`
          : copy.cards.routeQuality.note,
      state: toState(routeQualityStatusText),
    },
    {
      title: copy.cards.brainstemControlPlane.title,
      value: brainstemStatus.toUpperCase(),
      note: `${brainstemReasonCode} · ${copy.words.latestIncident}: ${latestBrainstemIncidentAt}`,
      state: toState(brainstemStatus),
    },
    {
      title: copy.cards.lease.title,
      value: String(runtimeLease.state || "missing").toUpperCase(),
      note: copy.cards.lease.note,
      state: toState(runtimeLease.status),
    },
    {
      title: copy.cards.queueDepth.title,
      value: toNumber(queuePending, lang),
      note: copy.cards.queueDepth.note,
      state: toState(queueDepth.status),
    },
    {
      title: copy.cards.lockStatus.title,
      value: String(lockStatus.state || "unknown").toUpperCase(),
      note: copy.cards.lockStatus.note,
      state: toState(lockStatus.status),
    },
    {
      title: copy.cards.diskWatermark.title,
      value: toPercent(diskUsage, lang),
      note: copy.cards.diskWatermark.note,
      state: toState(diskWatermark.status),
    },
  ];

  return (
    <div className="space-y-6">
      <section className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        {cards.map((card) => (
          <SignalCard
            key={card.title}
            title={card.title}
            value={card.value}
            note={card.note}
            state={card.state}
            stateLabel={translateSignalState(card.state, lang)}
          />
        ))}
      </section>

      <section className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <article className="glass-card p-6">
          <p className="text-[10px] font-bold uppercase tracking-[0.25em] text-gray-500">{copy.sections.runtimeBudget}</p>
          <div className="mt-4 grid grid-cols-1 gap-3">
            <MetricBar
              label={copy.metricLabels.rolloutHitRatio}
              value={toPercent(rolloutValue, lang)}
              ratio={rolloutValue}
              tone={toTone(toState(runtimeRollout.status))}
              hint={`${copy.words.totalDecisions}: ${asText(runtimeRollout.total_decisions)}`}
            />
            <MetricBar
              label={copy.metricLabels.failOpenUsage}
              value={toPercent(failOpenValue, lang)}
              ratio={failOpenValue}
              tone={toTone(toState(runtimeFailOpen.status))}
              right={
                <span>
                  {copy.words.budget} {toPercent(failOpenBudget, lang)}
                </span>
              }
              hint={`${copy.words.blocked}: ${asText(runtimeFailOpen.fail_open_blocked_count)}`}
            />
            <MetricBar
              label={copy.metricLabels.readonlyWriteExposure}
              value={toPercent(readonlyWriteExposureValue, lang)}
              ratio={readonlyWriteExposureValue}
              tone={toTone(toState(readonlyWriteToolExposure.status))}
              right={
                <span>
                  {copy.words.sampleCount} {toNumber(readonlyWriteExposureSampleCount, lang)}
                </span>
              }
              hint={`${copy.words.exposureCount}: ${toNumber(readonlyWriteExposureCount, lang)} · ${copy.words.outerReadonlyHitRate}: ${toPercent(outerReadonlyHitValue, lang)}`}
            />
            <MetricBar
              label={copy.metricLabels.pathCRouteShare}
              value={toPercent(pathCRatio, lang)}
              ratio={pathCRatio}
              tone={toTone(toState(chatRoutePathDistribution.status))}
              hint={`${copy.words.pathARatio}: ${toPercent(pathARatio, lang)} · ${copy.words.pathBRatio}: ${toPercent(pathBRatio, lang)} · ${copy.words.pathCRatio}: ${toPercent(pathCRatio, lang)}`}
            />
            <MetricBar
              label={copy.metricLabels.pathBBudgetEscalation}
              value={toPercent(pathBBudgetEscalationValue, lang)}
              ratio={pathBBudgetEscalationValue}
              tone={toTone(toState(pathBBudgetEscalation.status))}
              right={
                <span>
                  {copy.words.sampleCount} {toNumber(pathBBudgetSampleCount, lang)}
                </span>
              }
              hint={`${copy.words.escalatedCount}: ${toNumber(pathBBudgetEscalatedCount, lang)}`}
            />
            <MetricBar
              label={copy.metricLabels.coreSessionCreation}
              value={toPercent(coreSessionCreationValue, lang)}
              ratio={coreSessionCreationValue}
              tone={toTone(toState(coreSessionCreation.status))}
              right={
                <span>
                  {copy.words.sampleCount} {toNumber(coreSessionSampleCount, lang)}
                </span>
              }
              hint={`${copy.words.createdCount}: ${toNumber(coreSessionCreatedCount, lang)}`}
            />
            <MetricBar
              label={copy.metricLabels.queuePressure}
              value={toNumber(queuePending, lang)}
              ratio={queueRatio}
              tone={toTone(toState(queueDepth.status))}
              right={
                <span>
                  {copy.words.critical} {toNumber(queueCritical, lang)}
                </span>
              }
              hint={`${copy.words.oldestPendingAge}: ${toNumber(queueDepth.oldest_pending_age_seconds, lang)}s`}
            />
            <MetricBar
              label={copy.metricLabels.diskUsage}
              value={toPercent(diskUsage, lang)}
              ratio={diskUsage}
              tone={toTone(toState(diskWatermark.status))}
              right={
                <span>
                  {toNumber(diskWatermark.filesystem_free_gb, lang, 2)} {copy.words.gbFree}
                </span>
              }
            />
          </div>
        </article>

        <article className="glass-card p-6">
          <p className="text-[10px] font-bold uppercase tracking-[0.25em] text-gray-500">{copy.sections.dataSources}</p>
          <ul className="mt-4 space-y-2 text-sm text-gray-700">
            {(payload?.source_reports || []).map((path) => (
              <li key={path} className="rounded-xl bg-white/70 px-3 py-2 font-mono text-xs">
                {path}
              </li>
            ))}
            {(!payload || (payload.source_reports || []).length === 0) && (
              <li className="rounded-xl bg-white/70 px-3 py-2 text-xs text-gray-500">{copy.words.noSourceReport}</li>
            )}
          </ul>
          <div className="mt-4 rounded-xl bg-white/70 p-3 text-xs text-gray-600">
            {copy.words.eventsScanned}: <span className="font-bold">{asText(sources.events_scanned)}</span>
          </div>
        </article>
      </section>

      <section className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <article className="glass-card p-6">
          <p className="text-[10px] font-bold uppercase tracking-[0.25em] text-gray-500">{copy.sections.evidenceGates}</p>
          <div className="mt-4 grid grid-cols-1 gap-3">
            <MetricBar
              label={copy.metricLabels.evidenceCoverage}
              value={`${toNumber(requiredPresent, lang)}/${toNumber(requiredTotal, lang)}`}
              ratio={evidenceCoverageRatio}
              tone={requiredMissing && requiredMissing > 0 ? "warning" : "healthy"}
              hint={copy.words.discoveredRequiredEvidence}
            />
            <MetricBar
              label={copy.metricLabels.evidencePassRatio}
              value={`${toNumber(requiredPassed, lang)}/${toNumber(requiredTotal, lang)}`}
              ratio={evidencePassRatio}
              tone={requiredFailed && requiredFailed > 0 ? "critical" : "healthy"}
              right={
                <span>
                  {copy.words.failed} {toNumber(requiredFailed, lang)}
                </span>
              }
              hint={copy.words.requiredReportsPassed}
            />
          </div>
          <div className="mt-4 grid grid-cols-2 gap-2">
            <div className="rounded-xl bg-white/70 px-3 py-2 text-xs text-gray-700">
              {copy.words.missing}: <span className="font-bold">{toNumber(requiredMissing, lang)}</span>
            </div>
            <div className="rounded-xl bg-white/70 px-3 py-2 text-xs text-gray-700">
              {copy.words.failed}: <span className="font-bold">{toNumber(requiredFailed, lang)}</span>
            </div>
          </div>
        </article>

        <article className="glass-card p-6">
          <p className="text-[10px] font-bold uppercase tracking-[0.25em] text-gray-500">{copy.sections.requiredEvidence}</p>
          <ul className="mt-4 space-y-2 text-xs text-gray-700">
            {requiredReports.slice(0, 12).map((item) => {
              const status = String(item.status || "unknown");
              const gateLevel = String(item.gate_level || "soft");
              const state = toEvidenceState(status, gateLevel);
              return (
                <li key={String(item.id || "report")} className="rounded-xl bg-white/70 px-3 py-2">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-bold">{String(item.label || item.id || "unknown")}</span>
                    <span
                      className={`rounded-lg px-2 py-1 text-[10px] font-bold uppercase tracking-[0.16em] ${toneClassForState(state)}`}
                    >
                      {gateLabel(gateLevel, lang)}/{reportStatusLabel(status, lang)}
                    </span>
                  </div>
                  <p className="mt-1 font-mono text-[10px] text-gray-500">{String(item.path || "")}</p>
                </li>
              );
            })}
            {requiredReports.length === 0 ? (
              <li className="rounded-xl bg-white/70 px-3 py-2 text-xs text-gray-500">{copy.words.noEvidenceIndexed}</li>
            ) : null}
          </ul>
        </article>
      </section>

      <section className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <article className="glass-card p-6">
          <p className="text-[10px] font-bold uppercase tracking-[0.25em] text-gray-500">{copy.sections.leaseGuard}</p>
          <div className="mt-4 space-y-2 text-xs text-gray-700">
            <p className="rounded-xl bg-white/70 px-3 py-2">
              {copy.words.state}: {asText(runtimeLease.state).toUpperCase()}
            </p>
            <p className="rounded-xl bg-white/70 px-3 py-2">
              {copy.words.owner}: {asText(runtimeLease.owner_id, "none")}
            </p>
            <p className="rounded-xl bg-white/70 px-3 py-2">
              {copy.words.fencingEpoch}: {asText(runtimeLease.fencing_epoch)}
            </p>
            <p className="rounded-xl bg-white/70 px-3 py-2">
              {copy.words.secondsToExpiry}: {toNumber(runtimeLease.value, lang)}
            </p>
          </div>
        </article>

        <article className="glass-card p-6">
          <p className="text-[10px] font-bold uppercase tracking-[0.25em] text-gray-500">{copy.sections.brainstemGate}</p>
          <div className="mt-4 grid grid-cols-1 gap-2 text-xs text-gray-700 md:grid-cols-2">
            <p className="rounded-xl bg-white/70 px-3 py-2">
              {copy.words.state}: <span className="font-bold">{brainstemStatus.toUpperCase()}</span>
            </p>
            <p className="rounded-xl bg-white/70 px-3 py-2">
              {copy.words.reasonCode}: <span className="font-bold">{brainstemReasonCode}</span>
            </p>
            <p className="rounded-xl bg-white/70 px-3 py-2 md:col-span-2">
              {copy.words.reasonText}: <span className="font-bold">{brainstemReasonText}</span>
            </p>
            <p className="rounded-xl bg-white/70 px-3 py-2">
              {copy.words.heartbeatAge}:{" "}
              <span className="font-bold">
                {toNumber(brainstemHeartbeatAge, lang, 2)} {copy.words.seconds}
              </span>
            </p>
            <p className="rounded-xl bg-white/70 px-3 py-2">
              {copy.words.generatedAt}: <span className="font-bold">{brainstemGeneratedAtText}</span>
            </p>
            <p className="rounded-xl bg-white/70 px-3 py-2">
              {copy.words.staleWarning}:{" "}
              <span className="font-bold">
                {toNumber(brainstemStaleWarning, lang, 0)} {copy.words.seconds}
              </span>
            </p>
            <p className="rounded-xl bg-white/70 px-3 py-2">
              {copy.words.staleCritical}:{" "}
              <span className="font-bold">
                {toNumber(brainstemStaleCritical, lang, 0)} {copy.words.seconds}
              </span>
            </p>
            <p className="rounded-xl bg-white/70 px-3 py-2">
              {copy.words.healthy}: <span className="font-bold">{brainstemHealthyText}</span>
            </p>
            <p className="rounded-xl bg-white/70 px-3 py-2">
              {copy.words.serviceCount}: <span className="font-bold">{toNumber(brainstemServiceCount, lang)}</span>
            </p>
            <p className="rounded-xl bg-white/70 px-3 py-2">
              {copy.words.tick}: <span className="font-bold">{toNumber(brainstemTick, lang)}</span>
            </p>
            <p className="rounded-xl bg-white/70 px-3 py-2">
              {copy.words.pid}: <span className="font-bold">{toNumber(brainstemPid, lang)}</span>
            </p>
            <p className="rounded-xl bg-white/70 px-3 py-2 md:col-span-2">
              {copy.words.unhealthyServices}:{" "}
              <span className="font-bold">
                {brainstemUnhealthyServices.length > 0 ? brainstemUnhealthyServices.join(", ") : copy.words.none}
              </span>
            </p>
          </div>
          <div className="mt-4 rounded-xl bg-white/70 px-3 py-2 text-xs text-gray-700">
            <p>
              {copy.words.latestIncident}: <span className="font-bold">{latestIncidentAt}</span>
            </p>
            <p className="mt-1">
              <span className="font-bold">{latestBrainstemIncidentType}</span> · {latestBrainstemIncidentAt}
            </p>
            <p className="mt-1 text-gray-600">
              {brainstemIncidents.length > 0 ? latestBrainstemIncidentSummary : copy.words.noBrainstemIncident}
            </p>
          </div>
          <ul className="mt-3 space-y-2 text-xs text-gray-700">
            {brainstemIncidents.slice(0, 3).map((item) => (
              <li key={`${String(item.timestamp || "")}:${String(item.event_type || "")}`} className="rounded-xl bg-white/70 px-3 py-2">
                <p className="font-bold">
                  {String(item.event_type || "unknown")} · {String(item.severity || "unknown").toUpperCase()}
                </p>
                <p className="mt-1 text-gray-600">{String(item.summary || "")}</p>
              </li>
            ))}
            {brainstemIncidents.length === 0 ? (
              <li className="rounded-xl bg-white/70 px-3 py-2 text-gray-500">{copy.words.noIncidentSignal}</li>
            ) : null}
          </ul>
        </article>

        <article className="glass-card p-6">
          <p className="text-[10px] font-bold uppercase tracking-[0.25em] text-gray-500">{copy.sections.runtimeGovernanceConfig}</p>
          <div className="mt-4 space-y-2 text-xs text-gray-700">
            <p className="rounded-xl bg-white/70 px-3 py-2">
              {copy.words.auditLedgerFile}: <span className="font-mono font-bold">{emblaAuditLedgerFile}</span>
            </p>
            <div className="rounded-xl bg-white/70 px-3 py-2">
              <p className="font-bold">{copy.words.approvalRequiredScopes}</p>
              <p className="mt-1 font-mono text-[10px] text-gray-600">
                {emblaApprovalRequiredScopes.length > 0
                  ? emblaApprovalRequiredScopes.join(", ")
                  : copy.words.noApprovalScopesConfigured}
              </p>
            </div>
          </div>
        </article>

        <article className="glass-card p-6">
          <p className="text-[10px] font-bold uppercase tracking-[0.25em] text-gray-500">{copy.sections.summarySnapshot}</p>
          <pre className="mt-4 overflow-auto rounded-2xl bg-[#1c1c1e] p-4 text-xs text-gray-100">
            {JSON.stringify(payload?.data?.summary || { overall_status: "unknown" }, null, 2)}
          </pre>
        </article>
      </section>

      <section className="grid grid-cols-1 gap-4">
        <article className="glass-card p-6">
          <p className="text-[10px] font-bold uppercase tracking-[0.25em] text-gray-500">{copy.sections.recentEvidenceFiles}</p>
          <div className="mt-4 grid grid-cols-1 gap-2 md:grid-cols-2">
            {recentReports.slice(0, 12).map((item) => (
              <div key={String(item.path || item.name || "report")} className="rounded-xl bg-white/70 px-3 py-2 text-xs text-gray-700">
                <p className="font-bold">{String(item.name || "unknown")}</p>
                <p className="mt-1 font-mono text-[10px] text-gray-500">{formatIsoDateTime(item.modified_at, lang)}</p>
              </div>
            ))}
            {recentReports.length === 0 ? (
              <div className="rounded-xl bg-white/70 px-3 py-2 text-xs text-gray-500">{copy.words.noRecentEvidenceFile}</div>
            ) : null}
          </div>
        </article>
      </section>
    </div>
  );
}
