import { buildApiUrl, getApiBaseCandidates } from "@/lib/api/frontend-api-base";

type SystemConfigResponse = {
  status?: string;
  config?: Record<string, unknown>;
  message?: string;
};

export async function fetchSystemConfig(): Promise<Record<string, unknown> | null> {
  const candidates = getApiBaseCandidates({
    includeRelative: true,
    includeServerInternalFallback: true,
  });
  for (const base of candidates) {
    try {
      const response = await fetch(buildApiUrl("/system/config", base), {
        cache: "no-store",
        headers: {
          Accept: "application/json",
        },
      });
      if (!response.ok) {
        continue;
      }
      const payload = (await response.json()) as SystemConfigResponse;
      if (!payload || payload.status !== "success" || typeof payload.config !== "object" || payload.config === null) {
        continue;
      }
      return payload.config;
    } catch {
      continue;
    }
  }
  return null;
}

export async function updateSystemConfig(payload: Record<string, unknown>): Promise<{ ok: boolean; message: string }> {
  const candidates = getApiBaseCandidates({
    includeRelative: true,
    includeServerInternalFallback: true,
  });
  for (const base of candidates) {
    try {
      const response = await fetch(buildApiUrl("/system/config", base), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        continue;
      }
      const result = (await response.json()) as SystemConfigResponse;
      return {
        ok: result?.status === "success",
        message: String(result?.message || (result?.status === "success" ? "ok" : "update failed")),
      };
    } catch {
      continue;
    }
  }
  return { ok: false, message: "network error" };
}
