import { SignalCard, type SignalState } from "@/components/cards/signal-card";
import { MemoryGraphCanvas } from "@/components/graphs/memory-graph-canvas";
import { fetchMemoryGraph } from "@/lib/api/ops";

export const dynamic = "force-dynamic";

function toSignalState(totalQuintuples: number, failedTasks: number, enabled: boolean): SignalState {
  if (!enabled) {
    return "unknown";
  }
  if (failedTasks > 0) {
    return "warning";
  }
  if (totalQuintuples <= 0) {
    return "unknown";
  }
  return "healthy";
}

export default async function MemoryGraphPage() {
  const payload = await fetchMemoryGraph();
  const summary = payload?.data?.summary;

  const enabled = Boolean(summary?.enabled);
  const totalQuintuples = Number(summary?.total_quintuples || 0);
  const activeTasks = Number(summary?.active_tasks || 0);
  const pendingTasks = Number(summary?.pending_tasks || 0);
  const failedTasks = Number(summary?.failed_tasks || 0);
  const state = toSignalState(totalQuintuples, failedTasks, enabled);

  return (
    <div className="space-y-6">
      <section className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
        <SignalCard
          title="Quintuples"
          value={String(totalQuintuples)}
          note="Total extracted memory tuples"
          state={state}
        />
        <SignalCard title="Active Tasks" value={String(activeTasks)} note="In-flight extraction tasks" state={state} />
        <SignalCard title="Pending Tasks" value={String(pendingTasks)} note="Task queue pending load" state={state} />
        <SignalCard
          title="Failed Tasks"
          value={String(failedTasks)}
          note="Extraction failures in task manager"
          state={failedTasks > 0 ? "warning" : state}
        />
      </section>

      <section className="grid grid-cols-1 gap-4 xl:grid-cols-5">
        <article className="glass-card col-span-3 p-6">
          <p className="text-[10px] font-bold uppercase tracking-[0.25em] text-gray-500">Interactive Graph</p>
          <div className="mt-4">
            <MemoryGraphCanvas rows={payload?.data?.graph_sample || []} />
          </div>
        </article>

        <article className="glass-card col-span-2 p-6">
          <p className="text-[10px] font-bold uppercase tracking-[0.25em] text-gray-500">Hotspots</p>
          <div className="mt-4 space-y-4">
            <section>
              <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-gray-500">Relations</p>
              <ul className="mt-2 space-y-2">
                {(payload?.data?.relation_hotspots || []).slice(0, 8).map((item) => (
                  <li
                    key={`${item.relation}-${item.count}`}
                    className="flex items-center justify-between rounded-xl bg-white/70 px-3 py-2 text-xs"
                  >
                    <span>{item.relation || "-"}</span>
                    <span className="font-bold">{item.count}</span>
                  </li>
                ))}
              </ul>
            </section>
            <section>
              <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-gray-500">Entities</p>
              <ul className="mt-2 space-y-2">
                {(payload?.data?.entity_hotspots || []).slice(0, 8).map((item) => (
                  <li
                    key={`${item.entity}-${item.count}`}
                    className="flex items-center justify-between rounded-xl bg-white/70 px-3 py-2 text-xs"
                  >
                    <span>{item.entity || "-"}</span>
                    <span className="font-bold">{item.count}</span>
                  </li>
                ))}
              </ul>
            </section>
          </div>
        </article>
      </section>
    </div>
  );
}
