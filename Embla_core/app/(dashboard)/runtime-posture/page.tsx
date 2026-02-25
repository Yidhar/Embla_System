import { SignalCard, type SignalState } from "@/components/cards/signal-card";
import { fetchRuntimePosture } from "@/lib/api/ops";

export const dynamic = "force-dynamic";

type RuntimeCard = {
  title: string;
  value: string;
  note: string;
  state: SignalState;
};

function toPercent(value: unknown): string {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "--";
  }
  return `${(value * 100).toFixed(1)}%`;
}

function toCompact(value: unknown): string {
  if (typeof value === "number" && Number.isFinite(value)) {
    return String(value);
  }
  return "--";
}

function toState(raw: unknown): SignalState {
  const text = String(raw || "unknown").toLowerCase();
  if (text === "ok" || text === "healthy") {
    return "healthy";
  }
  if (text === "warning" || text === "near_expiry") {
    return "warning";
  }
  if (text === "critical" || text === "expired") {
    return "critical";
  }
  return "unknown";
}

export default async function RuntimePosturePage() {
  const payload = await fetchRuntimePosture();
  const metrics = payload?.data?.metrics || {};

  const cards: RuntimeCard[] = [
    {
      title: "Runtime Rollout",
      value: toPercent(metrics.runtime_rollout?.value),
      note: "SubAgent decision hit ratio",
      state: toState(metrics.runtime_rollout?.status),
    },
    {
      title: "Fail Open",
      value: toPercent(metrics.runtime_fail_open?.value),
      note: "Current fail-open ratio",
      state: toState(metrics.runtime_fail_open?.status),
    },
    {
      title: "Lease",
      value: String(metrics.runtime_lease?.state || "missing").toUpperCase(),
      note: "Global orchestrator lease state",
      state: toState(metrics.runtime_lease?.status),
    },
    {
      title: "Queue Depth",
      value: toCompact(metrics.queue_depth?.value),
      note: "Pending outbox events",
      state: toState(metrics.queue_depth?.status),
    },
    {
      title: "Lock Status",
      value: String(metrics.lock_status?.state || "unknown").toUpperCase(),
      note: "Global mutex lock health",
      state: toState(metrics.lock_status?.status),
    },
    {
      title: "Disk Watermark",
      value: toPercent(metrics.disk_watermark_ratio?.value),
      note: "Artifact storage usage ratio",
      state: toState(metrics.disk_watermark_ratio?.status),
    },
  ];

  return (
    <div className="space-y-6">
      <section className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        {cards.map((card) => (
          <SignalCard key={card.title} title={card.title} value={card.value} note={card.note} state={card.state} />
        ))}
      </section>

      <section className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <article className="glass-card p-6">
          <p className="text-[10px] font-bold uppercase tracking-[0.25em] text-gray-500">Data Sources</p>
          <ul className="mt-4 space-y-2 text-sm text-gray-700">
            {(payload?.source_reports || []).map((path) => (
              <li key={path} className="rounded-xl bg-white/70 px-3 py-2 font-mono text-xs">
                {path}
              </li>
            ))}
            {(!payload || (payload.source_reports || []).length === 0) && (
              <li className="rounded-xl bg-white/70 px-3 py-2 text-xs text-gray-500">No source report detected.</li>
            )}
          </ul>
        </article>

        <article className="glass-card p-6">
          <p className="text-[10px] font-bold uppercase tracking-[0.25em] text-gray-500">Current Summary</p>
          <pre className="mt-4 overflow-auto rounded-2xl bg-[#1c1c1e] p-4 text-xs text-gray-100">
            {JSON.stringify(payload?.data?.summary || { overall_status: "unknown" }, null, 2)}
          </pre>
        </article>
      </section>
    </div>
  );
}
