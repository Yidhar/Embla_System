import {
  GlassPanel,
  MetricCard,
  MetricGrid,
  PageHeader
} from "@/components/dashboard-ui";
import { getMemoryOverview } from "@/lib/api/ops";
import { formatNumber } from "@/lib/format";
import { createTranslator } from "@/lib/i18n";
import { getRequestLocale } from "@/lib/request-locale";

export default async function MemoryOverviewPage() {
  const locale = await getRequestLocale();
  const t = createTranslator(locale);
  const data = await getMemoryOverview();

  const l1Total = data.l1.total ?? 0;
  const l2Total = data.l2.total ?? data.l2.indexed ?? data.grag_quintuples ?? 0;
  const l3Total = data.l3.total ?? 0;

  const overallSeverity = l1Total > 0 || l2Total > 0 || l3Total > 0
    ? "ok"
    : "unknown";

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={t("memoryOverview.header.eyebrow")}
        title={t("memoryOverview.header.title")}
        description={t("memoryOverview.header.description")}
        severity={overallSeverity}
        locale={locale}
      />

      <MetricGrid>
        <MetricCard
          title={t("memoryOverview.metrics.l1Total.title")}
          value={formatNumber(l1Total, 0, locale)}
          description={t("memoryOverview.metrics.l1Total.description")}
          severity={l1Total > 0 ? "ok" : "unknown"}
          locale={locale}
        />
        <MetricCard
          title={t("memoryOverview.metrics.l2Indexed.title")}
          value={formatNumber(l2Total, 0, locale)}
          description={t("memoryOverview.metrics.l2Indexed.description")}
          severity={l2Total > 0 ? "ok" : "unknown"}
          locale={locale}
        />
        <MetricCard
          title={t("memoryOverview.metrics.l3Vectors.title")}
          value={formatNumber(l3Total, 0, locale)}
          description={t("memoryOverview.metrics.l3Vectors.description")}
          severity={l3Total > 0 ? "ok" : "unknown"}
          locale={locale}
        />
      </MetricGrid>

      <div className="grid gap-6 xl:grid-cols-3">
        <GlassPanel
          eyebrow={t("memoryOverview.layers.l1.eyebrow")}
          title={t("memoryOverview.layers.l1.title")}
          description={t("memoryOverview.layers.l1.description")}
        >
          <div className="space-y-3">
            <div className="flex items-center justify-between rounded-[20px] border border-white/70 bg-white/75 px-4 py-3">
              <span className="text-sm text-slate-500">{t("memoryOverview.layers.l1.scope")}</span>
              <span className="text-sm font-semibold text-slate-900">{data.l1.scope}</span>
            </div>
            <div className="flex items-center justify-between rounded-[20px] border border-white/70 bg-white/75 px-4 py-3">
              <span className="text-sm text-slate-500">{t("memoryOverview.layers.l1.total")}</span>
              <span className="text-sm font-semibold text-slate-900">{formatNumber(l1Total, 0, locale)}</span>
            </div>
            {data.l1.details ? (
              <div className="soft-inset p-4">
                {Object.entries(data.l1.details).map(([key, value]) => (
                  <div key={key} className="flex items-center justify-between py-1 text-sm">
                    <span className="text-slate-500">{key}</span>
                    <span className="font-medium text-slate-700">{String(value)}</span>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        </GlassPanel>

        <GlassPanel
          eyebrow={t("memoryOverview.layers.l2.eyebrow")}
          title={t("memoryOverview.layers.l2.title")}
          description={t("memoryOverview.layers.l2.description")}
        >
          <div className="space-y-3">
            <div className="flex items-center justify-between rounded-[20px] border border-white/70 bg-white/75 px-4 py-3">
              <span className="text-sm text-slate-500">{t("memoryOverview.layers.l2.scope")}</span>
              <span className="text-sm font-semibold text-slate-900">{data.l2.scope}</span>
            </div>
            <div className="flex items-center justify-between rounded-[20px] border border-white/70 bg-white/75 px-4 py-3">
              <span className="text-sm text-slate-500">{t("memoryOverview.layers.l2.indexed")}</span>
              <span className="text-sm font-semibold text-slate-900">{formatNumber(l2Total, 0, locale)}</span>
            </div>
            {data.l2.details ? (
              <div className="soft-inset p-4">
                {Object.entries(data.l2.details).map(([key, value]) => (
                  <div key={key} className="flex items-center justify-between py-1 text-sm">
                    <span className="text-slate-500">{key}</span>
                    <span className="font-medium text-slate-700">{String(value)}</span>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        </GlassPanel>

        <GlassPanel
          eyebrow={t("memoryOverview.layers.l3.eyebrow")}
          title={t("memoryOverview.layers.l3.title")}
          description={t("memoryOverview.layers.l3.description")}
        >
          <div className="space-y-3">
            <div className="flex items-center justify-between rounded-[20px] border border-white/70 bg-white/75 px-4 py-3">
              <span className="text-sm text-slate-500">{t("memoryOverview.layers.l3.scope")}</span>
              <span className="text-sm font-semibold text-slate-900">{data.l3.scope}</span>
            </div>
            <div className="flex items-center justify-between rounded-[20px] border border-white/70 bg-white/75 px-4 py-3">
              <span className="text-sm text-slate-500">{t("memoryOverview.layers.l3.total")}</span>
              <span className="text-sm font-semibold text-slate-900">{formatNumber(l3Total, 0, locale)}</span>
            </div>
            {data.l3.details ? (
              <div className="soft-inset p-4">
                {Object.entries(data.l3.details).map(([key, value]) => (
                  <div key={key} className="flex items-center justify-between py-1 text-sm">
                    <span className="text-slate-500">{key}</span>
                    <span className="font-medium text-slate-700">{String(value)}</span>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        </GlassPanel>
      </div>
    </div>
  );
}
