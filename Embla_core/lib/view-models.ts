import { clamp } from "@/lib/format";
import { AppLocale, DEFAULT_LOCALE, translate } from "@/lib/i18n";
import {
  McpFabricData,
  MemoryGraphData,
  RuntimePostureData,
  Severity,
  WorkflowEventData
} from "@/lib/types";

export function numberValue(input: unknown, fallback = 0) {
  const next = Number(input);
  return Number.isFinite(next) ? next : fallback;
}

export function deriveRecallReadiness(memory: MemoryGraphData, locale: AppLocale = DEFAULT_LOCALE) {
  const totalQuintuples = numberValue(memory.summary.total_quintuples);
  const runningTasks = numberValue(memory.summary.running_tasks);
  const failedTasks = numberValue(memory.summary.failed_tasks);
  const ready = Boolean(memory.summary.vector_index_ready);

  const score = clamp(
    (ready ? 0.48 : 0.18) +
      Math.min(totalQuintuples / 2400, 0.36) +
      Math.max(0, 0.18 - Math.min((runningTasks + failedTasks * 2) / 30, 0.18))
  );

  let severity: Severity = "ok";
  if (!ready) {
    severity = "warning";
  }
  if (failedTasks > 0) {
    severity = "warning";
  }
  if (!ready && totalQuintuples <= 0) {
    severity = "unknown";
  }

  return {
    score,
    severity,
    label: ready ? translate(locale, "viewModels.recall.ready") : translate(locale, "viewModels.recall.warming"),
    description: translate(locale, "viewModels.recall.description")
  };
}

export function deriveAgentFleet(runtime: RuntimePostureData) {
  const coreChild = (runtime.core_child_spawn_deferred ?? {}) as Record<string, unknown>;
  const roleCountsRaw = (coreChild.role_counts ?? {}) as Record<string, unknown>;
  const roleCounts = Object.entries(roleCountsRaw)
    .map(([role, count]) => ({ role, count: numberValue(count) }))
    .filter((item) => item.count > 0)
    .sort((left, right) => right.count - left.count);

  const totalObservedAgents = roleCounts.reduce((sum, item) => sum + item.count, 0);

  return {
    totalObservedAgents,
    roleCounts,
    latestRole: String(coreChild.latest_role ?? "unknown"),
    deferredCount: numberValue(coreChild.deferred_count),
    coreExecutionSessionCount: numberValue(coreChild.core_execution_session_count)
  };
}

export function deriveMcpBreakdown(mcp: McpFabricData) {
  const bySource = new Map<string, number>();
  const byStatus = new Map<string, number>();

  for (const service of mcp.services) {
    bySource.set(service.source, (bySource.get(service.source) ?? 0) + 1);
    const status = service.status_label ?? (service.available === true ? "online" : service.available === false ? "offline" : "unknown");
    byStatus.set(status, (byStatus.get(status) ?? 0) + 1);
  }

  return {
    bySource: [...bySource.entries()].map(([label, value]) => ({ label, value })),
    byStatus: [...byStatus.entries()].map(([label, value]) => ({ label, value }))
  };
}

export function deriveOpsTaskCount(workflow: WorkflowEventData, memory: MemoryGraphData) {
  return numberValue(workflow.summary.outbox_pending) + numberValue(memory.summary.active_tasks);
}

export function deriveServiceCountLabel(mcp: McpFabricData, locale: AppLocale = DEFAULT_LOCALE) {
  const total = numberValue(mcp.summary.total_services);
  const available = numberValue(mcp.summary.available_services);

  if (available > 0) {
    return translate(locale, "viewModels.services.online", { available, total });
  }

  return translate(locale, "viewModels.services.discovered", { total });
}
