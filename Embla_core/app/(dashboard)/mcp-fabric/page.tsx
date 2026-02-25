import { SignalCard, type SignalState } from "@/components/cards/signal-card";
import { MetricBar, type MetricBarTone } from "@/components/charts/metric-bar";
import { fetchMcpFabric } from "@/lib/api/ops";
import { formatNumber, resolveLangFromSearchParams, translateSignalState, type AppLang } from "@/lib/i18n";

export const dynamic = "force-dynamic";

type McpFabricPageProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

const PAGE_COPY: Record<
  AppLang,
  {
    cards: {
      servicesTotal: { title: string; note: string };
      servicesAvailable: { title: string; note: string };
      builtinServices: { title: string; note: string };
      mcporterServices: { title: string; note: string };
      isolatedWorkers: { title: string; note: string };
      rejectedManifests: { title: string; note: string };
    };
    sections: {
      fabricCoverage: string;
      unavailableServices: string;
      servicesMatrix: string;
      registrySnapshot: string;
      registryRaw: string;
      builtin: string;
      mcporter: string;
    };
    columns: {
      name: string;
      source: string;
      available: string;
    };
    metrics: {
      availability: string;
      builtinShare: string;
      mcporterShare: string;
      availableHint: string;
      builtinHint: string;
      mcporterHint: string;
    };
    words: {
      yes: string;
      no: string;
      none: string;
      noServicesDiscovered: string;
    };
  }
> = {
  en: {
    cards: {
      servicesTotal: { title: "Services Total", note: "Total registered + configured" },
      servicesAvailable: { title: "Services Available", note: "Runtime availability" },
      builtinServices: { title: "Builtin Services", note: "In-process registry services" },
      mcporterServices: { title: "Mcporter Services", note: "External configured services" },
      isolatedWorkers: { title: "Isolated Workers", note: "Sandboxed plugin services" },
      rejectedManifests: { title: "Rejected Manifests", note: "Policy-rejected plugin manifests" },
    },
    sections: {
      fabricCoverage: "Fabric Coverage",
      unavailableServices: "Unavailable Services",
      servicesMatrix: "Services Matrix",
      registrySnapshot: "Registry Snapshot",
      registryRaw: "Registry Raw",
      builtin: "Builtin",
      mcporter: "Mcporter",
    },
    columns: {
      name: "Name",
      source: "Source",
      available: "Available",
    },
    metrics: {
      availability: "Availability",
      builtinShare: "Builtin Share",
      mcporterShare: "Mcporter Share",
      availableHint: "Available services over discovered services",
      builtinHint: "In-process registry services",
      mcporterHint: "External configured services",
    },
    words: {
      yes: "yes",
      no: "no",
      none: "none",
      noServicesDiscovered: "No services discovered yet.",
    },
  },
  "zh-CN": {
    cards: {
      servicesTotal: { title: "服务总量", note: "已注册与已配置服务总数" },
      servicesAvailable: { title: "可用服务", note: "运行时可用率" },
      builtinServices: { title: "内置服务", note: "进程内注册中心服务" },
      mcporterServices: { title: "Mcporter 服务", note: "外部配置服务" },
      isolatedWorkers: { title: "隔离 Worker", note: "沙箱化插件服务" },
      rejectedManifests: { title: "拒绝清单", note: "被策略拒绝的插件清单" },
    },
    sections: {
      fabricCoverage: "织网覆盖率",
      unavailableServices: "不可用服务",
      servicesMatrix: "服务矩阵",
      registrySnapshot: "注册中心快照",
      registryRaw: "注册中心原始数据",
      builtin: "内置",
      mcporter: "Mcporter",
    },
    columns: {
      name: "名称",
      source: "来源",
      available: "可用",
    },
    metrics: {
      availability: "可用率",
      builtinShare: "内置占比",
      mcporterShare: "Mcporter 占比",
      availableHint: "可用服务 / 已发现服务",
      builtinHint: "进程内注册中心服务",
      mcporterHint: "外部配置服务",
    },
    words: {
      yes: "是",
      no: "否",
      none: "无",
      noServicesDiscovered: "尚未发现可用服务。",
    },
  },
};

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

