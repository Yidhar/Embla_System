import {
  EmptyState,
  GlassPanel,
  MetricCard,
  MetricGrid,
  PageHeader,
  StatusBadge
} from "@/components/dashboard-ui";
import { getAgentHierarchy } from "@/lib/api/ops";
import { createTranslator } from "@/lib/i18n";
import { getRequestLocale } from "@/lib/request-locale";
import { Severity } from "@/lib/types";

interface AgentSession {
  session_id: string;
  parent_id?: string;
  role?: string;
  status?: string;
  task?: string;
}

export default async function AgentHierarchyPage() {
  const locale = await getRequestLocale();
  const t = createTranslator(locale);
  const hierarchy = await getAgentHierarchy();

  const rawSessions: AgentSession[] = (
    Array.isArray(hierarchy.data.sessions) ? hierarchy.data.sessions : []
  ).map((s: Record<string, unknown>) => ({
    session_id: String(s.session_id ?? ""),
    parent_id: s.parent_id ? String(s.parent_id) : undefined,
    role: s.role ? String(s.role) : undefined,
    status: s.status ? String(s.status) : undefined,
    task: s.task ? String(s.task) : undefined
  }));

  const totalSessions = rawSessions.length;

  const roleCounts = new Map<string, number>();
  for (const session of rawSessions) {
    const role = session.role ?? "unknown";
    roleCounts.set(role, (roleCounts.get(role) ?? 0) + 1);
  }
  const roleEntries = [...roleCounts.entries()].sort((a, b) => b[1] - a[1]);
  const roleDistributionLabel = roleEntries.map(([role, count]) => `${role}: ${count}`).join(", ") || "—";

  const sessionsByRole = new Map<string, AgentSession[]>();
  for (const session of rawSessions) {
    const role = session.role ?? "unknown";
    const list = sessionsByRole.get(role) ?? [];
    list.push(session);
    sessionsByRole.set(role, list);
  }

  function statusToSeverity(status?: string): Severity {
    if (!status) return "unknown";
    const lower = status.toLowerCase();
    if (lower === "active" || lower === "running" || lower === "ok") return "ok";
    if (lower === "warning" || lower === "stale") return "warning";
    if (lower === "critical" || lower === "error" || lower === "failed") return "critical";
    return "unknown";
  }

  function truncateId(id: string, length = 12): string {
    return id.length > length ? `${id.slice(0, length)}...` : id;
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={t("agentHierarchy.header.eyebrow")}
        title={t("agentHierarchy.header.title")}
        description={t("agentHierarchy.header.description")}
        severity={hierarchy.severity ?? "unknown"}
        mode={hierarchy.meta?.mode}
        locale={locale}
      />

      <MetricGrid>
        <MetricCard
          title={t("agentHierarchy.metrics.totalSessions.title")}
          value={String(totalSessions)}
          description={t("agentHierarchy.metrics.totalSessions.description")}
          severity={totalSessions > 0 ? "ok" : "unknown"}
          locale={locale}
        />
        <MetricCard
          title={t("agentHierarchy.metrics.roleDistribution.title")}
          value={String(roleEntries.length)}
          description={t("agentHierarchy.metrics.roleDistribution.description")}
          severity={roleEntries.length > 0 ? "ok" : "unknown"}
          footnote={roleDistributionLabel}
          locale={locale}
        />
      </MetricGrid>

      {totalSessions === 0 ? (
        <GlassPanel title={t("agentHierarchy.labels.noSessions")}>
          <EmptyState
            title={t("agentHierarchy.labels.noSessions")}
            description={t("agentHierarchy.labels.noSessionsDescription")}
          />
        </GlassPanel>
      ) : (
        <div className="grid gap-6 md:grid-cols-2">
          {[...sessionsByRole.entries()].map(([role, sessions]) => (
            <GlassPanel
              key={role}
              eyebrow={t(`agentHierarchy.roles.${role}`, { 0: role })}
              title={`${role} (${sessions.length})`}
            >
              <div className="space-y-3">
                {sessions.map((session) => (
                  <div
                    key={session.session_id}
                    className="rounded-[16px] border border-white/70 bg-white/70 px-4 py-3"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="min-w-0">
                        <p className="text-sm font-semibold text-slate-900">
                          {t("agentHierarchy.labels.sessionId")}: {truncateId(session.session_id)}
                        </p>
                        <p className="mt-1 text-xs text-slate-500">
                          {session.parent_id
                            ? `${t("agentHierarchy.labels.parent")}: ${truncateId(session.parent_id)}`
                            : t("agentHierarchy.labels.noParent")}
                        </p>
                      </div>
                      <StatusBadge
                        severity={statusToSeverity(session.status)}
                        label={session.status}
                        locale={locale}
                      />
                    </div>
                    <p className="mt-2 text-sm leading-6 text-slate-500">
                      {session.task ?? t("agentHierarchy.labels.noTask")}
                    </p>
                  </div>
                ))}
              </div>
            </GlassPanel>
          ))}
        </div>
      )}
    </div>
  );
}
