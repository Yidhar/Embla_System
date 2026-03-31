import { DEFAULT_LOCALE, AppLocale } from "@/lib/i18n";
import { Severity } from "@/lib/types";

export function cx(...values: Array<string | false | null | undefined>) {
  return values.filter(Boolean).join(" ");
}

export function formatPercent(value: number | null | undefined, digits = 0) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "—";
  }

  const ratio = Math.abs(value) <= 1 ? value * 100 : value;
  return `${ratio.toFixed(digits)}%`;
}

export function formatNumber(value: number | null | undefined, digits = 0, locale: AppLocale = DEFAULT_LOCALE) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "—";
  }

  return new Intl.NumberFormat(locale, {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits
  }).format(value);
}

export function formatCompactNumber(value: number | null | undefined, digits = 1, locale: AppLocale = DEFAULT_LOCALE) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "—";
  }

  return new Intl.NumberFormat(locale, {
    notation: "compact",
    maximumFractionDigits: digits
  }).format(value);
}

export function formatDurationSeconds(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "—";
  }

  if (value < 1) {
    return `${Math.round(value * 1000)} ms`;
  }

  const seconds = Math.floor(value % 60);
  const minutes = Math.floor(value / 60) % 60;
  const hours = Math.floor(value / 3600);
  const parts: string[] = [];

  if (hours > 0) {
    parts.push(`${hours}h`);
  }
  if (minutes > 0) {
    parts.push(`${minutes}m`);
  }
  if (seconds > 0 || parts.length === 0) {
    parts.push(`${seconds}s`);
  }

  return parts.join(" ");
}

export function formatTimestamp(value: string | null | undefined, locale: AppLocale = DEFAULT_LOCALE) {
  if (!value) {
    return "—";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat(locale, {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  }).format(date);
}

export function formatMetricValue(value: number | null | undefined, unit?: string, locale: AppLocale = DEFAULT_LOCALE) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "—";
  }

  if (unit === "ratio") {
    return formatPercent(value, value < 0.1 ? 1 : 0);
  }

  if (unit === "ms") {
    return `${formatNumber(value, value < 10 ? 2 : 0, locale)} ms`;
  }

  if (unit === "seconds_to_expiry") {
    return formatDurationSeconds(value);
  }

  if (unit === "events") {
    return locale === "zh-CN"
      ? `${formatNumber(value, 0, locale)} 个`
      : `${formatNumber(value, 0, locale)} events`;
  }

  if (unit === "count") {
    return formatCompactNumber(value, 1, locale);
  }

  return formatNumber(value, value < 10 ? 2 : 0, locale);
}

export function severityLabel(severity: Severity) {
  switch (severity) {
    case "ok":
      return "ok";
    case "warning":
      return "warning";
    case "critical":
      return "critical";
    default:
      return "unknown";
  }
}

export function severityTone(severity: Severity) {
  switch (severity) {
    case "ok":
      return "text-emerald-700 bg-emerald-100/80 border-emerald-200/80";
    case "warning":
      return "text-amber-700 bg-amber-100/80 border-amber-200/80";
    case "critical":
      return "text-rose-700 bg-rose-100/80 border-rose-200/80";
    default:
      return "text-slate-600 bg-slate-100/90 border-slate-200/80";
  }
}

export function clamp(value: number, min = 0, max = 1) {
  return Math.min(max, Math.max(min, value));
}
