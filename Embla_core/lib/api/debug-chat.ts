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
  route_decision?: DebugRouteDecision;
};

export type DebugRouteDecision = {
  type?: string;
  path?: string;
  risk_level?: string;
  prompt_profile?: string;
  injection_mode?: string;
  delegation_intent?: string;
  path_b_clarify_turns?: number;
  path_b_clarify_limit?: number;
  path_b_budget_escalated?: boolean;
  path_b_budget_reason?: string;
  outer_session_id?: string;
  core_session_id?: string;
  execution_session_id?: string;
  core_session_created?: boolean;
};

export type DebugRouteBridgeEvent = {
  timestamp?: string;
  event_type?: string;
  path?: string;
  trigger?: string;
  delegation_intent?: string;
  prompt_profile?: string;
  injection_mode?: string;
  outer_session_id?: string;
  core_session_id?: string;
  execution_session_id?: string;
  path_b_budget_escalated?: boolean;
  path_b_budget_reason?: string;
  path_b_clarify_turns?: number;
  path_b_clarify_limit?: number;
  core_session_created?: boolean;
  source?: string;
};

export type DebugRouteBridgePayload = {
  status?: string;
  outer_session_id?: string;
  core_session_id?: string;
  execution_session_id?: string;
  outer_session_exists?: boolean;
  core_session_exists?: boolean;
  state?: {
    path_b_clarify_turns?: number;
    path_b_clarify_limit?: number;
    last_execution_session_id?: string;
    last_core_escalation_at_ms?: number;
  };
  recent_route_events?: DebugRouteBridgeEvent[];
};

function decodeBase64Json(data: string): { ok: boolean; payload: Record<string, unknown> | null } {
  try {
    const binary = atob(data);
    const bytes = new Uint8Array(binary.length);
    for (let idx = 0; idx < binary.length; idx += 1) {
      bytes[idx] = binary.charCodeAt(idx);
    }
    const decoded = new TextDecoder().decode(bytes);
    const payload = JSON.parse(decoded) as Record<string, unknown>;
    if (!payload || typeof payload !== "object") {
      return { ok: false, payload: null };
    }
    return { ok: true, payload };
  } catch {
    return { ok: false, payload: null };
  }
}

function parseSseBlock(lines: string[]): string[] {
  const dataLines: string[] = [];
  for (const line of lines) {
    if (!line.startsWith("data:")) {
      continue;
    }
    dataLines.push(line.slice(5).trim());
  }
  return dataLines;
}

export type PromptTemplateMeta = {
  name: string;
  filename?: string;
  size_bytes?: number;
  updated_at?: string;
};

export type PromptTemplatePayload = {
  status?: string;
  name?: string;
  content?: string;
  meta?: PromptTemplateMeta;
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
    const response = await fetch(withBase("/v1/chat/stream"), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
      },
      body: JSON.stringify({
        message: params.message,
        stream: true,
        session_id: params.sessionId || null,
        disable_tts: true,
        skip_intent_analysis: true,
        temporary: true,
      }),
    });
    if (!response.ok) {
      return { ok: false, data: null, error: `HTTP ${response.status}` };
    }
    if (!response.body) {
      return { ok: false, data: null, error: "empty stream body" };
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let streamBuffer = "";
    let sessionId = String(params.sessionId || "").trim();
    let content = "";
    let reasoning = "";
    let routeDecision: DebugRouteDecision | undefined;
    let streamError = "";
    const applyDataLine = (dataText: string) => {
      if (!dataText || dataText === "[DONE]") {
        return;
      }
      if (dataText.startsWith("session_id:")) {
        sessionId = dataText.slice("session_id:".length).trim() || sessionId;
        return;
      }
      if (dataText.startsWith("error:")) {
        streamError = dataText.slice("error:".length).trim();
        return;
      }
      const decoded = decodeBase64Json(dataText);
      if (!decoded.ok || !decoded.payload) {
        return;
      }
      const payload = decoded.payload;
      const type = String(payload.type || "");
      const text = String(payload.text || "");
      if (type === "content") {
        content += text;
      } else if (type === "reasoning") {
        reasoning += text;
      } else if (type === "route_decision") {
        routeDecision = payload as unknown as DebugRouteDecision;
      } else if (type === "error") {
        streamError = text || streamError;
      }
    };

    while (true) {
      const { value, done } = await reader.read();
      if (done) {
        break;
      }
      streamBuffer += decoder.decode(value, { stream: true });
      while (true) {
        const splitIndex = streamBuffer.indexOf("\n\n");
        if (splitIndex < 0) {
          break;
        }
        const block = streamBuffer.slice(0, splitIndex);
        streamBuffer = streamBuffer.slice(splitIndex + 2);
        const dataItems = parseSseBlock(block.split("\n"));
        for (const dataText of dataItems) {
          applyDataLine(dataText);
        }
      }
    }
    if (streamBuffer.trim()) {
      const dataItems = parseSseBlock(streamBuffer.split("\n"));
      for (const dataText of dataItems) {
        applyDataLine(dataText);
      }
    }

    if (streamError) {
      return { ok: false, data: null, error: streamError };
    }
    return {
      ok: true,
      data: {
        status: "success",
        response: content,
        reasoning_content: reasoning,
        session_id: sessionId || undefined,
        route_decision: routeDecision,
      },
      error: "",
    };
  } catch (error) {
    return { ok: false, data: null, error: String(error || "network error") };
  }
}