export default async function McpFabricPage({ searchParams }: McpFabricPageProps) {
  const lang = await resolveLangFromSearchParams(searchParams);
  const copy = PAGE_COPY[lang];
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
  const availableState = toState(available, total);

  const builtinServices = services.filter((item) => String(item.source || "").toLowerCase() === "builtin");
  const mcporterServices = services.filter((item) => String(item.source || "").toLowerCase() === "mcporter");
  const unavailableServices = services.filter((item) => !item.available);

  return (
    <div className="space-y-6">
      <section className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        <SignalCard
          title={copy.cards.servicesTotal.title}
          value={formatNumber(total, lang, { maximumFractionDigits: 0 })}
          note={copy.cards.servicesTotal.note}
          state={total > 0 ? "healthy" : "unknown"}
          stateLabel={translateSignalState(total > 0 ? "healthy" : "unknown", lang)}
        />
        <SignalCard
          title={copy.cards.servicesAvailable.title}
          value={`${formatNumber(available, lang, { maximumFractionDigits: 0 })}/${total || "--"}`}
          note={copy.cards.servicesAvailable.note}
          state={availableState}
          stateLabel={translateSignalState(availableState, lang)}
        />
        <SignalCard
          title={copy.cards.builtinServices.title}
          value={formatNumber(builtin, lang, { maximumFractionDigits: 0 })}
          note={copy.cards.builtinServices.note}
          state={builtin > 0 ? "healthy" : "unknown"}
          stateLabel={translateSignalState(builtin > 0 ? "healthy" : "unknown", lang)}
        />
        <SignalCard
          title={copy.cards.mcporterServices.title}
          value={formatNumber(mcporter, lang, { maximumFractionDigits: 0 })}
          note={copy.cards.mcporterServices.note}
          state={mcporter > 0 ? "healthy" : "unknown"}
          stateLabel={translateSignalState(mcporter > 0 ? "healthy" : "unknown", lang)}
        />
        <SignalCard
          title={copy.cards.isolatedWorkers.title}
          value={formatNumber(isolated, lang, { maximumFractionDigits: 0 })}
          note={copy.cards.isolatedWorkers.note}
          state={isolated > 0 ? "healthy" : "unknown"}
          stateLabel={translateSignalState(isolated > 0 ? "healthy" : "unknown", lang)}
        />
        <SignalCard
          title={copy.cards.rejectedManifests.title}
          value={formatNumber(rejected, lang, { maximumFractionDigits: 0 })}
          note={copy.cards.rejectedManifests.note}
          state={rejected > 0 ? "warning" : "healthy"}
          stateLabel={translateSignalState(rejected > 0 ? "warning" : "healthy", lang)}
        />
      </section>

      <section className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <article className="glass-card p-6">
          <p className="text-[10px] font-bold uppercase tracking-[0.25em] text-gray-500">{copy.sections.fabricCoverage}</p>
          <div className="mt-4 grid grid-cols-1 gap-3">
            <MetricBar
              label={copy.metrics.availability}
              value={`${formatNumber(available, lang, { maximumFractionDigits: 0 })}/${total || "--"}`}
              ratio={availabilityRatio}
              tone={toTone(availableState)}
              hint={copy.metrics.availableHint}
            />
            <MetricBar
              label={copy.metrics.builtinShare}
              value={formatNumber(builtin, lang, { maximumFractionDigits: 0 })}
              ratio={total > 0 ? builtin / total : null}
              tone="healthy"
              hint={copy.metrics.builtinHint}
            />
            <MetricBar
              label={copy.metrics.mcporterShare}
              value={formatNumber(mcporter, lang, { maximumFractionDigits: 0 })}
              ratio={total > 0 ? mcporter / total : null}
              tone="warning"
              hint={copy.metrics.mcporterHint}
            />
          </div>
          <div className="mt-4 rounded-xl bg-white/70 p-3 text-xs text-gray-700">
            <p className="font-bold uppercase tracking-[0.2em] text-gray-500">{copy.sections.unavailableServices}</p>
            <ul className="mt-2 space-y-1">
              {unavailableServices.slice(0, 10).map((service, idx) => (
                <li key={`${String(service.name || "unknown")}-${idx}`} className="font-mono">
                  {String(service.name || "unknown")} ({String(service.source || "n/a")})
                </li>
              ))}
              {unavailableServices.length === 0 ? <li>{copy.words.none}</li> : null}
            </ul>
          </div>
        </article>

        <article className="glass-card p-6">
          <p className="text-[10px] font-bold uppercase tracking-[0.25em] text-gray-500">{copy.sections.servicesMatrix}</p>
          <div className="mt-4 overflow-x-auto">
            <table className="min-w-full text-left text-xs text-gray-700">
              <thead>
                <tr className="border-b border-gray-200/70">
                  <th className="px-2 py-2 uppercase tracking-[0.2em]">{copy.columns.name}</th>
                  <th className="px-2 py-2 uppercase tracking-[0.2em]">{copy.columns.source}</th>
                  <th className="px-2 py-2 uppercase tracking-[0.2em]">{copy.columns.available}</th>
                </tr>
              </thead>
              <tbody>
                {(payload?.data?.services || []).map((service, idx) => (
                  <tr key={`${String(service.name || "unknown")}-${idx}`} className="border-b border-gray-100/70">
                    <td className="px-2 py-2 font-mono">{String(service.name || "unknown")}</td>
                    <td className="px-2 py-2 uppercase">{String(service.source || "n/a")}</td>
                    <td className="px-2 py-2">{String(service.available ? copy.words.yes : copy.words.no)}</td>
                  </tr>
                ))}
                {(!payload || (payload.data.services || []).length === 0) && (
                  <tr>
                    <td colSpan={3} className="px-2 py-3 text-gray-500">
                      {copy.words.noServicesDiscovered}
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
          <p className="text-[10px] font-bold uppercase tracking-[0.25em] text-gray-500">{copy.sections.registrySnapshot}</p>
          <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2">
            <div className="rounded-xl bg-white/70 p-3 text-xs">
              <p className="font-bold uppercase tracking-[0.2em] text-gray-500">{copy.sections.builtin}</p>
              <ul className="mt-2 space-y-1 text-gray-700">
                {builtinServices.slice(0, 12).map((service, idx) => (
                  <li key={`${String(service.name || "unknown")}-${idx}`} className="font-mono">
                    {String(service.name || "unknown")}
                  </li>
                ))}
              </ul>
            </div>
            <div className="rounded-xl bg-white/70 p-3 text-xs">
              <p className="font-bold uppercase tracking-[0.2em] text-gray-500">{copy.sections.mcporter}</p>
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
          <p className="text-[10px] font-bold uppercase tracking-[0.25em] text-gray-500">{copy.sections.registryRaw}</p>
          <pre className="mt-4 overflow-auto rounded-2xl bg-[#1c1c1e] p-4 text-xs text-gray-100">
            {JSON.stringify(registry || { registered_services: 0 }, null, 2)}
          </pre>
        </article>
      </section>
    </div>
  );
}
