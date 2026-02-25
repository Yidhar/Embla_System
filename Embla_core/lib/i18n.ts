export type AppLang = "en" | "zh-CN";

export type SearchParamsLike = Record<string, string | string[] | undefined>;

const DEFAULT_LANG: AppLang = "en";

function firstParam(value: string | string[] | undefined): string {
  if (Array.isArray(value)) {
    return String(value[0] || "");
  }
  return String(value || "");
}

export function normalizeLang(value: unknown): AppLang {
  const raw = String(value || "").trim().toLowerCase();
  if (raw === "zh" || raw === "zh-cn" || raw === "zh_cn" || raw === "zh-hans") {
    return "zh-CN";
  }
  if (raw === "en" || raw === "en-us" || raw === "en_us") {
    return "en";
  }
  return DEFAULT_LANG;
}

export async function resolveLangFromSearchParams(value?: Promise<SearchParamsLike>): Promise<AppLang> {
  const resolved = value ? await value : {};
  return normalizeLang(firstParam(resolved.lang));
}

export function localeForLang(lang: AppLang): string {
  return lang === "zh-CN" ? "zh-CN" : "en-US";
}

export function formatNumber(
  value: unknown,
  lang: AppLang,
  options?: Intl.NumberFormatOptions & { fallback?: string },
): string {
  const fallback = options?.fallback || "--";
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return fallback;
  }
  const intlOptions = { ...(options || {}) } as Intl.NumberFormatOptions & { fallback?: string };
  delete intlOptions.fallback;
  return new Intl.NumberFormat(localeForLang(lang), intlOptions).format(value);
}

export function formatPercentRatio(
  value: unknown,
  lang: AppLang,
  fractionDigits = 1,
  fallback = "--",
): string {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return fallback;
  }
  return new Intl.NumberFormat(localeForLang(lang), {
    style: "percent",
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
  }).format(value);
}

export function formatIsoDateTime(value: unknown, lang: AppLang, fallback = "--"): string {
  const raw = String(value || "").trim();
  if (!raw) {
    return fallback;
  }
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) {
    return fallback;
  }
  return new Intl.DateTimeFormat(localeForLang(lang), {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
    timeZoneName: "short",
  }).format(date);
}

export function translateSignalState(state: string, lang: AppLang): string {
  const normalized = String(state || "unknown").toLowerCase();
  if (lang === "zh-CN") {
    if (normalized === "healthy") {
      return "正常";
    }
    if (normalized === "warning") {
      return "告警";
    }
    if (normalized === "critical") {
      return "严重";
    }
    return "未知";
  }
  if (normalized === "healthy") {
    return "healthy";
  }
  if (normalized === "warning") {
    return "warning";
  }
  if (normalized === "critical") {
    return "critical";
  }
  return "unknown";
}
