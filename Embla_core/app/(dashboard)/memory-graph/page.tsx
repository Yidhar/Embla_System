import { SignalCard, type SignalState } from "@/components/cards/signal-card";
import { MemoryGraphCanvas } from "@/components/graphs/memory-graph-canvas";
import { fetchMemoryGraph } from "@/lib/api/ops";
import { formatNumber, resolveLangFromSearchParams, translateSignalState, type AppLang } from "@/lib/i18n";

export const dynamic = "force-dynamic";

type MemoryGraphPageProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

const PAGE_COPY: Record<
  AppLang,
  {
    cards: {
      quintuples: { title: string; note: string };
      activeTasks: { title: string; note: string };
      pendingTasks: { title: string; note: string };
      failedTasks: { title: string; note: string };
    };
    sections: {
      interactiveGraph: string;
      hotspots: string;
      relations: string;
      entities: string;
    };
    canvas: {
      keyword: string;
      keywordPlaceholder: string;
      predicate: string;
      predicateAll: string;
      edges: string;
      nodesCount: string;
      edgesCount: string;
      selected: string;
      none: string;
      nodeDetail: string;
      type: string;
      degreeWeight: string;
    };
  }
> = {
  en: {
    cards: {
      quintuples: { title: "Quintuples", note: "Total extracted memory tuples" },
      activeTasks: { title: "Active Tasks", note: "In-flight extraction tasks" },
      pendingTasks: { title: "Pending Tasks", note: "Task queue pending load" },
      failedTasks: { title: "Failed Tasks", note: "Extraction failures in task manager" },
    },
    sections: {
      interactiveGraph: "Interactive Graph",
      hotspots: "Hotspots",
      relations: "Relations",
      entities: "Entities",
    },
    canvas: {
      keyword: "Keyword",
      keywordPlaceholder: "subject / predicate / object",
      predicate: "Predicate",
      predicateAll: "All",
      edges: "Edges",
      nodesCount: "Nodes",
      edgesCount: "Edges",
      selected: "Selected",
      none: "none",
      nodeDetail: "Node Detail",
      type: "Type",
      degreeWeight: "Degree Weight",
    },
  },
  "zh-CN": {
    cards: {
      quintuples: { title: "五元组数量", note: "已提取的记忆五元组总量" },
      activeTasks: { title: "活跃任务", note: "正在执行的提取任务" },
      pendingTasks: { title: "排队任务", note: "等待处理的提取任务" },
      failedTasks: { title: "失败任务", note: "任务管理器中的提取失败数" },
    },
    sections: {
      interactiveGraph: "交互图谱",
      hotspots: "热点分布",
      relations: "关系",
      entities: "实体",
    },
    canvas: {
      keyword: "关键词",
      keywordPlaceholder: "subject / predicate / object",
      predicate: "关系谓词",
      predicateAll: "全部",
      edges: "边数",
      nodesCount: "节点",
      edgesCount: "边",
      selected: "选中",
      none: "无",
      nodeDetail: "节点详情",
      type: "类型",
      degreeWeight: "连接权重",
    },
  },
};

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

export default async function MemoryGraphPage({ searchParams }: MemoryGraphPageProps) {
  const lang = await resolveLangFromSearchParams(searchParams);
  const copy = PAGE_COPY[lang];
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
          title={copy.cards.quintuples.title}
          value={formatNumber(totalQuintuples, lang, { maximumFractionDigits: 0 })}
          note={copy.cards.quintuples.note}
          state={state}
          stateLabel={translateSignalState(state, lang)}
        />
        <SignalCard
          title={copy.cards.activeTasks.title}
          value={formatNumber(activeTasks, lang, { maximumFractionDigits: 0 })}
          note={copy.cards.activeTasks.note}
          state={state}
          stateLabel={translateSignalState(state, lang)}
        />
        <SignalCard
          title={copy.cards.pendingTasks.title}
          value={formatNumber(pendingTasks, lang, { maximumFractionDigits: 0 })}
          note={copy.cards.pendingTasks.note}
          state={state}
          stateLabel={translateSignalState(state, lang)}
        />
        <SignalCard
          title={copy.cards.failedTasks.title}
          value={formatNumber(failedTasks, lang, { maximumFractionDigits: 0 })}
          note={copy.cards.failedTasks.note}
          state={failedTasks > 0 ? "warning" : state}
          stateLabel={translateSignalState(failedTasks > 0 ? "warning" : state, lang)}
        />
      </section>

      <section className="grid grid-cols-1 gap-4 xl:grid-cols-5">
        <article className="glass-card col-span-3 p-6">
          <p className="text-[10px] font-bold uppercase tracking-[0.25em] text-gray-500">{copy.sections.interactiveGraph}</p>
          <div className="mt-4">
            <MemoryGraphCanvas rows={payload?.data?.graph_sample || []} text={copy.canvas} />
          </div>
        </article>

        <article className="glass-card col-span-2 p-6">
          <p className="text-[10px] font-bold uppercase tracking-[0.25em] text-gray-500">{copy.sections.hotspots}</p>
          <div className="mt-4 space-y-4">
            <section>
              <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-gray-500">{copy.sections.relations}</p>
              <ul className="mt-2 space-y-2">
                {(payload?.data?.relation_hotspots || []).slice(0, 8).map((item) => (
                  <li
                    key={`${item.relation}-${item.count}`}
                    className="flex items-center justify-between rounded-xl bg-white/70 px-3 py-2 text-xs"
                  >
                    <span>{item.relation || "-"}</span>
                    <span className="font-bold">{formatNumber(item.count, lang, { maximumFractionDigits: 0 })}</span>
                  </li>
                ))}
              </ul>
            </section>
            <section>
              <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-gray-500">{copy.sections.entities}</p>
              <ul className="mt-2 space-y-2">
                {(payload?.data?.entity_hotspots || []).slice(0, 8).map((item) => (
                  <li
                    key={`${item.entity}-${item.count}`}
                    className="flex items-center justify-between rounded-xl bg-white/70 px-3 py-2 text-xs"
                  >
                    <span>{item.entity || "-"}</span>
                    <span className="font-bold">{formatNumber(item.count, lang, { maximumFractionDigits: 0 })}</span>
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
