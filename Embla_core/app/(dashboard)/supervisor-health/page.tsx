import {
  EmptyState,
  GlassPanel,
  MetricCard,
  MetricGrid,
  PageHeader,
  StatusBadge
} from "@/components/dashboard-ui";
import { getSupervisorHealth } from "@/lib/api/ops";
import { createTranslator } from "@/lib/i18n";
import { getRequestLocale } from "@/lib/request-locale";
import { Severity } from "@/lib/types";

const SERVICE_KEYS = ["brainstem", "process_guard", "watchdog", "killswitch"] as const;

interface ServiceHealth {
  key: string;
  label: string;
  status: string;
  severity: Severity;
  metrics: Record<string, string | number>;
}

export default async function SupervisorHealthPage() {
  const locale = await getRequestLocale();
  const t = createTranslator(locale);
  const health = await getSupervisorHealth();

  const rawServices: Record<string, unknown> =
    health.data.services && typeof health.data.services === "object"
      ? (health.data.services as Record<string, unknown>)
      : {};

  const services: ServiceHealth[] = SERVICE_KEYS.map((key) => {
    const raw = rawServices[key];
    const data =
      raw && typeof raw === "object" && !Array.isArray(raw)
        ? (raw as Record<string, unknown>)
        : {};

    const status = String(data.status ?? "unknown");
    let severity: Severity = "unknown";
    const lower = status.toLowerCase();
    if (lower === "healthy" || lower === "ok" || lower === "active" || lower === "running") {
      severity = "ok";
    } else if (lower === "warning" || lower === "degraded") {
      severity = "warning";
    } else if (lower === "critical" || lower === "error" || lower === "failed" || lower === "stopped") {
      severity = "critical";
    }

    const metrics: Record<string, string | number> = {};
    for (const [mk, mv] of Object.entries(data)) {
      if (mk === "status" || mk === "severity") continue;
      if (typeof mv === "string" || typeof mv === "number") {
        metrics[mk] = mv;
      }
    }

    return {
      key,
      label: t(`supervisorHealth.services.${key}`),
      status,
      severity,
      metrics
    };
  });

  const healthyCount = services.filter((s) => s.severity === "ok").length;
  const totalCount = services.length;

  const overallSeverity: Severity =
    healthyCount === totalCount
      ? "ok"
      : healthyCount >= totalCount / 2
        ? "warning"
        : "critical";

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={t("supervisorHealth.header.eyebrow")}
        title={t("supervisorHealth.header.title")}
        description={t("supervisorHealth.header.description")}
        severity={health.severity ?? overallSeverity}
        mode={health.meta?.mode}
        locale={locale}
      />

      <MetricGrid>
        <MetricCard
          title={t("supervisorHealth.metrics.healthyServices.title")}
          value={`${healthyCount}/${totalCount}`}
          description={t("supervisorHealth.metrics.healthyServices.description")}
          severity={overallSeverity}
          locale={locale}
        />
        <MetricCard
          title={t("supervisorHealth.metrics.totalServices.title")}
          value={String(totalCount)}
          description={t("supervisorHealth.metrics.totalServices.description")}
          severity="unknown"
          locale={locale}
        />
      </MetricGrid>

      {totalCount === 0 ? (
        <GlassPanel title={t("supervisorHealth.labels.noData")}>
          <EmptyState
            title={t("supervisorHealth.labels.noData")}
            description={t("supervisorHealth.labels.noDataDescription")}
          />
        </GlassPanel>
      ) : (
        <div className="grid gap-6 md:grid-cols-2">
          {services.map((service) => (
            <GlassPanel
              key={service.key}
              eyebrow={service.label}
              title={service.label}
              actions={
                <StatusBadge
                  severity={service.severity}
                  label={service.status}
                  locale={locale}
                />
              }
            >
              <div className="space-y-3">
                <div className="flex items-center gap-4">
                  <div className="rounded-[16px] border border-white/70 bg-white/70 px-4 py-2">
                    <p className="text-xs text-slate-500">{t("supervisorHealth.labels.status")}</p>
                    <p className="text-sm font-semibold text-slate-900">{service.status}</p>
                  </div>
                  <div className="rounded-[16px] border border-white/70 bg-white/70 px-4 py-2">
                    <p className="text-xs text-slate-500">{t("supervisorHealth.labels.severity")}</p>
                    <StatusBadge severity={service.severity} locale={locale} />
                  </div>
                </div>

                {Object.keys(service.metrics).length > 0 ? (
                  <div className="grid gap-2 sm:grid-cols-2">
                    {Object.entries(service.metrics).map(([metricKey, metricValue]) => (
                      <div
                        key={`${service.key}-${metricKey}`}
                        className="rounded-[16px] border border-white/70 bg-white/70 px-4 py-2"
                      >
                        <p className="text-xs text-slate-500">{metricKey}</p>
                        <p className="text-sm font-semibold text-slate-900">{String(metricValue)}</p>
                      </div>
                    ))}
                  </div>
                ) : null}
              </div>
            </GlassPanel>
          ))}
        </div>
      )}
    </div>
  );
}
