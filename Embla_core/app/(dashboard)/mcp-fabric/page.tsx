import { CircleSlash, Component, PlugZap, ShieldEllipsis } from "lucide-react";

import { GlassPanel, MetricGrid, PageHeader, SourceList } from "@/components/dashboard-ui";
import { ManagementPanels } from "@/components/management-panels";
import { getMcpFabric } from "@/lib/api/ops";
import { formatNumber } from "@/lib/format";
import { createTranslator, humanizeEnum } from "@/lib/i18n";
import { getRequestLocale } from "@/lib/request-locale";
import { deriveMcpBreakdown, numberValue } from "@/lib/view-models";

function InventoryCard({ title, value, description, footnote }: { title: string; value: string; description: string; footnote?: string }) {
  return (
    <article className="glass-card h-full">
      <p className="eyebrow">{title}</p>
      <p className="mt-4 text-3xl font-extrabold tracking-tight text-[#1C1C1E]">{value}</p>
      <p className="mt-3 text-sm leading-6 text-slate-500">{description}</p>
      {footnote ? <p className="mt-4 text-xs text-slate-400">{footnote}</p> : null}
    </article>
  );
}

export default async function McpFabricPage() {
  const locale = await getRequestLocale();
  const t = createTranslator(locale);
  const mcp = await getMcpFabric();
  const breakdown = deriveMcpBreakdown(mcp.data);

  const toolInventory = mcp.data.tool_inventory;
  const toolBreakdown = [
    `${formatNumber(numberValue(toolInventory?.memory_tools), 0, locale)} memory`,
    `${formatNumber(numberValue(toolInventory?.native_tools), 0, locale)} native`,
    `${formatNumber(numberValue(toolInventory?.dynamic_tools), 0, locale)} dynamic`
  ].join(" · ");

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={t("mcpFabric.header.eyebrow")}
        title={t("mcpFabric.header.title")}
        description={t("mcpFabric.header.description")}
        severity={mcp.severity}
        mode={mcp.meta?.mode}
        locale={locale}
      />

      <MetricGrid>
        <InventoryCard
          title={t("mcpFabric.metrics.tools.title")}
          value={formatNumber(numberValue(mcp.data.summary.local_tools ?? toolInventory?.total_tools), 0, locale)}
          description={t("mcpFabric.metrics.tools.description")}
          footnote={toolBreakdown}
        />
        <InventoryCard
          title={t("mcpFabric.metrics.mcpServices.title")}
          value={formatNumber(numberValue(mcp.data.summary.total_services), 0, locale)}
          description={t("mcpFabric.metrics.mcpServices.description")}
        />
        <InventoryCard
          title={t("mcpFabric.metrics.mcpTools.title")}
          value={formatNumber(numberValue(mcp.data.summary.mcp_tools ?? mcp.data.registry?.registered_tool_count), 0, locale)}
          description={t("mcpFabric.metrics.mcpTools.description")}
        />
        <InventoryCard
          title={t("mcpFabric.metrics.skills.title")}
          value={formatNumber(numberValue(mcp.data.skill_inventory?.total_skills), 0, locale)}
          description={t("mcpFabric.metrics.skills.description")}
        />
      </MetricGrid>

      <div className="grid gap-6 xl:grid-cols-[1.1fr_0.9fr]">
        <GlassPanel eyebrow={t("mcpFabric.serviceMatrix.eyebrow")} title={t("mcpFabric.serviceMatrix.title")} description={t("mcpFabric.serviceMatrix.description")}>
          <div className="space-y-3">
            {mcp.data.services.length === 0 ? (
              <div className="soft-inset p-6 text-center text-sm text-slate-500">{t("mcpFabric.serviceMatrix.empty")}</div>
            ) : (
              mcp.data.services.map((service) => {
                const statusLabel = service.status_label ?? (service.available ? "online" : "offline");
                return (
                  <div key={`${service.source}-${service.name}`} className="grid gap-3 rounded-[24px] border border-white/70 bg-white/75 p-4 md:grid-cols-[minmax(0,1fr)_120px_140px] md:items-center">
                    <div>
                      <p className="text-sm font-semibold text-slate-900">{service.display_name || service.name}</p>
                      <p className="mt-1 text-sm leading-6 text-slate-500">{service.description || t("common.label.noDescription")}</p>
                    </div>
                    <div className="flex flex-wrap gap-2 text-xs">
                      <span className="rounded-full border border-white/70 bg-white px-3 py-1 text-slate-600">{service.source}</span>
                      <span className="rounded-full border border-white/70 bg-white px-3 py-1 text-slate-600">{humanizeEnum(locale, "mcpStatus", statusLabel)}</span>
                    </div>
                    <div className="text-sm text-slate-500">{service.status_reason ?? t("common.label.manageable")}</div>
                  </div>
                );
              })
            )}
          </div>
          <SourceList reports={mcp.source_reports} endpoints={mcp.source_endpoints} />
        </GlassPanel>

        <GlassPanel eyebrow={t("mcpFabric.trustBoundary.eyebrow")} title={t("mcpFabric.trustBoundary.title")} description={t("mcpFabric.trustBoundary.description")}>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="soft-inset p-4">
              <div className="flex items-center gap-2 text-slate-500"><PlugZap className="h-4 w-4" /><span className="text-sm">{t("mcpFabric.trustBoundary.statusBreakdown")}</span></div>
              <div className="mt-3 space-y-2 text-sm text-slate-600">
                {breakdown.byStatus.map((item) => (
                  <div key={item.label} className="flex items-center justify-between gap-4">
                    <span>{humanizeEnum(locale, "mcpStatus", item.label)}</span>
                    <span className="font-semibold text-slate-900">{formatNumber(item.value, 0, locale)}</span>
                  </div>
                ))}
              </div>
            </div>
            <div className="soft-inset p-4">
              <div className="flex items-center gap-2 text-slate-500"><Component className="h-4 w-4" /><span className="text-sm">{t("mcpFabric.trustBoundary.sourceBreakdown")}</span></div>
              <div className="mt-3 space-y-2 text-sm text-slate-600">
                {breakdown.bySource.map((item) => (
                  <div key={item.label} className="flex items-center justify-between gap-4">
                    <span>{item.label}</span>
                    <span className="font-semibold text-slate-900">{formatNumber(item.value, 0, locale)}</span>
                  </div>
                ))}
              </div>
            </div>
            <div className="soft-inset p-4">
              <div className="flex items-center gap-2 text-slate-500"><ShieldEllipsis className="h-4 w-4" /><span className="text-sm">{t("mcpFabric.trustBoundary.rejected")}</span></div>
              <p className="mt-3 text-2xl font-extrabold text-slate-900">{formatNumber(numberValue(mcp.data.summary.rejected_plugin_manifests), 0, locale)}</p>
              <p className="mt-2 text-sm text-slate-500">{t("mcpFabric.trustBoundary.rejectedDescription")}</p>
            </div>
            <div className="soft-inset p-4">
              <div className="flex items-center gap-2 text-slate-500"><CircleSlash className="h-4 w-4" /><span className="text-sm">{t("mcpFabric.trustBoundary.isolated")}</span></div>
              <p className="mt-3 text-2xl font-extrabold text-slate-900">{formatNumber(numberValue(mcp.data.summary.isolated_worker_services), 0, locale)}</p>
              <p className="mt-2 text-sm text-slate-500">{t("mcpFabric.trustBoundary.isolatedDescription")}</p>
            </div>
          </div>
        </GlassPanel>
      </div>

      <ManagementPanels locale={locale} />
    </div>
  );
}
