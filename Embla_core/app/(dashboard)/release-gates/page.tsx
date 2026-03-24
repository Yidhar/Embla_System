import {
  GlassPanel,
  MetricCard,
  MetricGrid,
  PageHeader,
  StatusBadge
} from "@/components/dashboard-ui";
import { getReleaseGates } from "@/lib/api/ops";
import { createTranslator } from "@/lib/i18n";
import { getRequestLocale } from "@/lib/request-locale";
import { Severity } from "@/lib/types";

const GATE_KEYS = ["read_only", "write_repo", "deploy", "secrets"] as const;

export default async function ReleaseGatesPage() {
  const locale = await getRequestLocale();
  const t = createTranslator(locale);
  const releaseGates = await getReleaseGates();

  const gates: Array<{
    key: string;
    label: string;
    passed: boolean;
    checks: Array<{ name: string; passed: boolean }>;
  }> = [];

  const rawGates = Array.isArray(releaseGates.data.gates)
    ? releaseGates.data.gates
    : [];

  for (const gateKey of GATE_KEYS) {
    const match = rawGates.find(
      (g: Record<string, unknown>) =>
        String(g.name ?? g.gate ?? g.level ?? "").toLowerCase() === gateKey
    );
    if (match) {
      const rawChecks = Array.isArray(match.checks) ? match.checks : [];
      gates.push({
        key: gateKey,
        label: t(`releaseGates.gates.${gateKey}`),
        passed: Boolean(match.passed),
        checks: rawChecks.map((c: Record<string, unknown>) => ({
          name: String(c.name ?? c.label ?? "check"),
          passed: Boolean(c.passed)
        }))
      });
    } else {
      gates.push({
        key: gateKey,
        label: t(`releaseGates.gates.${gateKey}`),
        passed: false,
        checks: []
      });
    }
  }

  const passedCount = gates.filter((g) => g.passed).length;
  const failedCount = gates.filter((g) => !g.passed).length;
  const totalCount = gates.length;
  const pendingCount = gates.filter((g) => !g.passed && g.checks.length === 0).length;

  const overallSeverity: Severity =
    failedCount === 0 ? "ok" : failedCount <= 1 ? "warning" : "critical";

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={t("releaseGates.header.eyebrow")}
        title={t("releaseGates.header.title")}
        description={t("releaseGates.header.description")}
        severity={releaseGates.severity ?? overallSeverity}
        mode={releaseGates.meta?.mode}
        locale={locale}
      />

      <MetricGrid>
        <MetricCard
          title={t("releaseGates.metrics.totalGates.title")}
          value={String(totalCount)}
          description={t("releaseGates.metrics.totalGates.description")}
          severity="unknown"
          locale={locale}
        />
        <MetricCard
          title={t("releaseGates.metrics.passedGates.title")}
          value={String(passedCount)}
          description={t("releaseGates.metrics.passedGates.description")}
          severity={passedCount === totalCount ? "ok" : "warning"}
          locale={locale}
        />
        <MetricCard
          title={t("releaseGates.metrics.failedGates.title")}
          value={String(failedCount)}
          description={t("releaseGates.metrics.failedGates.description")}
          severity={failedCount === 0 ? "ok" : "critical"}
          locale={locale}
        />
        <MetricCard
          title={t("releaseGates.metrics.pendingGates.title")}
          value={String(pendingCount)}
          description={t("releaseGates.metrics.pendingGates.description")}
          severity={pendingCount === 0 ? "ok" : "warning"}
          locale={locale}
        />
      </MetricGrid>

      <div className="grid gap-6 md:grid-cols-2">
        {gates.map((gate) => (
          <GlassPanel
            key={gate.key}
            eyebrow={gate.label}
            title={gate.label}
            description={gate.passed ? t("releaseGates.labels.passed") : t("releaseGates.labels.failed")}
            actions={
              <StatusBadge
                severity={gate.passed ? "ok" : "critical"}
                label={gate.passed ? t("releaseGates.labels.passed") : t("releaseGates.labels.failed")}
                locale={locale}
              />
            }
          >
            <div className="space-y-3">
              <p className="text-sm font-semibold text-slate-700">
                {t("releaseGates.labels.checks")}
              </p>
              {gate.checks.length > 0 ? (
                <div className="space-y-2">
                  {gate.checks.map((check, index) => (
                    <div
                      key={`${gate.key}-${check.name}-${index}`}
                      className="flex items-center justify-between rounded-[16px] border border-white/70 bg-white/70 px-4 py-2"
                    >
                      <span className="text-sm text-slate-700">{check.name}</span>
                      <StatusBadge
                        severity={check.passed ? "ok" : "critical"}
                        locale={locale}
                      />
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-slate-400">
                  {t("releaseGates.labels.noChecks")}
                </p>
              )}
            </div>
          </GlassPanel>
        ))}
      </div>
    </div>
  );
}
