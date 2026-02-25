import { SignalCard, type SignalState } from "@/components/cards/signal-card";
import { fetchWorkflowEvents } from "@/lib/api/ops";

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
  const payload = await fetchWorkflowEvents();
  const summary = payload?.data?.summary;
  const toolStatus = payload?.data?.tool_status || {};
  const eventCounters = payload?.data?.event_counters || {};
  const recentEvents = payload?.data?.recent_critical_events || [];
  const logStats = payload?.data?.log_context_statistics || {};

  const outboxPending = summary?.outbox_pending;
  const oldestPendingAge = summary?.oldest_pending_age_seconds;
  const leaseLost = Number(eventCounters.LeaseLost || 0);
  const state = toState(payload?.severity || "unknown");

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
                  <tr
                    key={`${item.timestamp}-${item.event_type}-${idx}`}
                    className="border-b border-gray-100/70 align-top"
                  >
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
      </section>
    </div>
  );
}
