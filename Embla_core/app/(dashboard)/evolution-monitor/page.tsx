import { AlertTriangle, CheckCircle2, Settings2, TrendingUp } from "lucide-react";

import {
  BarList,
  GlassPanel,
  MetricCard,
  MetricGrid,
  PageHeader,
  SourceList
} from "@/components/dashboard-ui";
import { getEvolutionStatus } from "@/lib/api/ops";
import { formatPercent } from "@/lib/format";
import { createTranslator } from "@/lib/i18n";
import { getRequestLocale } from "@/lib/request-locale";

export default async function EvolutionMonitorPage() {
  const locale = await getRequestLocale();
  const t = createTranslator(locale);
  const evolution = await getEvolutionStatus();

  const data = evolution.data;
  const config = data.config ?? {};
  const signals = data.failure_signals ?? [];

  const enabledSeverity = data.enabled ? "ok" : "warning";
  const evolveSeverity = data.should_evolve ? "warning" : "ok";

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={t("evolutionMonitor.header.eyebrow")}
        title={t("evolutionMonitor.header.title")}
        description={t("evolutionMonitor.header.description")}
        severity={evolution.severity}
        mode={evolution.meta?.mode}
        locale={locale}
      />

      <MetricGrid>
        <MetricCard
          title={t("evolutionMonitor.metrics.enabled.title")}
          value={data.enabled ? t("evolutionMonitor.metrics.enabled.valueOn") : t("evolutionMonitor.metrics.enabled.valueOff")}
          description={t("evolutionMonitor.metrics.enabled.description")}
          severity={enabledSeverity}
          locale={locale}
        />
        <MetricCard
          title={t("evolutionMonitor.metrics.shouldEvolve.title")}
          value={data.should_evolve ? t("evolutionMonitor.metrics.shouldEvolve.valueYes") : t("evolutionMonitor.metrics.shouldEvolve.valueNo")}
          description={t("evolutionMonitor.metrics.shouldEvolve.description")}
          severity={evolveSeverity}
          locale={locale}
        />
        <MetricCard
          title={t("evolutionMonitor.metrics.signalCount.title")}
          value={String(signals.length)}
          description={t("evolutionMonitor.metrics.signalCount.description")}
          severity={signals.length > 0 ? "warning" : "ok"}
          locale={locale}
        />
        <MetricCard
          title={t("evolutionMonitor.metrics.triggerThreshold.title")}
          value={String(config.trigger_threshold ?? "—")}
          description={t("evolutionMonitor.metrics.triggerThreshold.description")}
          severity="ok"
          locale={locale}
        />
      </MetricGrid>

      <div className="grid gap-6 xl:grid-cols-[1.15fr_0.85fr]">
        <GlassPanel
          eyebrow={t("evolutionMonitor.signals.eyebrow")}
          title={t("evolutionMonitor.signals.title")}
          description={t("evolutionMonitor.signals.description")}
        >
          {signals.length > 0 ? (
            <div className="space-y-4">
              {signals.map((signal, index) => (
                <div key={`${signal.task_type}-${index}`} className="rounded-[20px] border border-white/70 bg-white/70 p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex items-center gap-2">
                      {signal.failure_count >= (config.trigger_threshold ?? 3)
                        ? <AlertTriangle className="h-4 w-4 text-amber-500" />
                        : <CheckCircle2 className="h-4 w-4 text-emerald-500" />
                      }
                      <span className="text-sm font-bold text-slate-900">{signal.task_type}</span>
                    </div>
                    <span className="rounded-full border border-white/70 bg-white px-3 py-1 text-xs text-slate-500">
                      {t("evolutionMonitor.signals.failureCount", { count: signal.failure_count })}
                    </span>
                  </div>
                  <div className="mt-3">
                    <div className="flex items-center justify-between text-xs text-slate-500 mb-1">
                      <span>{t("evolutionMonitor.signals.confidence")}</span>
                      <span>{formatPercent(signal.confidence, 0)}</span>
                    </div>
                    <div className="soft-inset h-2 overflow-hidden p-0.5">
                      <div
                        className="h-full rounded-full bg-[#1C1C1E]"
                        style={{ width: `${Math.max(8, (Math.abs(signal.confidence) <= 1 ? signal.confidence * 100 : signal.confidence))}%` }}
                      />
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="soft-inset flex min-h-32 flex-col items-center justify-center gap-2 px-4 py-8 text-center">
              <p className="text-sm font-semibold text-slate-700">{t("evolutionMonitor.signals.emptyTitle")}</p>
              <p className="max-w-md text-sm leading-6 text-slate-500">{t("evolutionMonitor.signals.emptyDescription")}</p>
            </div>
          )}
          <SourceList reports={evolution.source_reports} endpoints={evolution.source_endpoints} />
        </GlassPanel>

        <GlassPanel
          eyebrow={t("evolutionMonitor.config.eyebrow")}
          title={t("evolutionMonitor.config.title")}
          description={t("evolutionMonitor.config.description")}
        >
          <div className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="soft-inset p-4">
                <div className="flex items-center gap-2 text-slate-500">
                  <TrendingUp className="h-4 w-4" />
                  <span className="text-sm">{t("evolutionMonitor.config.triggerThreshold")}</span>
                </div>
                <p className="mt-3 text-2xl font-extrabold text-slate-900">{config.trigger_threshold ?? "—"}</p>
              </div>
              <div className="soft-inset p-4">
                <div className="flex items-center gap-2 text-slate-500">
                  <Settings2 className="h-4 w-4" />
                  <span className="text-sm">{t("evolutionMonitor.config.maxPerDay")}</span>
                </div>
                <p className="mt-3 text-2xl font-extrabold text-slate-900">{config.max_per_day ?? "—"}</p>
              </div>
            </div>

            <div className="rounded-[24px] border border-white/70 bg-white/70 p-4">
              <p className="eyebrow">{t("evolutionMonitor.config.allowedScopes")}</p>
              <div className="mt-4 flex flex-wrap gap-2">
                {(config.allowed_scopes ?? []).length > 0 ? (
                  (config.allowed_scopes as string[]).map((scope) => (
                    <span key={scope} className="rounded-full border border-white/70 bg-white px-3 py-2 text-sm text-slate-700">
                      {scope}
                    </span>
                  ))
                ) : (
                  <span className="text-sm text-slate-400">{t("evolutionMonitor.config.noScopes")}</span>
                )}
              </div>
            </div>

            {(config.allowed_scopes ?? []).length > 0 ? (
              <BarList
                items={(config.allowed_scopes as string[]).map((scope, index) => ({
                  label: scope,
                  value: (config.allowed_scopes as string[]).length - index
                }))}
              />
            ) : null}
          </div>
        </GlassPanel>
      </div>
    </div>
  );
}
