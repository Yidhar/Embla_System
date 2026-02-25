import { SignalCard, type SignalState } from "@/components/cards/signal-card";
import { MetricBar } from "@/components/charts/metric-bar";
import { fetchMcpFabric } from "@/lib/api/ops";

export const dynamic = "force-dynamic";

function toState(value: number, total: number): SignalState {
  if (total <= 0) {
    return "unknown";
  }
  if (value <= 0) {
    return "critical";
  }
  if (value < total) {
    return "warning";
  }
  return "healthy";
}

export default async function McpFabricPage() {
  const payload = await fetchMcpFabric();
  const summary = payload?.data?.summary;
  const services = payload?.data?.services || [];
  const registry = payload?.data?.registry || {};

  const total = summary?.total_services ?? 0;
  const available = summary?.available_services ?? 0;
  const builtin = summary?.builtin_services ?? 0;
  const mcporter = summary?.mcporter_services ?? 0;
  const isolated = summary?.isolated_worker_services ?? 0;
  const rejected = summary?.rejected_plugin_manifests ?? 0;
  const availabilityRatio = total > 0 ? available / total : null;

  const builtinServices = services.filter((item) => String(item.source || "").toLowerCase() === "builtin");
  const mcporterServices = services.filter((item) => String(item.source || "").toLowerCase() === "mcporter");
  const unavailableServices = services.filter((item) => !item.available);

  return (
    <div className="space-y-6">
      <section className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        <SignalCard
          title="Services Total"
          value={String(total)}
          note="Total registered + configured"
          state={total > 0 ? "healthy" : "unknown"}
        />
        <SignalCard
          title="Services Available"
          value={`${available}/${total || "--"}`}
          note="Runtime availability"
          state={toState(available, total)}
        />
        <SignalCard
          title="Builtin Services"
          value={String(builtin)}
          note="In-process registry services"
          state={builtin > 0 ? "healthy" : "unknown"}
        />
        <SignalCard
          title="Mcporter Services"
          value={String(mcporter)}
          note="External configured services"
          state={mcporter > 0 ? "healthy" : "unknown"}
        />
        <SignalCard
          title="Isolated Workers"
          value={String(isolated)}
          note="Sandboxed plugin services"
          state={isolated > 0 ? "healthy" : "unknown"}
        />
        <SignalCard
          title="Rejected Manifests"
          value={String(rejected)}
          note="Policy-rejected plugin manifests"
          state={rejected > 0 ? "warning" : "healthy"}
        />
      </section>

      <section className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <article className="glass-card p-6">
          <p className="text-[10px] font-bold uppercase tracking-[0.25em] text-gray-500">Fabric Coverage</p>
          <div className="mt-4 grid grid-cols-1 gap-3">
            <MetricBar
              label="Availability"
              value={`${available}/${total || "--"}`}
              ratio={availabilityRatio}
              tone={toState(available, total) === "healthy" ? "healthy" : toState(available, total) === "warning" ? "warning" : "critical"}
              hint="Available services over discovered services"
            />
            <MetricBar
              label="Builtin Share"
              value={`${builtin}`}
              ratio={total > 0 ? builtin / total : null}
              tone="healthy"
              hint="In-process registry services"
            />
            <MetricBar
              label="Mcporter Share"
              value={`${mcporter}`}
              ratio={total > 0 ? mcporter / total : null}
              tone="warning"
              hint="External configured services"
            />
          </div>
          <div className="mt-4 rounded-xl bg-white/70 p-3 text-xs text-gray-700">
            <p className="font-bold uppercase tracking-[0.2em] text-gray-500">Unavailable Services</p>
            <ul className="mt-2 space-y-1">
              {unavailableServices.slice(0, 10).map((service, idx) => (
                <li key={`${String(service.name || "unknown")}-${idx}`} className="font-mono">
                  {String(service.name || "unknown")} ({String(service.source || "n/a")})
                </li>
              ))}
              {unavailableServices.length === 0 ? <li>none</li> : null}
            </ul>
          </div>
        </article>

        <article className="glass-card p-6">
          <p className="text-[10px] font-bold uppercase tracking-[0.25em] text-gray-500">Services Matrix</p>
          <div className="mt-4 overflow-x-auto">
            <table className="min-w-full text-left text-xs text-gray-700">
              <thead>
                <tr className="border-b border-gray-200/70">
                  <th className="px-2 py-2 uppercase tracking-[0.2em]">Name</th>
                  <th className="px-2 py-2 uppercase tracking-[0.2em]">Source</th>
                  <th className="px-2 py-2 uppercase tracking-[0.2em]">Available</th>
                </tr>
              </thead>
              <tbody>
                {(payload?.data?.services || []).map((service, idx) => (
                  <tr key={`${String(service.name || "unknown")}-${idx}`} className="border-b border-gray-100/70">
                    <td className="px-2 py-2 font-mono">{String(service.name || "unknown")}</td>
                    <td className="px-2 py-2 uppercase">{String(service.source || "n/a")}</td>
                    <td className="px-2 py-2">{String(service.available ? "yes" : "no")}</td>
                  </tr>
                ))}
                {(!payload || (payload.data.services || []).length === 0) && (
                  <tr>
                    <td colSpan={3} className="px-2 py-3 text-gray-500">
                      No services discovered yet.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </article>
      </section>

      <section className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <article className="glass-card p-6 xl:col-span-2">
          <p className="text-[10px] font-bold uppercase tracking-[0.25em] text-gray-500">Registry Snapshot</p>
          <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2">
            <div className="rounded-xl bg-white/70 p-3 text-xs">
              <p className="font-bold uppercase tracking-[0.2em] text-gray-500">Builtin</p>
              <ul className="mt-2 space-y-1 text-gray-700">
                {builtinServices.slice(0, 12).map((service, idx) => (
                  <li key={`${String(service.name || "unknown")}-${idx}`} className="font-mono">
                    {String(service.name || "unknown")}
                  </li>
                ))}
              </ul>
            </div>
            <div className="rounded-xl bg-white/70 p-3 text-xs">
              <p className="font-bold uppercase tracking-[0.2em] text-gray-500">Mcporter</p>
              <ul className="mt-2 space-y-1 text-gray-700">
                {mcporterServices.slice(0, 12).map((service, idx) => (
                  <li key={`${String(service.name || "unknown")}-${idx}`} className="font-mono">
                    {String(service.name || "unknown")}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </article>
        <article className="glass-card p-6">
          <p className="text-[10px] font-bold uppercase tracking-[0.25em] text-gray-500">Registry Raw</p>
          <pre className="mt-4 overflow-auto rounded-2xl bg-[#1c1c1e] p-4 text-xs text-gray-100">
            {JSON.stringify(registry || { registered_services: 0 }, null, 2)}
          </pre>
        </article>
      </section>
    </div>
  );
}
