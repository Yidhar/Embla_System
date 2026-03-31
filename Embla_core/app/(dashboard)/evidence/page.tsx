import { GlassPanel, MetricCard, MetricGrid, PageHeader, SourceList } from "@/components/dashboard-ui";
import { getEvidence } from "@/lib/api/ops";
import { formatNumber } from "@/lib/format";
import { createTranslator } from "@/lib/i18n";
import { getRequestLocale } from "@/lib/request-locale";
import { numberValue } from "@/lib/view-models";

export default async function EvidencePage() {
  const locale = await getRequestLocale();
  const t = createTranslator(locale);
  const evidence = await getEvidence();

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={t("evidence.header.eyebrow")}
        title={t("evidence.header.title")}
        description={t("evidence.header.description")}
        severity={evidence.severity}
        mode={evidence.meta?.mode}
        locale={locale}
      />

      <MetricGrid>
        <MetricCard title={t("evidence.metrics.requiredTotal.title")} value={formatNumber(numberValue(evidence.data.summary.required_total), 0, locale)} description={t("evidence.metrics.requiredTotal.description")} severity={evidence.severity} locale={locale} />
        <MetricCard title={t("evidence.metrics.requiredPassed.title")} value={formatNumber(numberValue(evidence.data.summary.required_passed), 0, locale)} description={t("evidence.metrics.requiredPassed.description")} severity="ok" locale={locale} />
        <MetricCard title={t("evidence.metrics.hardMissing.title")} value={formatNumber(numberValue(evidence.data.summary.hard_missing), 0, locale)} description={t("evidence.metrics.hardMissing.description")} severity={numberValue(evidence.data.summary.hard_missing) > 0 ? "critical" : "ok"} locale={locale} />
        <MetricCard title={t("evidence.metrics.softMissing.title")} value={formatNumber(numberValue(evidence.data.summary.soft_missing), 0, locale)} description={t("evidence.metrics.softMissing.description")} severity={numberValue(evidence.data.summary.soft_missing) > 0 ? "warning" : "ok"} locale={locale} />
      </MetricGrid>

      <GlassPanel eyebrow={t("evidence.reportIndex.eyebrow")} title={t("evidence.reportIndex.title")} description={t("evidence.reportIndex.description")}>
        <div className="space-y-3">
          {evidence.data.required_reports.map((report) => (
            <div key={report.id} className="grid gap-3 rounded-[24px] border border-white/70 bg-white/75 p-4 md:grid-cols-[minmax(0,1fr)_120px_180px] md:items-center">
              <div>
                <p className="text-sm font-semibold text-slate-900">{report.label}</p>
                <p className="mt-1 break-all text-sm leading-6 text-slate-500">{report.path}</p>
              </div>
              <div className="text-sm text-slate-500">{report.gate_level}</div>
              <div className="text-sm font-semibold text-slate-900">{report.status}</div>
            </div>
          ))}
        </div>
        <SourceList reports={evidence.source_reports} endpoints={evidence.source_endpoints} />
      </GlassPanel>
    </div>
  );
}
