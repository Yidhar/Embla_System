import { SignalCard } from "@/components/cards/signal-card";

export default function WorkflowEventsPage() {
  return (
    <div className="space-y-6">
      <section className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
        <SignalCard title="Outbox Pending" value="--" note="Pending events in workflow DB" state="unknown" />
        <SignalCard title="Oldest Age" value="--" note="Oldest pending event age (s)" state="unknown" />
        <SignalCard title="Lease Lost" value="--" note="Lease loss events (recent window)" state="unknown" />
        <SignalCard title="Tool Status" value="--" note="Current tool execution heartbeat" state="unknown" />
      </section>

      <section className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <article className="glass-card p-6">
          <p className="text-[10px] font-bold uppercase tracking-[0.25em] text-gray-500">Event Timeline</p>
          <div className="mt-4 flex h-[320px] items-center justify-center rounded-3xl border border-dashed border-gray-300/80 bg-white/60 text-sm text-gray-500">
            Timeline visualization placeholder
          </div>
        </article>
        <article className="glass-card p-6">
          <p className="text-[10px] font-bold uppercase tracking-[0.25em] text-gray-500">Data Plumbing</p>
          <ul className="mt-4 space-y-2 text-sm text-gray-700">
            <li className="rounded-xl bg-white/70 p-3 font-mono text-xs">logs/autonomous/events.jsonl</li>
            <li className="rounded-xl bg-white/70 p-3 font-mono text-xs">logs/autonomous/workflow.db</li>
            <li className="rounded-xl bg-white/70 p-3 font-mono text-xs">GET /logs/context/statistics</li>
            <li className="rounded-xl bg-white/70 p-3 font-mono text-xs">GET /tool_status</li>
          </ul>
        </article>
      </section>
    </div>
  );
}
