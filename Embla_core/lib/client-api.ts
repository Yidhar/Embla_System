"use client";

const DEFAULT_API_PORT = process.env.NEXT_PUBLIC_API_PORT ?? "8000";

function trimTrailingSlash(value: string) {
  return value.replace(/\/+$/, "");
}

export function getBrowserApiBase() {
  const explicit = String(process.env.NEXT_PUBLIC_API_BASE ?? "").trim();
  if (explicit) {
    return trimTrailingSlash(explicit);
  }
  if (typeof window === "undefined") {
    return `http://127.0.0.1:${DEFAULT_API_PORT}`;
  }
  const protocol = window.location.protocol === "https:" ? "https:" : "http:";
  const hostname = window.location.hostname || "127.0.0.1";
  return `${protocol}//${hostname}:${DEFAULT_API_PORT}`;
}

export function buildBrowserApiUrl(endpoint: string) {
  const normalized = String(endpoint || "").trim();
  if (!normalized) {
    return getBrowserApiBase();
  }
  if (normalized.startsWith("http://") || normalized.startsWith("https://")) {
    return normalized;
  }
  const base = getBrowserApiBase();
  return `${base}${normalized.startsWith("/") ? normalized : `/${normalized}`}`;
}

export async function fetchBrowserJson<T>(endpoint: string, init?: RequestInit): Promise<T> {
  const response = await fetch(buildBrowserApiUrl(endpoint), {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  const payload = (await response.json()) as T;
  if (!response.ok) {
    throw new Error(extractApiErrorMessage(payload));
  }
  return payload;
}

export function extractApiErrorMessage(payload: unknown, fallback = "Request failed") {
  if (!payload || typeof payload !== "object") {
    return fallback;
  }
  const row = payload as Record<string, unknown>;
  const detail = row.detail;
  if (typeof detail === "string" && detail.trim()) {
    return detail.trim();
  }
  if (detail && typeof detail === "object") {
    const detailRow = detail as Record<string, unknown>;
    const message = String(detailRow.message ?? detailRow.reason ?? detailRow.code ?? "").trim();
    if (message) {
      return message;
    }
  }
  const message = String(row.message ?? row.reason_text ?? "").trim();
  return message || fallback;
}
