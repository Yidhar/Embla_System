import { SignalCard, type SignalState } from "@/components/cards/signal-card";
import { fetchIncidentsLatest, fetchWorkflowEvents } from "@/lib/api/ops";

export const dynamic = "force-dynamic";

function toState(status: string): SignalState {
  const normalized = String(status || "unknown").toLowerCase();
  if (normalized === "ok" || normalized === "healthy") {
    return "healthy";
  }
  if (normalized === "warning") {
    return "warning";
  }
  if (normalized === "critical") {
    return "critical";
  }
  return "unknown";
}

function toText(value: unknown, suffix = ""): string {
  if (typeof value === "number" && Number.isFinite(value)) {
    return `${value}${suffix}`;
  }
  return "--";
}

export default async function WorkflowEventsPage() {
  const [payload, incidentsPayload] = await Promise.all([fetchWorkflowEvents(), fetchIncidentsLatest()]);
  const summary = payload?.data?.summary;
  const toolStatus = payload?.data?.tool_status || {};
  const eventCounters = payload?.data?.event_counters || {};
  const recentEvents = payload?.data?.recent_critical_events || [];
  const logStats = payload?.data?.log_context_statistics || {};

  const incidentsSummary = incidentsPayload?.data?.summary;
  const incidents = incidentsPayload?.data?.incidents || [];

  const outboxPending = summary?.outbox_pending;
  const oldestPendingAge = summary?.oldest_pending_age_seconds;
  const leaseLost = Number(eventCounters.LeaseLost || 0);
  const state = toState(payload?.severity || "unknown");
  const incidentsState = toState(incidentsPayload?.severity || "unknown");

  return (
    <div className="space-y-6">
      <section className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
        <SignalCard
          title="Outbox Pending"
          value={toText(outboxPending)}
          note="Pending events in workflow DB"
          state={state}
        />
        <SignalCard
          title="Oldest Age"
          value={toText(oldestPendingAge, "s")}
          note="Oldest pending event age"
          state={state}
        />
        <SignalCard
          title="Lease Lost"
          value={String(leaseLost)}
          note="Lease loss events in scanned window"
          state={leaseLost > 0 ? "warning" : state}
        />
        <SignalCard
          title="Tool Status"
          value={toolStatus.visible ? "VISIBLE" : "IDLE"}
          note={String(toolStatus.message || "No active tool event")}
          state={toolStatus.visible ? "warning" : state}
        />
      </section>

      <section className="grid grid-cols-1 gap-4 xl:grid-cols-4">
        <SignalCard
          title="Incidents Total"
          value={String(incidentsSummary?.total_incidents || 0)}
          note="Events + evidence gate incidents"
          state={incidentsState}
        />
        <SignalCard
          title="Critical Incidents"
          value={String(incidentsSummary?.critical_incidents || 0)}
          note="Critical incident count in current window"
          state={Number(incidentsSummary?.critical_incidents || 0) > 0 ? "critical" : incidentsState}
        />
        <SignalCard
          title="Warning Incidents"
          value={String(incidentsSummary?.warning_incidents || 0)}
          note="Warning incident count in current window"
          state={Number(incidentsSummary?.warning_incidents || 0) > 0 ? "warning" : incidentsState}
        />
        <SignalCard
          title="Latest Incident"
          value={String(incidentsSummary?.latest_incident_at || "--")}
          note="Most recent incident timestamp"
          state={incidentsState}
        />
      </section>

      <section className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <article className="glass-card p-6">
          <p className="text-[10px] font-bold uppercase tracking-[0.25em] text-gray-500">Recent Critical Events</p>
          <div className="mt-4 overflow-auto rounded-2xl bg-white/70 p-3">
            <table className="min-w-full text-left text-xs text-gray-700">
              <thead>
                <tr className="border-b border-gray-200/80">
                  <th className="px-2 py-2 uppercase tracking-[0.2em]">Time</th>
                  <th className="px-2 py-2 uppercase tracking-[0.2em]">Type</th>
                  <th className="px-2 py-2 uppercase tracking-[0.2em]">Payload</th>
                </tr>
              </thead>
              <tbody>
                {recentEvents.slice(0, 25).map((item, idx) => (
                  <tr key={`${item.timestamp}-${item.event_type}-${idx}`} className="border-b border-gray-100/70 align-top">
                    <td className="px-2 py-2 font-mono">{item.timestamp || "-"}</td>
                    <td className="px-2 py-2">{item.event_type || "-"}</td>
                    <td className="px-2 py-2">
                      <pre className="whitespace-pre-wrap text-[10px]">
                        {JSON.stringify(item.payload_excerpt || {}, null, 2)}
                      </pre>
                    </td>
                  </tr>
                ))}
                {(!payload || recentEvents.length === 0) && (
                  <tr>
                    <td colSpan={3} className="px-2 py-3 text-gray-500">
                      No critical events in current scan window.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </article>

        <article className="glass-card p-6">
          <p className="text-[10px] font-bold uppercase tracking-[0.25em] text-gray-500">Incident Feed</p>
          <div className="mt-4 overflow-auto rounded-2xl bg-white/70 p-3">
            <table className="min-w-full text-left text-xs text-gray-700">
              <thead>
                <tr className="border-b border-gray-200/80">
                  <th className="px-2 py-2 uppercase tracking-[0.2em]">Severity</th>
                  <th className="px-2 py-2 uppercase tracking-[0.2em]">Source</th>
                  <th className="px-2 py-2 uppercase tracking-[0.2em]">Summary</th>
                </tr>
              </thead>
              <tbody>
                {incidents.slice(0, 25).map((item, idx) => (
                  <tr key={`${item.timestamp}-${item.summary}-${idx}`} className="border-b border-gray-100/70 align-top">
                    <td className="px-2 py-2 uppercase">{String(item.severity || "unknown")}</td>
                    <td className="px-2 py-2">{String(item.source || "-")}</td>
                    <td className="px-2 py-2">
                      <p>{String(item.summary || "-")}</p>
                      <p className="mt-1 font-mono text-[10px] text-gray-500">{String(item.timestamp || "-")}</p>
                    </td>
                  </tr>
                ))}
                {(!incidentsPayload || incidents.length === 0) && (
                  <tr>
                    <td colSpan={3} className="px-2 py-3 text-gray-500">
                      No incidents in current scan window.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </article>
      </section>

      <section className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <article className="glass-card p-6">
          <p className="text-[10px] font-bold uppercase tracking-[0.25em] text-gray-500">Event Posture Summary</p>
          <div className="mt-4 space-y-3 text-xs text-gray-700">
            <div className="rounded-xl bg-white/70 p-3">
              <p className="font-bold uppercase tracking-[0.2em] text-gray-500">Event Counters</p>
              <pre className="mt-2 whitespace-pre-wrap">{JSON.stringify(eventCounters, null, 2)}</pre>
            </div>
            <div className="rounded-xl bg-white/70 p-3">
              <p className="font-bold uppercase tracking-[0.2em] text-gray-500">Log Context Stats</p>
              <pre className="mt-2 whitespace-pre-wrap">{JSON.stringify(logStats, null, 2)}</pre>
            </div>
          </div>
        </article>

        <article className="glass-card p-6">
          <p className="text-[10px] font-bold uppercase tracking-[0.25em] text-gray-500">Incident Counters</p>
          <div className="mt-4 rounded-xl bg-white/70 p-3 text-xs text-gray-700">
            <pre className="whitespace-pre-wrap">
              {JSON.stringify(
                {
                  severity: incidentsPayload?.severity || "unknown",
                  reason_code: incidentsPayload?.reason_code || "",
                  reason_text: incidentsPayload?.reason_text || "",
                  event_counters: incidentsPayload?.data?.event_counters || {},
                  events_scanned: incidentsPayload?.data?.events_scanned || 0,
                },
                null,
                2,
              )}
            </pre>
          </div>
        </article>
      </section>
    </div>
  );
}
