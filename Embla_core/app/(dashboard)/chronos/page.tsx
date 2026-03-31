import { CheckCircle2, XCircle } from "lucide-react";

import {
  EmptyState,
  GlassPanel,
  MetricCard,
  MetricGrid,
  PageHeader
} from "@/components/dashboard-ui";
import { getChronosJobs } from "@/lib/api/ops";
import { formatTimestamp } from "@/lib/format";
import { createTranslator } from "@/lib/i18n";
import { getRequestLocale } from "@/lib/request-locale";

export default async function ChronosPage() {
  const locale = await getRequestLocale();
  const t = createTranslator(locale);
  const data = await getChronosJobs();

  const schedulerSeverity = data.scheduler_running ? "ok" : "warning";

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={t("chronos.header.eyebrow")}
        title={t("chronos.header.title")}
        description={t("chronos.header.description")}
        severity={schedulerSeverity}
        locale={locale}
      />

      <MetricGrid>
        <MetricCard
          title={t("chronos.metrics.schedulerStatus.title")}
          value={data.scheduler_running ? t("common.label.running") : t("common.label.unknown")}
          description={t("chronos.metrics.schedulerStatus.description")}
          severity={schedulerSeverity}
          locale={locale}
        />
        <MetricCard
          title={t("chronos.metrics.jobCount.title")}
          value={String(data.job_count)}
          description={t("chronos.metrics.jobCount.description")}
          severity={data.job_count > 0 ? "ok" : "unknown"}
          locale={locale}
        />
      </MetricGrid>

      <GlassPanel
        eyebrow={t("chronos.jobList.eyebrow")}
        title={t("chronos.jobList.title")}
        description={t("chronos.jobList.description")}
      >
        {data.jobs.length === 0 ? (
          <EmptyState
            title={t("chronos.jobList.emptyTitle")}
            description={t("chronos.jobList.emptyDescription")}
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200/60 text-left text-xs font-semibold text-slate-500">
                  <th className="pb-3 pr-4">{t("chronos.jobList.id")}</th>
                  <th className="pb-3 pr-4">{t("chronos.jobList.nextRun")}</th>
                  <th className="pb-3" />
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {data.jobs.map((job) => (
                  <tr key={job.id} className="text-slate-700">
                    <td className="py-3 pr-4 font-medium">{job.id}</td>
                    <td className="py-3 pr-4 text-slate-500">
                      {job.next_run ? formatTimestamp(job.next_run, locale) : t("common.label.unknown")}
                    </td>
                    <td className="py-3">
                      {job.status === "active" || data.scheduler_running ? (
                        <CheckCircle2 className="h-4 w-4 text-emerald-500" />
                      ) : (
                        <XCircle className="h-4 w-4 text-slate-400" />
                      )}
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
