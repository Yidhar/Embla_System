const API_BASE = (process.env.NEXT_PUBLIC_API_BASE || "").replace(/\/$/, "");

function withBase(path: string): string {
  return API_BASE ? `${API_BASE}${path}` : path;
}

export type DebugHealthPayload = {
  status?: string;
  agent_ready?: boolean;
  timestamp?: string;
};

export type DebugSystemInfoPayload = {
  version?: string;
  status?: string;
  available_services?: string[];
  api_key_configured?: boolean;
};

export type DebugChatReply = {
  status?: string;
  response?: string;
  reasoning_content?: string;
  session_id?: string;
};

export async function fetchDebugHealth(): Promise<DebugHealthPayload | null> {
  try {
    const response = await fetch(withBase("/v1/health"), {
      cache: "no-store",
      headers: { Accept: "application/json" },
    });
    if (!response.ok) {
      return null;
    }
    return (await response.json()) as DebugHealthPayload;
  } catch {
    return null;
  }
}

export async function fetchDebugSystemInfo(): Promise<DebugSystemInfoPayload | null> {
  try {
    const response = await fetch(withBase("/v1/system/info"), {
      cache: "no-store",
      headers: { Accept: "application/json" },
    });
    if (!response.ok) {
      return null;
    }
    return (await response.json()) as DebugSystemInfoPayload;
  } catch {
    return null;
  }
}

export async function sendDebugChatMessage(params: {
  message: string;
  sessionId?: string;
}): Promise<{ ok: boolean; data: DebugChatReply | null; error: string }> {
  try {
    const response = await fetch(withBase("/v1/chat"), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify({
        message: params.message,
        stream: false,
        session_id: params.sessionId || null,
        disable_tts: true,
        skip_intent_analysis: true,
        temporary: true,
      }),
    });
    if (!response.ok) {
      return { ok: false, data: null, error: `HTTP ${response.status}` };
    }
    const payload = (await response.json()) as DebugChatReply;
    if (!payload || payload.status !== "success") {
      return { ok: false, data: payload || null, error: "invalid response" };
    }
    return { ok: true, data: payload, error: "" };
  } catch (error) {
    return { ok: false, data: null, error: String(error || "network error") };
  }
}
