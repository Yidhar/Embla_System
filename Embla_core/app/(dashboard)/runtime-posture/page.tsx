import { SignalCard, type SignalState } from "@/components/cards/signal-card";
import { MetricBar, type MetricBarTone } from "@/components/charts/metric-bar";
import { fetchRuntimePosture } from "@/lib/api/ops";

export const dynamic = "force-dynamic";

type RuntimeCard = {
  title: string;
  value: string;
  note: string;
  state: SignalState;
};

function asRecord(value: unknown): Record<string, unknown> {
  if (typeof value === "object" && value !== null) {
    return value as Record<string, unknown>;
  }
  return {};
}

function asNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  return null;
}

function asText(value: unknown, fallback = "--"): string {
  if (typeof value === "string" && value.trim()) {
    return value;
  }
  if (typeof value === "number" && Number.isFinite(value)) {
    return String(value);
  }
  return fallback;
}

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

function toTone(state: SignalState): MetricBarTone {
  if (state === "healthy") {
    return "healthy";
  }
  if (state === "warning") {
    return "warning";
  }
  if (state === "critical") {
    return "critical";
  }
  return "unknown";
}

export default async function RuntimePosturePage() {
  const payload = await fetchRuntimePosture();
  const metrics = asRecord(payload?.data?.metrics);
  const runtimeRollout = asRecord(metrics.runtime_rollout);
  const runtimeFailOpen = asRecord(metrics.runtime_fail_open);
  const runtimeLease = asRecord(metrics.runtime_lease);
  const queueDepth = asRecord(metrics.queue_depth);
  const lockStatus = asRecord(metrics.lock_status);
  const diskWatermark = asRecord(metrics.disk_watermark_ratio);
  const sources = asRecord(payload?.data?.sources);

  const rolloutValue = asNumber(runtimeRollout.value);
  const failOpenValue = asNumber(runtimeFailOpen.value);
  const failOpenBudget = asNumber(runtimeFailOpen.configured_budget_ratio);
  const diskUsage = asNumber(diskWatermark.value);
  const queuePending = asNumber(queueDepth.value);
  const queueCritical = asNumber(asRecord(queueDepth.thresholds).critical);
  const queueRatio = queuePending !== null && queueCritical && queueCritical > 0 ? queuePending / queueCritical : null;

  const cards: RuntimeCard[] = [
    {
      title: "Runtime Rollout",
      value: toPercent(rolloutValue),
      note: "SubAgent decision hit ratio",
      state: toState(runtimeRollout.status),
    },
    {
      title: "Fail Open",
      value: toPercent(failOpenValue),
      note: "Current fail-open ratio",
      state: toState(runtimeFailOpen.status),
    },
    {
      title: "Lease",
      value: String(runtimeLease.state || "missing").toUpperCase(),
      note: "Global orchestrator lease state",
      state: toState(runtimeLease.status),
    },
    {
      title: "Queue Depth",
      value: toCompact(queuePending),
      note: "Pending outbox events",
      state: toState(queueDepth.status),
    },
    {
      title: "Lock Status",
      value: String(lockStatus.state || "unknown").toUpperCase(),
      note: "Global mutex lock health",
      state: toState(lockStatus.status),
    },
    {
      title: "Disk Watermark",
      value: toPercent(diskUsage),
      note: "Artifact storage usage ratio",
      state: toState(diskWatermark.status),
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
          <p className="text-[10px] font-bold uppercase tracking-[0.25em] text-gray-500">Runtime Budget & Pressure</p>
          <div className="mt-4 grid grid-cols-1 gap-3">
            <MetricBar
              label="Rollout Hit Ratio"
              value={toPercent(rolloutValue)}
              ratio={rolloutValue}
              tone={toTone(toState(runtimeRollout.status))}
              hint={`Total decisions: ${asText(runtimeRollout.total_decisions)}`}
            />
            <MetricBar
              label="Fail-Open Usage"
              value={toPercent(failOpenValue)}
              ratio={failOpenValue}
              tone={toTone(toState(runtimeFailOpen.status))}
              right={<span>Budget {toPercent(failOpenBudget)}</span>}
              hint={`Blocked: ${asText(runtimeFailOpen.fail_open_blocked_count)}`}
            />
            <MetricBar
              label="Queue Pressure"
              value={toCompact(queuePending)}
              ratio={queueRatio}
              tone={toTone(toState(queueDepth.status))}
              right={<span>Critical {toCompact(queueCritical)}</span>}
              hint={`Oldest pending age: ${toCompact(queueDepth.oldest_pending_age_seconds)}s`}
            />
            <MetricBar
              label="Disk Usage"
              value={toPercent(diskUsage)}
              ratio={diskUsage}
              tone={toTone(toState(diskWatermark.status))}
              right={<span>{toCompact(diskWatermark.filesystem_free_gb)} GB free</span>}
            />
          </div>
        </article>

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
          <div className="mt-4 rounded-xl bg-white/70 p-3 text-xs text-gray-600">
            events_scanned: <span className="font-bold">{asText(sources.events_scanned)}</span>
          </div>
        </article>

      </section>

      <section className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <article className="glass-card p-6">
          <p className="text-[10px] font-bold uppercase tracking-[0.25em] text-gray-500">Lease Guard</p>
          <div className="mt-4 space-y-2 text-xs text-gray-700">
            <p className="rounded-xl bg-white/70 px-3 py-2">State: {asText(runtimeLease.state).toUpperCase()}</p>
            <p className="rounded-xl bg-white/70 px-3 py-2">Owner: {asText(runtimeLease.owner_id, "none")}</p>
            <p className="rounded-xl bg-white/70 px-3 py-2">Fencing Epoch: {asText(runtimeLease.fencing_epoch)}</p>
            <p className="rounded-xl bg-white/70 px-3 py-2">
              Seconds To Expiry: {toCompact(runtimeLease.value)}
            </p>
          </div>
        </article>

        <article className="glass-card p-6">
          <p className="text-[10px] font-bold uppercase tracking-[0.25em] text-gray-500">Summary Snapshot</p>
          <pre className="mt-4 overflow-auto rounded-2xl bg-[#1c1c1e] p-4 text-xs text-gray-100">
            {JSON.stringify(payload?.data?.summary || { overall_status: "unknown" }, null, 2)}
          </pre>
        </article>
      </section>
    </div>
  );
}
