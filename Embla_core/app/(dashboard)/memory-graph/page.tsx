import { Activity, Brain, DatabaseZap, Network } from "lucide-react";

import { BarList, GlassPanel, GraphCanvas, MetricCard, MetricGrid, PageHeader, SourceList } from "@/components/dashboard-ui";
import { MemorySearchPanel } from "@/components/memory-search-panel";
import { getMemoryGraph } from "@/lib/api/ops";
import { formatNumber, formatPercent } from "@/lib/format";
import { createTranslator } from "@/lib/i18n";
import { getRequestLocale } from "@/lib/request-locale";
import { deriveRecallReadiness, numberValue } from "@/lib/view-models";

export default async function MemoryGraphPage() {
  const locale = await getRequestLocale();
  const t = createTranslator(locale);
  const memory = await getMemoryGraph();
  const recall = deriveRecallReadiness(memory.data, locale);
  const suggestionKeywords = memory.data.relation_hotspots.slice(0, 3).map((item) => item.relation);

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={t("memoryGraph.header.eyebrow")}
        title={t("memoryGraph.header.title")}
        description={t("memoryGraph.header.description")}
        severity={memory.severity}
        mode={memory.meta?.mode}
        locale={locale}
      />

      <MetricGrid>
        <MetricCard title={t("memoryGraph.metrics.recallReadiness")} value={formatPercent(recall.score, 0)} description={recall.description} severity={recall.severity} footnote={recall.label} locale={locale} />
        <MetricCard title={t("memoryGraph.metrics.quintuples.title")} value={formatNumber(numberValue(memory.data.summary.total_quintuples), 0, locale)} description={t("memoryGraph.metrics.quintuples.description")} severity={memory.severity} locale={locale} />
        <MetricCard title={t("memoryGraph.metrics.activeTasks.title")} value={formatNumber(numberValue(memory.data.summary.active_tasks), 0, locale)} description={t("memoryGraph.metrics.activeTasks.description")} severity={numberValue(memory.data.summary.active_tasks) > 0 ? "warning" : "ok"} locale={locale} />
        <MetricCard title={t("memoryGraph.metrics.vectorIndex.title")} value={String(memory.data.summary.vector_index_state ?? t("common.label.unknown"))} description={t("memoryGraph.metrics.vectorIndex.description")} severity={Boolean(memory.data.summary.vector_index_ready) ? "ok" : "warning"} locale={locale} />
      </MetricGrid>

      <div className="grid gap-6 xl:grid-cols-[1.2fr_0.8fr]">
        <GlassPanel eyebrow={t("memoryGraph.graphCanvas.eyebrow")} title={t("memoryGraph.graphCanvas.title")} description={t("memoryGraph.graphCanvas.description")}>
          <GraphCanvas edges={memory.data.graph_sample} locale={locale} />
          <SourceList reports={memory.source_reports} endpoints={memory.source_endpoints} />
        </GlassPanel>

        <GlassPanel eyebrow={t("memoryGraph.hotspots.eyebrow")} title={t("memoryGraph.hotspots.title")} description={t("memoryGraph.hotspots.description")}>
          <div className="grid gap-6">
            <div>
              <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-700"><Network className="h-4 w-4" />{t("memoryGraph.hotspots.relation")}</div>
              <BarList items={memory.data.relation_hotspots.map((item) => ({ label: item.relation, value: item.count }))} formatter={(value) => formatNumber(value, 0, locale)} />
            </div>
            <div>
              <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-700"><Brain className="h-4 w-4" />{t("memoryGraph.hotspots.entity")}</div>
              <BarList items={memory.data.entity_hotspots.map((item) => ({ label: item.entity, value: item.count }))} formatter={(value) => formatNumber(value, 0, locale)} />
            </div>
            <div className="grid gap-3 sm:grid-cols-3">
              <div className="soft-inset p-4"><div className="flex items-center gap-2 text-slate-500"><DatabaseZap className="h-4 w-4" /><span className="text-sm">{t("memoryGraph.hotspots.pending")}</span></div><p className="mt-3 text-2xl font-extrabold text-slate-900">{formatNumber(numberValue(memory.data.summary.pending_tasks), 0, locale)}</p></div>
              <div className="soft-inset p-4"><div className="flex items-center gap-2 text-slate-500"><Activity className="h-4 w-4" /><span className="text-sm">{t("memoryGraph.hotspots.running")}</span></div><p className="mt-3 text-2xl font-extrabold text-slate-900">{formatNumber(numberValue(memory.data.summary.running_tasks), 0, locale)}</p></div>
              <div className="soft-inset p-4"><div className="flex items-center gap-2 text-slate-500"><Brain className="h-4 w-4" /><span className="text-sm">{t("memoryGraph.hotspots.failed")}</span></div><p className="mt-3 text-2xl font-extrabold text-slate-900">{formatNumber(numberValue(memory.data.summary.failed_tasks), 0, locale)}</p></div>
            </div>
          </div>
        </GlassPanel>
      </div>

      <MemorySearchPanel locale={locale} defaultKeywords={suggestionKeywords.length > 0 ? suggestionKeywords : ["agent", "memory", "workflow"]} />
    </div>
  );
}
