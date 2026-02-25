import type { McpFabricData, OpsEnvelope, RuntimePostureData } from "@/lib/types/ops";

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
