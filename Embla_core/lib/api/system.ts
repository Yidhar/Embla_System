const API_BASE = (process.env.NEXT_PUBLIC_API_BASE || "").replace(/\/$/, "");

function withBase(path: string): string {
  return API_BASE ? `${API_BASE}${path}` : path;
}

type SystemConfigResponse = {
  status?: string;
  config?: Record<string, unknown>;
  message?: string;
};

export async function fetchSystemConfig(): Promise<Record<string, unknown> | null> {
  try {
    const response = await fetch(withBase("/system/config"), {
      cache: "no-store",
      headers: {
        Accept: "application/json",
      },
    });
    if (!response.ok) {
      return null;
    }
    const payload = (await response.json()) as SystemConfigResponse;
    if (!payload || payload.status !== "success" || typeof payload.config !== "object" || payload.config === null) {
      return null;
    }
    return payload.config;
  } catch {
    return null;
  }
}

export async function updateSystemConfig(payload: Record<string, unknown>): Promise<{ ok: boolean; message: string }> {
  try {
    const response = await fetch(withBase("/system/config"), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      return { ok: false, message: `HTTP ${response.status}` };
    }
    const result = (await response.json()) as SystemConfigResponse;
    return {
      ok: result?.status === "success",
      message: String(result?.message || (result?.status === "success" ? "ok" : "update failed")),
    };
  } catch (error) {
    return { ok: false, message: String(error || "network error") };
  }
}
