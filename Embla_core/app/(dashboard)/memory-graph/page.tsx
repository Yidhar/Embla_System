import { SignalCard } from "@/components/cards/signal-card";

export default function MemoryGraphPage() {
  return (
    <div className="space-y-6">
      <section className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        <SignalCard title="Quintuples" value="--" note="Total extracted memory tuples" state="unknown" />
        <SignalCard title="Active Tasks" value="--" note="In-flight extraction tasks" state="unknown" />
        <SignalCard title="Task Backlog" value="--" note="Task manager queue pressure" state="unknown" />
      </section>

      <section className="grid grid-cols-1 gap-4 xl:grid-cols-5">
        <article className="glass-card col-span-3 p-6">
          <p className="text-[10px] font-bold uppercase tracking-[0.25em] text-gray-500">Memory Graph Canvas</p>
          <div className="mt-4 flex h-[420px] items-center justify-center rounded-3xl border border-dashed border-gray-300/80 bg-white/60 text-sm text-gray-500">
            Graph renderer placeholder (subject-predicate-object relation view)
          </div>
        </article>
        <article className="glass-card col-span-2 p-6">
          <p className="text-[10px] font-bold uppercase tracking-[0.25em] text-gray-500">Query Drilldown</p>
          <div className="mt-4 space-y-3 text-sm text-gray-700">
            <p>Planned sources:</p>
            <p className="rounded-xl bg-white/70 p-3 font-mono text-xs">GET /memory/stats</p>
            <p className="rounded-xl bg-white/70 p-3 font-mono text-xs">GET /memory/quintuples</p>
            <p className="rounded-xl bg-white/70 p-3 font-mono text-xs">GET /memory/quintuples/search</p>
          </div>
        </article>
      </section>
    </div>
  );
}
