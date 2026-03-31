import { GlassPanel, PageHeader, SourceList, TimelineList } from "@/components/dashboard-ui";
import { getIncidents } from "@/lib/api/ops";
import { createTranslator } from "@/lib/i18n";
import { getRequestLocale } from "@/lib/request-locale";

export default async function IncidentsPage() {
  const locale = await getRequestLocale();
  const t = createTranslator(locale);
  const incidents = await getIncidents();

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={t("incidents.header.eyebrow")}
        title={t("incidents.header.title")}
        description={t("incidents.header.description")}
        severity={incidents.severity}
        mode={incidents.meta?.mode}
        locale={locale}
      />

      <GlassPanel eyebrow={t("incidents.latest.eyebrow")} title={t("incidents.latest.title")} description={t("incidents.latest.description")}>
        <TimelineList
          items={incidents.data.incidents.map((incident) => ({
            title: incident.summary,
            detail: [incident.payload_excerpt, incident.report_path].filter(Boolean).join(" · "),
            timestamp: incident.timestamp,
            severity: incident.severity
          }))}
          locale={locale}
        />
        <SourceList reports={incidents.source_reports} endpoints={incidents.source_endpoints} />
      </GlassPanel>
    </div>
  );
}
