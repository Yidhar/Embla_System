import { AgentProfileManager } from "@/components/agent-profile-manager";
import { MetricCard, MetricGrid, PageHeader } from "@/components/dashboard-ui";
import { getAgentProfileDetail, getAgentProfiles } from "@/lib/api/ops";
import { createTranslator } from "@/lib/i18n";
import { getRequestLocale } from "@/lib/request-locale";

function numberValue(input: unknown, fallback = 0) {
  const next = Number(input);
  return Number.isFinite(next) ? next : fallback;
}

export default async function AgentConfigPage() {
  const locale = await getRequestLocale();
  const t = createTranslator(locale);
  const registry = await getAgentProfiles();
  const firstAgentType = registry.profiles[0]?.agent_type ?? "";
  const detail = firstAgentType ? await getAgentProfileDetail(firstAgentType) : null;
  const enabledProfiles = numberValue(registry.summary.enabled_profiles, registry.profiles.filter((item) => item.enabled !== false).length);
  const defaultProfiles = numberValue(registry.summary.default_profiles, registry.profiles.filter((item) => item.default_for_role).length);

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={t("agentConfig.header.eyebrow")}
        title={t("agentConfig.header.title")}
        description={t("agentConfig.header.description")}
        severity={registry.profiles.length > 0 ? "ok" : "warning"}
        mode="live"
        locale={locale}
      />

      <MetricGrid>
        <MetricCard
          title={t("agentConfig.metrics.totalProfiles.title")}
          value={String(registry.profiles.length)}
          description={t("agentConfig.metrics.totalProfiles.description")}
          severity={registry.profiles.length > 0 ? "ok" : "warning"}
          locale={locale}
        />
        <MetricCard
          title={t("agentConfig.metrics.enabledProfiles.title")}
          value={String(enabledProfiles)}
          description={t("agentConfig.metrics.enabledProfiles.description")}
          severity={enabledProfiles > 0 ? "ok" : "warning"}
          locale={locale}
        />
        <MetricCard
          title={t("agentConfig.metrics.defaultProfiles.title")}
          value={String(defaultProfiles)}
          description={t("agentConfig.metrics.defaultProfiles.description")}
          severity={defaultProfiles > 0 ? "ok" : "warning"}
          locale={locale}
        />
        <MetricCard
          title={t("agentConfig.metrics.promptTemplates.title")}
          value={String((registry.prompt_templates || []).length)}
          description={t("agentConfig.metrics.promptTemplates.description")}
          severity={(registry.prompt_templates || []).length > 0 ? "ok" : "warning"}
          locale={locale}
        />
      </MetricGrid>

      <AgentProfileManager locale={locale} initialRegistry={registry} initialDetail={detail} />
    </div>
  );
}