export async function fetchDebugRouteBridge(params: {
  sessionId: string;
  limit?: number;
}): Promise<{ ok: boolean; data: DebugRouteBridgePayload | null; error: string }> {
  const sessionId = String(params.sessionId || "").trim();
  if (!sessionId) {
    return { ok: false, data: null, error: "missing session id" };
  }
  const limit = Number.isFinite(params.limit) ? Math.max(1, Math.trunc(params.limit as number)) : 20;
  try {
    const response = await fetch(withBase(`/v1/chat/route_bridge/${encodeURIComponent(sessionId)}?limit=${limit}`), {
      cache: "no-store",
      headers: { Accept: "application/json" },
    });
    if (!response.ok) {
      return { ok: false, data: null, error: `HTTP ${response.status}` };
    }
    const payload = (await response.json()) as DebugRouteBridgePayload;
    if (!payload || payload.status !== "success") {
      return { ok: false, data: payload || null, error: "invalid response" };
    }
    return { ok: true, data: payload, error: "" };
  } catch (error) {
    return { ok: false, data: null, error: String(error || "network error") };
  }
}

export async function fetchPromptTemplates(): Promise<{ ok: boolean; prompts: PromptTemplateMeta[]; error: string }> {
  try {
    const response = await fetch(withBase("/v1/system/prompts"), {
      cache: "no-store",
      headers: { Accept: "application/json" },
    });
    if (!response.ok) {
      return { ok: false, prompts: [], error: `HTTP ${response.status}` };
    }
    const payload = (await response.json()) as { status?: string; prompts?: PromptTemplateMeta[] };
    if (!payload || payload.status !== "success" || !Array.isArray(payload.prompts)) {
      return { ok: false, prompts: [], error: "invalid response" };
    }
    return { ok: true, prompts: payload.prompts, error: "" };
  } catch (error) {
    return { ok: false, prompts: [], error: String(error || "network error") };
  }
}

export async function fetchPromptTemplate(name: string): Promise<{ ok: boolean; data: PromptTemplatePayload | null; error: string }> {
  try {
    const response = await fetch(withBase(`/v1/system/prompts/${encodeURIComponent(name)}`), {
      cache: "no-store",
      headers: { Accept: "application/json" },
    });
    if (!response.ok) {
      return { ok: false, data: null, error: `HTTP ${response.status}` };
    }
    const payload = (await response.json()) as PromptTemplatePayload;
    if (!payload || payload.status !== "success") {
      return { ok: false, data: payload || null, error: "invalid response" };
    }
    return { ok: true, data: payload, error: "" };
  } catch (error) {
    return { ok: false, data: null, error: String(error || "network error") };
  }
}

export async function savePromptTemplate(params: {
  name: string;
  content: string;
}): Promise<{ ok: boolean; error: string }> {
  try {
    const response = await fetch(withBase(`/v1/system/prompts/${encodeURIComponent(params.name)}`), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify({ content: params.content }),
    });
    if (!response.ok) {
      return { ok: false, error: `HTTP ${response.status}` };
    }
    const payload = (await response.json()) as { status?: string; message?: string };
    if (!payload || payload.status !== "success") {
      return { ok: false, error: "invalid response" };
    }
    return { ok: true, error: "" };
  } catch (error) {
    return { ok: false, error: String(error || "network error") };
  }
}
