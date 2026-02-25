import { SignalCard, type SignalState } from "@/components/cards/signal-card";
import { MetricBar, type MetricBarTone } from "@/components/charts/metric-bar";
import { fetchEvidenceIndex, fetchRuntimePosture } from "@/lib/api/ops";

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

function asArray(value: unknown): Record<string, unknown>[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter((item): item is Record<string, unknown> => typeof item === "object" && item !== null);
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

function toEvidenceState(status: unknown, gateLevel: unknown): SignalState {
  const normalizedStatus = String(status || "unknown").toLowerCase();
  const normalizedGate = String(gateLevel || "soft").toLowerCase();
  if (normalizedStatus === "passed") {
    return "healthy";
  }
  if (normalizedStatus === "failed" || normalizedStatus === "missing") {
    return normalizedGate === "hard" ? "critical" : "warning";
  }
  return "unknown";
}

function toneClassForState(state: SignalState): string {
  if (state === "healthy") {
    return "bg-emerald-100 text-emerald-700";
  }
  if (state === "critical") {
    return "bg-rose-100 text-rose-700";
  }
  if (state === "warning") {
    return "bg-amber-100 text-amber-700";
  }
  return "bg-slate-100 text-slate-700";
}

export default async function RuntimePosturePage() {
  const [payload, evidencePayload] = await Promise.all([fetchRuntimePosture(), fetchEvidenceIndex()]);
  const metrics = asRecord(payload?.data?.metrics);
  const runtimeRollout = asRecord(metrics.runtime_rollout);
  const runtimeFailOpen = asRecord(metrics.runtime_fail_open);
  const runtimeLease = asRecord(metrics.runtime_lease);
  const queueDepth = asRecord(metrics.queue_depth);
  const lockStatus = asRecord(metrics.lock_status);
  const diskWatermark = asRecord(metrics.disk_watermark_ratio);
  const sources = asRecord(payload?.data?.sources);

  const evidenceSummary = asRecord(evidencePayload?.data?.summary);
  const requiredReports = asArray(evidencePayload?.data?.required_reports);
  const recentReports = asArray(evidencePayload?.data?.recent_reports);

  const rolloutValue = asNumber(runtimeRollout.value);
  const failOpenValue = asNumber(runtimeFailOpen.value);
  const failOpenBudget = asNumber(runtimeFailOpen.configured_budget_ratio);
  const diskUsage = asNumber(diskWatermark.value);
  const queuePending = asNumber(queueDepth.value);
  const queueCritical = asNumber(asRecord(queueDepth.thresholds).critical);
  const queueRatio = queuePending !== null && queueCritical && queueCritical > 0 ? queuePending / queueCritical : null;

  const requiredTotal = asNumber(evidenceSummary.required_total);
  const requiredPresent = asNumber(evidenceSummary.required_present);
  const requiredPassed = asNumber(evidenceSummary.required_passed);
  const requiredMissing = asNumber(evidenceSummary.required_missing);
  const requiredFailed = asNumber(evidenceSummary.required_failed);
  const evidenceCoverageRatio =
    requiredTotal !== null && requiredTotal > 0 && requiredPresent !== null ? requiredPresent / requiredTotal : null;
  const evidencePassRatio =
    requiredTotal !== null && requiredTotal > 0 && requiredPassed !== null ? requiredPassed / requiredTotal : null;

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
          <p className="text-[10px] font-bold uppercase tracking-[0.25em] text-gray-500">M12 Evidence Gates</p>
          <div className="mt-4 grid grid-cols-1 gap-3">
            <MetricBar
              label="Evidence Coverage"
              value={`${toCompact(requiredPresent)}/${toCompact(requiredTotal)}`}
              ratio={evidenceCoverageRatio}
              tone={requiredMissing && requiredMissing > 0 ? "warning" : "healthy"}
              hint="Discovered required evidence reports"
            />
            <MetricBar
              label="Evidence Pass Ratio"
              value={`${toCompact(requiredPassed)}/${toCompact(requiredTotal)}`}
              ratio={evidencePassRatio}
              tone={requiredFailed && requiredFailed > 0 ? "critical" : "healthy"}
              right={<span>Failed {toCompact(requiredFailed)}</span>}
              hint="Required reports currently in passed state"
            />
          </div>
          <div className="mt-4 grid grid-cols-2 gap-2">
            <div className="rounded-xl bg-white/70 px-3 py-2 text-xs text-gray-700">
              Missing: <span className="font-bold">{toCompact(requiredMissing)}</span>
            </div>
            <div className="rounded-xl bg-white/70 px-3 py-2 text-xs text-gray-700">
              Failed: <span className="font-bold">{toCompact(requiredFailed)}</span>
            </div>
          </div>
        </article>

        <article className="glass-card p-6">
          <p className="text-[10px] font-bold uppercase tracking-[0.25em] text-gray-500">Required Evidence Reports</p>
          <ul className="mt-4 space-y-2 text-xs text-gray-700">
            {requiredReports.slice(0, 12).map((item) => {
              const status = String(item.status || "unknown");
              const gateLevel = String(item.gate_level || "soft");
              const state = toEvidenceState(status, gateLevel);
              return (
                <li key={String(item.id || "report")} className="rounded-xl bg-white/70 px-3 py-2">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-bold">{String(item.label || item.id || "unknown")}</span>
                    <span
                      className={`rounded-lg px-2 py-1 text-[10px] font-bold uppercase tracking-[0.16em] ${toneClassForState(state)}`}
                    >
                      {gateLevel}/{status}
                    </span>
                  </div>
                  <p className="mt-1 font-mono text-[10px] text-gray-500">{String(item.path || "")}</p>
                </li>
              );
            })}
            {requiredReports.length === 0 ? (
              <li className="rounded-xl bg-white/70 px-3 py-2 text-xs text-gray-500">No evidence report indexed.</li>
            ) : null}
          </ul>
        </article>
      </section>

      <section className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <article className="glass-card p-6">
          <p className="text-[10px] font-bold uppercase tracking-[0.25em] text-gray-500">Lease Guard</p>
          <div className="mt-4 space-y-2 text-xs text-gray-700">
            <p className="rounded-xl bg-white/70 px-3 py-2">State: {asText(runtimeLease.state).toUpperCase()}</p>
            <p className="rounded-xl bg-white/70 px-3 py-2">Owner: {asText(runtimeLease.owner_id, "none")}</p>
            <p className="rounded-xl bg-white/70 px-3 py-2">Fencing Epoch: {asText(runtimeLease.fencing_epoch)}</p>
            <p className="rounded-xl bg-white/70 px-3 py-2">Seconds To Expiry: {toCompact(runtimeLease.value)}</p>
          </div>
        </article>

        <article className="glass-card p-6">
          <p className="text-[10px] font-bold uppercase tracking-[0.25em] text-gray-500">Summary Snapshot</p>
          <pre className="mt-4 overflow-auto rounded-2xl bg-[#1c1c1e] p-4 text-xs text-gray-100">
            {JSON.stringify(payload?.data?.summary || { overall_status: "unknown" }, null, 2)}
          </pre>
        </article>
      </section>

      <section className="grid grid-cols-1 gap-4">
        <article className="glass-card p-6">
          <p className="text-[10px] font-bold uppercase tracking-[0.25em] text-gray-500">Recent Evidence Files</p>
          <div className="mt-4 grid grid-cols-1 gap-2 md:grid-cols-2">
            {recentReports.slice(0, 12).map((item) => (
              <div key={String(item.path || item.name || "report")} className="rounded-xl bg-white/70 px-3 py-2 text-xs text-gray-700">
                <p className="font-bold">{String(item.name || "unknown")}</p>
                <p className="mt-1 font-mono text-[10px] text-gray-500">{String(item.modified_at || "--")}</p>
              </div>
            ))}
            {recentReports.length === 0 ? (
              <div className="rounded-xl bg-white/70 px-3 py-2 text-xs text-gray-500">No recent evidence file.</div>
            ) : null}
          </div>
        </article>
      </section>
    </div>
  );
}
