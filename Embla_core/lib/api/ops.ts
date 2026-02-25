import type {
  EvidenceIndexData,
  IncidentsLatestData,
  McpFabricData,
  MemoryGraphData,
  OpsEnvelope,
  RuntimePostureData,
  WorkflowEventsData,
} from "@/lib/types/ops";

const API_BASE = (process.env.NEXT_PUBLIC_API_BASE || "").replace(/\/$/, "");

function withBase(path: string): string {
  return API_BASE ? `${API_BASE}${path}` : path;
}

async function fetchOps<TData>(path: string): Promise<OpsEnvelope<TData> | null> {
  try {
    const response = await fetch(withBase(path), {
      cache: "no-store",
      headers: {
        Accept: "application/json",
      },
    });
    if (!response.ok) {
      return null;
    }
    return (await response.json()) as OpsEnvelope<TData>;
  } catch {
    return null;
  }
}

export async function fetchRuntimePosture(): Promise<OpsEnvelope<RuntimePostureData> | null> {
  return fetchOps<RuntimePostureData>("/v1/ops/runtime/posture");
}

export async function fetchMcpFabric(): Promise<OpsEnvelope<McpFabricData> | null> {
  return fetchOps<McpFabricData>("/v1/ops/mcp/fabric");
}

export async function fetchMemoryGraph(): Promise<OpsEnvelope<MemoryGraphData> | null> {
  return fetchOps<MemoryGraphData>("/v1/ops/memory/graph");
}

export async function fetchWorkflowEvents(): Promise<OpsEnvelope<WorkflowEventsData> | null> {
  return fetchOps<WorkflowEventsData>("/v1/ops/workflow/events");
}

export async function fetchIncidentsLatest(): Promise<OpsEnvelope<IncidentsLatestData> | null> {
  return fetchOps<IncidentsLatestData>("/v1/ops/incidents/latest");
}

export async function fetchEvidenceIndex(): Promise<OpsEnvelope<EvidenceIndexData> | null> {
  return fetchOps<EvidenceIndexData>("/v1/ops/evidence/index");
}
