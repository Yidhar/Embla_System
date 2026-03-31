import Link from "next/link";

import { FrameworkSettingsPanel } from "@/components/framework-settings-panel";
import { GlassPanel, MetricCard, MetricGrid, PageHeader } from "@/components/dashboard-ui";
import { getAgentProfiles, getPromptTemplates, getSystemConfig, getSystemInfo } from "@/lib/api/ops";
import { createTranslator } from "@/lib/i18n";
import { getRequestLocale } from "@/lib/request-locale";

function recordValue(input: unknown): Record<string, unknown> {
  return input && typeof input === "object" && !Array.isArray(input) ? (input as Record<string, unknown>) : {};
}

function numberValue(input: unknown, fallback = 0) {
  const next = Number(input);
  return Number.isFinite(next) ? next : fallback;
}

export default async function SettingsPage() {
  const locale = await getRequestLocale();
  const t = createTranslator(locale);
  const [systemInfo, systemConfig, promptTemplates, agentProfiles] = await Promise.all([
    getSystemInfo(),
    getSystemConfig(),
    getPromptTemplates(),
    getAgentProfiles(),
  ]);

  const enabledProfiles = numberValue(agentProfiles.summary.enabled_profiles, agentProfiles.profiles.filter((item) => item.enabled !== false).length);
  const config = recordValue(systemConfig.config);

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={t("settings.header.eyebrow")}
        title={t("settings.header.title")}
        description={t("settings.header.description")}
        severity="ok"
        mode="live"
        locale={locale}
        actions={
          <Link href="/agent-config" className="rounded-full border border-white/70 bg-white/85 px-4 py-2 text-sm font-semibold text-slate-700">
            {t("settings.header.agentConfigCta")}
          </Link>
        }
      />

      <MetricGrid>
        <MetricCard
          title={t("settings.metrics.apiVersion.title")}
          value={String(systemInfo.version || "-")}
          description={t("settings.metrics.apiVersion.description")}
          severity="ok"
          locale={locale}
        />
        <MetricCard
          title={t("settings.metrics.promptTemplates.title")}
          value={String(promptTemplates.length)}
          description={t("settings.metrics.promptTemplates.description")}
          severity={promptTemplates.length > 0 ? "ok" : "warning"}
          locale={locale}
        />
        <MetricCard
          title={t("settings.metrics.agentProfiles.title")}
          value={`${enabledProfiles}/${agentProfiles.profiles.length}`}
          description={t("settings.metrics.agentProfiles.description")}
          severity={enabledProfiles > 0 ? "ok" : "warning"}
          locale={locale}
        />
        <MetricCard
          title={t("settings.metrics.apiKey.title")}
          value={systemInfo.api_key_configured ? t("settings.labels.configured") : t("settings.labels.notConfigured")}
          description={t("settings.metrics.apiKey.description")}
          severity={systemInfo.api_key_configured ? "ok" : "warning"}
          locale={locale}
        />
      </MetricGrid>

      <GlassPanel
        eyebrow={t("settings.sections.runtime.eyebrow")}
        title={t("settings.sections.runtime.title")}
        description={t("settings.sections.runtime.description")}
      >
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <div className="soft-inset p-4">
            <p className="text-sm font-semibold text-slate-900">{t("settings.labels.registryPath")}</p>
            <p className="mt-2 break-all text-sm leading-6 text-slate-500">{agentProfiles.registry_path || t("common.label.none")}</p>
          </div>
          <div className="soft-inset p-4">
            <p className="text-sm font-semibold text-slate-900">{t("settings.labels.allowedRoles")}</p>
            <p className="mt-2 text-sm leading-6 text-slate-500">{agentProfiles.allowed_roles.join(", ") || t("common.label.none")}</p>
          </div>
          <div className="soft-inset p-4">
            <p className="text-sm font-semibold text-slate-900">{t("settings.labels.promptTemplates")}</p>
            <p className="mt-2 text-sm leading-6 text-slate-500">{promptTemplates.slice(0, 4).map((item) => item.relative_path || item.name).join(" · ") || t("common.label.none")}</p>
          </div>
          <div className="soft-inset p-4">
            <p className="text-sm font-semibold text-slate-900">{t("settings.labels.availableServices")}</p>
            <p className="mt-2 text-sm leading-6 text-slate-500">{String((systemInfo.available_services || []).length)}</p>
          </div>
        </div>
      </GlassPanel>

      <FrameworkSettingsPanel
        locale={locale}
        initialConfig={config}
        registryPath={agentProfiles.registry_path || ""}
        promptTemplateCount={promptTemplates.length}
        enabledProfiles={enabledProfiles}
        totalProfiles={agentProfiles.profiles.length}
      />
    </div>
  );
}
