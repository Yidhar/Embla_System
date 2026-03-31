import { Lock, ShieldCheck } from "lucide-react";

import {
  EmptyState,
  GlassPanel,
  MetricCard,
  MetricGrid,
  PageHeader
} from "@/components/dashboard-ui";
import { getDnaIntegrity } from "@/lib/api/ops";
import { formatNumber } from "@/lib/format";
import { createTranslator } from "@/lib/i18n";
import { getRequestLocale } from "@/lib/request-locale";

export default async function DnaIntegrityPage() {
  const locale = await getRequestLocale();
  const t = createTranslator(locale);
  const data = await getDnaIntegrity();

  const overallSeverity = data.verification_status === "pass" || data.verification_status === "ok"
    ? "ok"
    : data.verification_status === "unknown"
      ? "unknown"
      : "critical";

  const truncatedHash = data.manifest_hash
    ? `${data.manifest_hash.slice(0, 16)}...`
    : t("common.label.none");

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={t("dnaIntegrity.header.eyebrow")}
        title={t("dnaIntegrity.header.title")}
        description={t("dnaIntegrity.header.description")}
        severity={overallSeverity}
        locale={locale}
      />

      <MetricGrid>
        <MetricCard
          title={t("dnaIntegrity.metrics.verificationStatus.title")}
          value={data.verification_status || t("common.label.unknown")}
          description={t("dnaIntegrity.metrics.verificationStatus.description")}
          severity={overallSeverity}
          locale={locale}
        />
        <MetricCard
          title={t("dnaIntegrity.metrics.fileCount.title")}
          value={formatNumber(data.file_count, 0, locale)}
          description={t("dnaIntegrity.metrics.fileCount.description")}
          severity={data.file_count > 0 ? "ok" : "unknown"}
          locale={locale}
        />
        <MetricCard
          title={t("dnaIntegrity.metrics.manifestHash.title")}
          value={truncatedHash}
          description={t("dnaIntegrity.metrics.manifestHash.description")}
          severity={data.manifest_hash ? "ok" : "unknown"}
          footnote={data.manifest_hash || undefined}
          locale={locale}
        />
      </MetricGrid>

      <GlassPanel
        eyebrow={t("dnaIntegrity.promptList.eyebrow")}
        title={t("dnaIntegrity.promptList.title")}
        description={t("dnaIntegrity.promptList.description")}
      >
        {data.prompts.length === 0 ? (
          <EmptyState
            title={t("dnaIntegrity.promptList.emptyTitle")}
            description={t("dnaIntegrity.promptList.emptyDescription")}
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200/60 text-left text-xs font-semibold text-slate-500">
                  <th className="pb-3 pr-4">{t("dnaIntegrity.promptList.path")}</th>
                  <th className="pb-3 pr-4">{t("dnaIntegrity.promptList.immutable")}</th>
                  <th className="pb-3">{t("dnaIntegrity.promptList.size")}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {data.prompts.map((prompt) => (
                  <tr key={prompt.path} className="text-slate-700">
                    <td className="py-3 pr-4 font-medium">
                      <span className="flex items-center gap-2">
                        <ShieldCheck className="h-4 w-4 shrink-0 text-slate-400" />
                        <span className="truncate">{prompt.path}</span>
                      </span>
                    </td>
                    <td className="py-3 pr-4">
                      {prompt.immutable ? (
                        <span className="inline-flex items-center gap-1 rounded-full border border-emerald-200/70 bg-emerald-50/80 px-2.5 py-0.5 text-xs font-semibold text-emerald-700">
                          <Lock className="h-3 w-3" />
                          {t("dnaIntegrity.promptList.immutable")}
                        </span>
                      ) : (
                        <span className="text-xs text-slate-400">&mdash;</span>
                      )}
                    </td>
                    <td className="py-3 text-slate-500">
                      {prompt.size_bytes != null
                        ? `${formatNumber(prompt.size_bytes, 0, locale)} B`
                        : t("common.label.unknown")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassPanel>
    </div>
  );
}
