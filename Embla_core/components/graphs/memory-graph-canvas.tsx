"use client";

import { useMemo, useState } from "react";
import type { MemoryGraphRow } from "@/lib/types/ops";

type GraphNode = {
  id: string;
  kind: "subject" | "object";
  count: number;
  typeLabel: string;
  x: number;
  y: number;
};

type GraphEdge = {
  id: string;
  from: string;
  to: string;
  predicate: string;
};

function hashHue(text: string): number {
  let value = 0;
  for (let i = 0; i < text.length; i += 1) {
    value = (value * 31 + text.charCodeAt(i)) % 360;
  }
  return value;
}

function buildGraph(rows: MemoryGraphRow[], maxEdges: number): { nodes: GraphNode[]; edges: GraphEdge[]; predicates: string[] } {
  const edges: GraphEdge[] = [];
  const nodeMap = new Map<string, { kind: "subject" | "object"; count: number; typeLabel: string }>();

  for (const [idx, row] of rows.slice(0, maxEdges).entries()) {
    const subject = (row.subject || "").trim();
    const object = (row.object || "").trim();
    const predicate = (row.predicate || "unknown").trim() || "unknown";
    if (!subject || !object) {
      continue;
    }

    const fromId = `s:${subject}`;
    const toId = `o:${object}`;

    const from = nodeMap.get(fromId) || { kind: "subject", count: 0, typeLabel: row.subject_type || "subject" };
    from.count += 1;
    nodeMap.set(fromId, from);

    const to = nodeMap.get(toId) || { kind: "object", count: 0, typeLabel: row.object_type || "object" };
    to.count += 1;
    nodeMap.set(toId, to);

    edges.push({
      id: `e:${idx}:${fromId}:${predicate}:${toId}`,
      from: fromId,
      to: toId,
      predicate,
    });
  }

  const keys = [...nodeMap.keys()];
  const centerX = 460;
  const centerY = 250;
  const nodes: GraphNode[] = keys.map((id, index) => {
    const base = nodeMap.get(id)!;
    const angle = (Math.PI * 2 * index) / Math.max(1, keys.length);
    const radius = 120 + (index % 4) * 35;
    return {
      id,
      kind: base.kind,
      count: base.count,
      typeLabel: base.typeLabel,
      x: centerX + Math.cos(angle) * radius,
      y: centerY + Math.sin(angle) * radius,
    };
  });

  const predicates = Array.from(new Set(edges.map((edge) => edge.predicate))).sort();
  return { nodes, edges, predicates };
}

