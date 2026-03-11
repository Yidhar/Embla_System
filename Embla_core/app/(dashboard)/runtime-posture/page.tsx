import { Cable, GitBranch, ListChecks, Radar, Sparkles } from "lucide-react";

import {
  BarList,
  GlassPanel,
  GraphCanvas,
  MetricCard,
  MetricGrid,
  PageHeader,
  RatioBadge,
  SourceList,
  TimelineList
} from "@/components/dashboard-ui";
import {
  getEvidence,
  getIncidents,
  getMcpFabric,
  getMemoryGraph,
  getMetric,
  getRuntimePosture,
  getWorkflowEvents
} from "@/lib/api/ops";
import { formatDurationSeconds, formatMetricValue, formatPercent, formatTimestamp } from "@/lib/format";
import { createTranslator, humanizeEnum } from "@/lib/i18n";
import { getRequestLocale } from "@/lib/request-locale";
import { Severity } from "@/lib/types";
import {
  deriveAgentFleet,
  deriveMcpBreakdown,
  deriveOpsTaskCount,
  deriveRecallReadiness,
  deriveServiceCountLabel,
  numberValue
} from "@/lib/view-models";

export default async function RuntimePosturePage() {
  const locale = await getRequestLocale();
  const t = createTranslator(locale);
  const [runtime, workflow, mcp, memory, incidents, evidence] = await Promise.all([
    getRuntimePosture(),
    getWorkflowEvents(),
    getMcpFabric(),
    getMemoryGraph(),
    getIncidents(),
    getEvidence()
  ]);

  const metrics = runtime.data.metrics ?? {};
  const agentFleet = deriveAgentFleet(runtime.data);
  const recall = deriveRecallReadiness(memory.data, locale);
  const mcpBreakdown = deriveMcpBreakdown(mcp.data);
  const ongoingTaskCount = deriveOpsTaskCount(workflow.data, memory.data);
  const evidencePassed = numberValue(evidence.data.summary.required_passed);
  const evidenceTotal = numberValue(evidence.data.summary.required_total);

  const primaryMetrics = [
    {
      title: t("runtimePosture.metrics.rollout.title"),
      value: formatMetricValue(getMetric(metrics, "runtime_rollout").value, getMetric(metrics, "runtime_rollout").unit, locale),
      description: t("runtimePosture.metrics.rollout.description", {
        percent: numberValue(getMetric(metrics, "runtime_rollout").configured_rollout_percent)
      }),
      severity: getMetric(metrics, "runtime_rollout").status ?? "unknown"
    },
    {
      title: t("runtimePosture.metrics.failOpen.title"),
      value: formatMetricValue(getMetric(metrics, "runtime_fail_open").value, getMetric(metrics, "runtime_fail_open").unit, locale),
      description: t("runtimePosture.metrics.failOpen.description", {
        budget: formatPercent(numberValue(getMetric(metrics, "runtime_fail_open").budget_remaining_ratio), 0),
        blocked: formatPercent(numberValue(getMetric(metrics, "runtime_fail_open").fail_open_blocked_ratio), 0)
      }),
      severity: getMetric(metrics, "runtime_fail_open").status ?? "unknown"
    },
    {
      title: t("runtimePosture.metrics.lease.title"),
      value: formatMetricValue(getMetric(metrics, "runtime_lease").value, getMetric(metrics, "runtime_lease").unit, locale),
      description: t("runtimePosture.metrics.lease.description", {
        state: humanizeEnum(locale, "leaseState", getMetric(metrics, "runtime_lease").state ?? "unknown"),
        epoch: numberValue(getMetric(metrics, "runtime_lease").fencing_epoch)
      }),
      severity: getMetric(metrics, "runtime_lease").status ?? "unknown"
    },
    {
      title: t("runtimePosture.metrics.queue.title"),
      value: formatMetricValue(getMetric(metrics, "queue_depth").value, getMetric(metrics, "queue_depth").unit, locale),
      description: t("runtimePosture.metrics.queue.description", {
        age: formatDurationSeconds(numberValue(getMetric(metrics, "queue_depth").oldest_pending_age_seconds, 0))
      }),
      severity: getMetric(metrics, "queue_depth").status ?? "unknown"
    },
    {
      title: t("runtimePosture.metrics.lock.title"),
      value: humanizeEnum(locale, "lockState", getMetric(metrics, "lock_status").state ?? "unknown"),
      description: t("runtimePosture.metrics.lock.description", {
        epoch: numberValue(getMetric(metrics, "lock_status").fencing_epoch)
      }),
      severity: getMetric(metrics, "lock_status").status ?? "unknown"
    },
    {
      title: t("runtimePosture.metrics.disk.title"),
      value: formatMetricValue(getMetric(metrics, "disk_watermark_ratio").value, getMetric(metrics, "disk_watermark_ratio").unit, locale),
      description: t("runtimePosture.metrics.disk.description", {
        freeGb: numberValue(getMetric(metrics, "disk_watermark_ratio").filesystem_free_gb, 0).toFixed(0)
      }),
      severity: getMetric(metrics, "disk_watermark_ratio").status ?? "unknown"
    }
  ];

  const timelineItems: Array<{ title: string; detail?: string; timestamp?: string; severity?: Severity }> = [
    ...workflow.data.recent_critical_events.map((item) => ({
      title: item.event_type,
      detail: item.payload_excerpt,
      timestamp: item.timestamp,
      severity: (item.event_type === "LeaseLost" ? "critical" : "warning") as Severity
    })),
    ...incidents.data.incidents.slice(0, 2).map((incident) => ({
      title: incident.summary,
      detail: [incident.payload_excerpt, incident.report_path].filter(Boolean).join(" · "),
      timestamp: incident.timestamp,
      severity: incident.severity as Severity
    }))
  ].slice(0, 6);

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={t("runtimePosture.header.eyebrow")}
        title={t("runtimePosture.header.title")}
        description={t("runtimePosture.header.description")}
        severity={runtime.severity}
        mode={runtime.meta?.mode}
        locale={locale}
      />

      <MetricGrid>
        {primaryMetrics.map((metric) => (
          <MetricCard key={metric.title} {...metric} locale={locale} />
        ))}
      </MetricGrid>

      <div className="grid gap-6 xl:grid-cols-[1.15fr_0.85fr]">
        <GlassPanel
          eyebrow={t("runtimePosture.sections.agentFleet.eyebrow")}
          title={t("runtimePosture.sections.agentFleet.title")}
          description={t("runtimePosture.sections.agentFleet.description")}
          actions={<span className="rounded-full border border-white/70 bg-white/75 px-3 py-1 text-xs text-slate-500">{t("common.label.updatedAt", { timestamp: formatTimestamp(runtime.generated_at, locale) })}</span>}
        >
          <div className="grid gap-4 lg:grid-cols-[1fr_1fr]">
            <div className="grid gap-4 sm:grid-cols-2">
              <MetricCard
                title={t("runtimePosture.sections.agentFleet.observedAgents")}
                value={String(agentFleet.totalObservedAgents)}
                description={t("runtimePosture.sections.agentFleet.totalObserved")}
                severity={runtime.severity}
                footnote={`${t("runtimePosture.sections.agentFleet.latestRole")} · ${agentFleet.latestRole}`}
                locale={locale}
              />
              <MetricCard
                title={t("runtimePosture.sections.agentFleet.ongoingTasks")}
                value={String(ongoingTaskCount)}
                description={t("runtimePosture.sections.agentFleet.ongoingTasksFootnote")}
                severity={workflow.severity}
                footnote={`${t("runtimePosture.sections.agentFleet.deferredCount")} · ${agentFleet.deferredCount}`}
                locale={locale}
              />
              <div className="soft-inset p-4 sm:col-span-2">
                <div className="flex items-center gap-2 text-slate-500">
                  <Sparkles className="h-4 w-4" />
                  <span className="text-sm">{t("runtimePosture.sections.agentFleet.toolStatus")}</span>
                </div>
                <p className="mt-3 text-base font-semibold text-slate-900">{workflow.data.tool_status?.visible ? workflow.data.tool_status.message : t("runtimePosture.sections.agentFleet.noToolStatus")}</p>
              </div>
            </div>

            <div className="rounded-[24px] border border-white/70 bg-white/70 p-4">
              <p className="eyebrow">{t("runtimePosture.sections.agentFleet.roleBreakdown")}</p>
              <div className="mt-4 flex flex-wrap gap-2">
                {agentFleet.roleCounts.length > 0 ? (
                  agentFleet.roleCounts.map((item) => (
                    <span key={item.role} className="rounded-full border border-white/70 bg-white px-3 py-2 text-sm text-slate-700">
                      {item.role} · {item.count}
                    </span>
                  ))
                ) : (
                  <span className="text-sm text-slate-400">{t("runtimePosture.sections.agentFleet.noRoleBreakdown")}</span>
                )}
              </div>
              <div className="mt-6 grid gap-3 sm:grid-cols-3">
                <RatioBadge value={numberValue(getMetric(metrics, "shell_to_core_dispatch_rate").value)} label={t("runtimePosture.sections.agentFleet.shellToCore")} />
                <RatioBadge value={numberValue(getMetric(metrics, "shell_readonly_hit_rate").value)} label={t("runtimePosture.sections.agentFleet.readonlyHit")} />
                <RatioBadge value={numberValue(getMetric(metrics, "execution_bridge_rejection_ratio").value)} label={t("runtimePosture.sections.agentFleet.bridgeReject")} />
              </div>
            </div>
          </div>
          <SourceList reports={runtime.source_reports} endpoints={runtime.source_endpoints} />
        </GlassPanel>

        <GlassPanel
          eyebrow={t("runtimePosture.sections.memoryReadiness.eyebrow")}
          title={t("runtimePosture.sections.memoryReadiness.title")}
          description={t("runtimePosture.sections.memoryReadiness.description")}
        >
          <div className="grid gap-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <MetricCard
                title={t("runtimePosture.sections.memoryReadiness.recallReadiness")}
                value={formatPercent(recall.score, 0)}
                description={recall.description}
                severity={recall.severity}
                footnote={recall.label}
                locale={locale}
              />
              <MetricCard
                title={t("runtimePosture.sections.memoryReadiness.knowledgeGraph")}
                value={String(numberValue(memory.data.summary.total_quintuples))}
                description={t("runtimePosture.sections.memoryReadiness.knowledgeGraphDescription", {
                  activeTasks: numberValue(memory.data.summary.active_tasks),
                  indexState: String(memory.data.summary.vector_index_state ?? t("common.label.unknown"))
                })}
                severity={memory.severity}
                footnote={t("runtimePosture.sections.memoryReadiness.knowledgeGraphFootnote", {
                  sampleSize: numberValue(memory.data.summary.graph_sample_size)
                })}
                locale={locale}
              />
            </div>
            <GraphCanvas edges={memory.data.graph_sample} compact locale={locale} />
          </div>
          <SourceList reports={memory.source_reports} endpoints={memory.source_endpoints} />
        </GlassPanel>
      </div>

      <div className="grid gap-6 xl:grid-cols-[1fr_1fr]">
        <GlassPanel
          eyebrow={t("runtimePosture.sections.toolSurface.eyebrow")}
          title={t("runtimePosture.sections.toolSurface.title")}
          description={t("runtimePosture.sections.toolSurface.description")}
        >
          <div className="grid gap-4 sm:grid-cols-3">
            <div className="soft-inset p-4">
              <div className="flex items-center gap-2 text-slate-500">
                <Cable className="h-4 w-4" />
                <span className="text-sm">{t("runtimePosture.sections.toolSurface.mcpServices")}</span>
              </div>
              <p className="mt-3 text-2xl font-extrabold text-slate-900">{deriveServiceCountLabel(mcp.data, locale)}</p>
            </div>
            <div className="soft-inset p-4">
              <div className="flex items-center gap-2 text-slate-500">
                <GitBranch className="h-4 w-4" />
                <span className="text-sm">{t("runtimePosture.sections.toolSurface.skills")}</span>
              </div>
              <p className="mt-3 text-2xl font-extrabold text-slate-900">{numberValue(mcp.data.skill_inventory?.total_skills)}</p>
              <p className="mt-2 text-sm text-slate-500">{t("runtimePosture.sections.toolSurface.skillsDescription")}</p>
            </div>
            <div className="soft-inset p-4">
              <div className="flex items-center gap-2 text-slate-500">
                <ListChecks className="h-4 w-4" />
                <span className="text-sm">{t("runtimePosture.sections.toolSurface.evidenceReadiness")}</span>
              </div>
              <p className="mt-3 text-2xl font-extrabold text-slate-900">{evidencePassed}/{evidenceTotal}</p>
              <p className="mt-2 text-sm text-slate-500">{t("runtimePosture.sections.toolSurface.evidenceReadinessDescription")}</p>
            </div>
          </div>

          <div className="mt-6 grid gap-6 lg:grid-cols-2">
            <div>
              <p className="mb-3 text-sm font-semibold text-slate-700">{t("runtimePosture.sections.toolSurface.sourceBreakdown")}</p>
              <BarList items={mcpBreakdown.bySource} />
            </div>
            <div>
              <p className="mb-3 text-sm font-semibold text-slate-700">{t("runtimePosture.sections.toolSurface.statusBreakdown")}</p>
              <BarList
                items={mcpBreakdown.byStatus.map((item) => ({
                  label: humanizeEnum(locale, "mcpStatus", item.label),
                  value: item.value
                }))}
              />
            </div>
          </div>
          <SourceList reports={mcp.source_reports} endpoints={mcp.source_endpoints} />
        </GlassPanel>

        <GlassPanel
          eyebrow={t("runtimePosture.sections.eventsAndRisks.eyebrow")}
          title={t("runtimePosture.sections.eventsAndRisks.title")}
          description={t("runtimePosture.sections.eventsAndRisks.description")}
        >
          <TimelineList items={timelineItems} locale={locale} />
          <SourceList reports={workflow.source_reports} endpoints={workflow.source_endpoints} />
        </GlassPanel>
      </div>
    </div>
  );
}