export function MemoryGraphCanvas({ rows }: { rows: MemoryGraphRow[] }) {
  const [keyword, setKeyword] = useState("");
  const [predicateFilter, setPredicateFilter] = useState("all");
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [edgeLimit, setEdgeLimit] = useState(120);

  const normalizedKeyword = keyword.trim().toLowerCase();
  const filteredRows = useMemo(() => {
    return rows.filter((row) => {
      if (predicateFilter !== "all" && row.predicate !== predicateFilter) {
        return false;
      }
      if (!normalizedKeyword) {
        return true;
      }
      const target = `${row.subject} ${row.predicate} ${row.object}`.toLowerCase();
      return target.includes(normalizedKeyword);
    });
  }, [rows, predicateFilter, normalizedKeyword]);

  const graph = useMemo(() => buildGraph(filteredRows, edgeLimit), [filteredRows, edgeLimit]);
  const nodeById = useMemo(() => {
    return new Map(graph.nodes.map((node) => [node.id, node]));
  }, [graph.nodes]);

  const highlightedEdgeIds = useMemo(() => {
    if (!selectedNodeId) {
      return new Set<string>();
    }
    return new Set(graph.edges.filter((edge) => edge.from === selectedNodeId || edge.to === selectedNodeId).map((edge) => edge.id));
  }, [graph.edges, selectedNodeId]);

  const connectedNodeIds = useMemo(() => {
    if (highlightedEdgeIds.size === 0) {
      return new Set<string>();
    }
    const ids = new Set<string>();
    for (const edge of graph.edges) {
      if (!highlightedEdgeIds.has(edge.id)) {
        continue;
      }
      ids.add(edge.from);
      ids.add(edge.to);
    }
    return ids;
  }, [graph.edges, highlightedEdgeIds]);

  const selectedNode = selectedNodeId ? nodeById.get(selectedNodeId) : null;

  return (
    <div className="rounded-3xl border border-gray-200/70 bg-white/70 p-4">
      <div className="mb-4 grid grid-cols-1 gap-3 md:grid-cols-4">
        <label className="md:col-span-2">
          <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-gray-500">Keyword</p>
          <input
            value={keyword}
            onChange={(event) => setKeyword(event.target.value)}
            placeholder="subject / predicate / object"
            className="mt-1 h-10 w-full rounded-xl border border-white/70 bg-white/85 px-3 text-sm outline-none"
          />
        </label>
        <label>
          <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-gray-500">Predicate</p>
          <select
            value={predicateFilter}
            onChange={(event) => setPredicateFilter(event.target.value)}
            className="mt-1 h-10 w-full rounded-xl border border-white/70 bg-white/85 px-3 text-sm outline-none"
          >
            <option value="all">All</option>
            {graph.predicates.map((predicate) => (
              <option key={predicate} value={predicate}>
                {predicate}
              </option>
            ))}
          </select>
        </label>
        <label>
          <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-gray-500">Edges</p>
          <input
            type="range"
            min={20}
            max={400}
            step={10}
            value={edgeLimit}
            onChange={(event) => setEdgeLimit(Number(event.target.value))}
            className="mt-4 w-full"
          />
        </label>
      </div>

      <div className="overflow-auto rounded-2xl border border-gray-200/60 bg-[#f9f9fb]">
        <svg viewBox="0 0 920 500" className="h-[420px] min-w-[920px] w-full">
          {graph.edges.map((edge) => {
            const from = nodeById.get(edge.from);
            const to = nodeById.get(edge.to);
            if (!from || !to) {
              return null;
            }
            const highlighted = highlightedEdgeIds.size === 0 || highlightedEdgeIds.has(edge.id);
            const hue = hashHue(edge.predicate);
            return (
              <line
                key={edge.id}
                x1={from.x}
                y1={from.y}
                x2={to.x}
                y2={to.y}
                stroke={`hsl(${hue}, 55%, ${highlighted ? "45%" : "75%"})`}
                strokeOpacity={highlighted ? 0.8 : 0.25}
                strokeWidth={highlighted ? 1.8 : 1}
              />
            );
          })}

          {graph.nodes.map((node) => {
            const active = selectedNodeId === node.id;
            const connected = highlightedEdgeIds.size === 0 || connectedNodeIds.has(node.id);
            return (
              <g key={node.id} onClick={() => setSelectedNodeId(active ? null : node.id)} className="cursor-pointer">
                <circle
                  cx={node.x}
                  cy={node.y}
                  r={Math.max(8, Math.min(24, 8 + node.count * 1.2))}
                  fill={node.kind === "subject" ? "#1C1C1E" : "#6B7280"}
                  fillOpacity={connected ? 0.9 : 0.3}
                  stroke={active ? "#111827" : "rgba(255,255,255,0.7)"}
                  strokeWidth={active ? 2.5 : 1.4}
                />
                <text
                  x={node.x}
                  y={node.y + 3}
                  textAnchor="middle"
                  fontSize="8"
                  fill="white"
                  fontWeight={700}
                >
                  {node.count}
                </text>
              </g>
            );
          })}
        </svg>
      </div>

      <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-3">
        <div className="rounded-xl bg-white/70 px-3 py-2 text-xs text-gray-700">
          Nodes: <span className="font-bold">{graph.nodes.length}</span>
        </div>
        <div className="rounded-xl bg-white/70 px-3 py-2 text-xs text-gray-700">
          Edges: <span className="font-bold">{graph.edges.length}</span>
        </div>
        <div className="rounded-xl bg-white/70 px-3 py-2 text-xs text-gray-700">
          Selected: <span className="font-bold">{selectedNode?.id || "none"}</span>
        </div>
      </div>

      {selectedNode ? (
        <div className="mt-3 rounded-xl border border-gray-200/70 bg-white/80 p-3 text-xs text-gray-700">
          <p className="font-bold uppercase tracking-[0.2em] text-gray-500">Node Detail</p>
          <p className="mt-1 font-mono">{selectedNode.id}</p>
          <p className="mt-1">Type: {selectedNode.typeLabel || "unknown"}</p>
          <p>Degree Weight: {selectedNode.count}</p>
        </div>
      ) : null}
    </div>
  );
}
