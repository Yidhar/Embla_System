import { ReactNode } from "react";
import { AlertTriangle, CheckCircle2, Dot, HelpCircle, Link2, ShieldAlert } from "lucide-react";

import { AppLocale, DEFAULT_LOCALE, getModeLabel, getStatusLabel, translate } from "@/lib/i18n";
import {
  cx,
  formatNumber,
  formatPercent,
  formatTimestamp,
  severityTone
} from "@/lib/format";
import { DataMode, MemoryGraphEdge, Severity } from "@/lib/types";

export function StatusBadge({ severity, label, locale = DEFAULT_LOCALE }: { severity: Severity; label?: string; locale?: AppLocale }) {
  const Icon = severity === "critical" ? ShieldAlert : severity === "warning" ? AlertTriangle : severity === "ok" ? CheckCircle2 : HelpCircle;

  return (
    <span className={cx("inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-semibold", severityTone(severity))}>
      <Icon className="h-3.5 w-3.5" strokeWidth={2} />
      {label ?? getStatusLabel(locale, severity)}
    </span>
  );
}

export function ModeBadge({ mode, locale = DEFAULT_LOCALE }: { mode?: DataMode; locale?: AppLocale }) {
  const toneMap: Record<DataMode, string> = {
    live: "text-sky-700 bg-sky-100/90 border-sky-200/70",
    degraded: "text-amber-700 bg-amber-100/90 border-amber-200/70",
    "local-fallback": "text-violet-700 bg-violet-100/90 border-violet-200/70",
    mock: "text-slate-700 bg-slate-100/90 border-slate-200/70"
  };

  const safeMode = mode ?? "mock";
  return <span className={cx("rounded-full border px-3 py-1 text-xs font-semibold", toneMap[safeMode])}>{getModeLabel(locale, safeMode)}</span>;
}

export function PageHeader({
  eyebrow,
  title,
  description,
  severity,
  mode,
  actions,
  locale = DEFAULT_LOCALE
}: {
  eyebrow: string;
  title: string;
  description: string;
  severity: Severity;
  mode?: DataMode;
  actions?: ReactNode;
  locale?: AppLocale;
}) {
  return (
    <section className="glass-panel flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
      <div className="max-w-3xl">
        <p className="eyebrow">{eyebrow}</p>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <h1 className="text-3xl font-extrabold md:text-4xl">{title}</h1>
          <StatusBadge severity={severity} locale={locale} />
          <ModeBadge mode={mode} locale={locale} />
        </div>
        <p className="mt-4 max-w-2xl text-sm leading-7 text-slate-600 md:text-base">{description}</p>
      </div>

      {actions ? <div className="flex shrink-0 items-start">{actions}</div> : null}
    </section>
  );
}

export function GlassPanel({
  title,
  eyebrow,
  description,
  actions,
  children,
  className
}: {
  title: string;
  eyebrow?: string;
  description?: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={cx("glass-card", className)}>
      <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
        <div>
          {eyebrow ? <p className="eyebrow">{eyebrow}</p> : null}
          <h2 className="mt-2 text-xl font-extrabold">{title}</h2>
          {description ? <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-500">{description}</p> : null}
        </div>
        {actions ? <div>{actions}</div> : null}
      </div>
      <div className="mt-5">{children}</div>
    </section>
  );
}

export function MetricCard({
  title,
  value,
  description,
  severity,
  footnote,
  locale = DEFAULT_LOCALE
}: {
  title: string;
  value: string;
  description?: string;
  severity: Severity;
  footnote?: string;
  locale?: AppLocale;
}) {
  return (
    <article className="glass-card h-full">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="eyebrow">{title}</p>
          <p className="mt-4 text-3xl font-extrabold tracking-tight text-[#1C1C1E]">{value}</p>
          {description ? <p className="mt-3 text-sm leading-6 text-slate-500">{description}</p> : null}
        </div>
        <StatusBadge severity={severity} locale={locale} />
      </div>
      {footnote ? <p className="mt-4 text-xs text-slate-400">{footnote}</p> : null}
    </article>
  );
}

export function MetricGrid({ children }: { children: ReactNode }) {
  return <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-4">{children}</div>;
}

export function BarList({
  items,
  formatter = (value: number) => formatNumber(value, 0, DEFAULT_LOCALE)
}: {
  items: Array<{ label: string; value: number }>;
  formatter?: (value: number) => string;
}) {
  const maxValue = Math.max(1, ...items.map((item) => item.value));

  return (
    <div className="space-y-3">
      {items.map((item) => (
        <div key={item.label} className="space-y-2">
          <div className="flex items-center justify-between gap-4 text-sm">
            <span className="truncate font-medium text-slate-700">{item.label}</span>
            <span className="shrink-0 text-slate-500">{formatter(item.value)}</span>
          </div>
          <div className="soft-inset h-2 overflow-hidden p-0.5">
            <div className="h-full rounded-full bg-[#1C1C1E]" style={{ width: `${Math.max(8, (item.value / maxValue) * 100)}%` }} />
          </div>
        </div>
      ))}
    </div>
  );
}

export function TimelineList({
  items,
  locale = DEFAULT_LOCALE
}: {
  items: Array<{ title: string; detail?: string; timestamp?: string; severity?: Severity }>;
  locale?: AppLocale;
}) {
  if (items.length === 0) {
    return <EmptyState title={translate(locale, "common.empty.noCriticalEventsTitle")} description={translate(locale, "common.empty.noCriticalEventsDescription")} />;
  }

  return (
    <div className="space-y-4">
      {items.map((item, index) => (
        <div key={`${item.title}-${item.timestamp ?? index}`} className="flex gap-3">
          <div className="flex flex-col items-center">
            <span
              className={cx(
                "mt-1 flex h-3 w-3 items-center justify-center rounded-full",
                item.severity === "critical"
                  ? "bg-rose-500"
                  : item.severity === "warning"
                    ? "bg-amber-500"
                    : "bg-emerald-500"
              )}
            />
            {index !== items.length - 1 ? <span className="mt-2 h-full w-px bg-slate-200" /> : null}
          </div>
          <div className="pb-2">
            <div className="flex flex-wrap items-center gap-2">
              <p className="text-sm font-semibold text-slate-900">{item.title}</p>
              {item.timestamp ? <span className="text-xs text-slate-400">{formatTimestamp(item.timestamp, locale)}</span> : null}
            </div>
            {item.detail ? <p className="mt-2 text-sm leading-6 text-slate-500">{item.detail}</p> : null}
          </div>
        </div>
      ))}
    </div>
  );
}

export function EmptyState({ title, description }: { title: string; description: string }) {
  return (
    <div className="soft-inset flex min-h-32 flex-col items-center justify-center gap-2 px-4 py-8 text-center">
      <p className="text-sm font-semibold text-slate-700">{title}</p>
      <p className="max-w-md text-sm leading-6 text-slate-500">{description}</p>
    </div>
  );
}

export function SourceList({ reports = [], endpoints = [] }: { reports?: string[]; endpoints?: string[] }) {
  const items = [...reports.map((item) => ({ value: item, type: "report" })), ...endpoints.map((item) => ({ value: item, type: "endpoint" }))].slice(0, 8);

  if (items.length === 0) {
    return null;
  }

  return (
    <div className="top-divider mt-5 pt-4">
      <div className="flex flex-wrap items-center gap-2">
        <Link2 className="h-4 w-4 text-slate-400" />
        {items.map((item) => (
          <span key={`${item.type}-${item.value}`} className="rounded-full border border-white/70 bg-white/80 px-3 py-1 text-xs text-slate-500">
            {item.value}
          </span>
        ))}
      </div>
    </div>
  );
}

export function GraphCanvas({ edges, compact = false, locale = DEFAULT_LOCALE }: { edges: MemoryGraphEdge[]; compact?: boolean; locale?: AppLocale }) {
  if (edges.length === 0) {
    return <EmptyState title={translate(locale, "common.empty.noGraphSampleTitle")} description={translate(locale, "common.empty.noGraphSampleDescription")} />;
  }

  const limitedEdges = edges.slice(0, compact ? 8 : 14);
  const nodeNames = Array.from(new Set(limitedEdges.flatMap((edge) => [edge.subject, edge.object]))).slice(0, compact ? 10 : 16);
  const centerX = 240;
  const centerY = compact ? 150 : 180;
  const radius = compact ? 94 : 128;
  const positions = new Map<string, { x: number; y: number }>();

  nodeNames.forEach((name, index) => {
    const angle = (Math.PI * 2 * index) / nodeNames.length - Math.PI / 2;
    positions.set(name, {
      x: centerX + radius * Math.cos(angle),
      y: centerY + radius * Math.sin(angle)
    });
  });

  return (
    <div className="soft-inset grid-overlay overflow-hidden p-4">
      <svg viewBox={`0 0 480 ${compact ? 300 : 360}`} className="h-full w-full">
        {limitedEdges.map((edge, index) => {
          const from = positions.get(edge.subject);
          const to = positions.get(edge.object);
          if (!from || !to) {
            return null;
          }

          return (
            <g key={`${edge.subject}-${edge.object}-${edge.predicate}-${index}`}>
              <line x1={from.x} y1={from.y} x2={to.x} y2={to.y} stroke="rgba(71, 85, 105, 0.22)" strokeWidth="1.5" />
              <text
                x={(from.x + to.x) / 2}
                y={(from.y + to.y) / 2 - 4}
                textAnchor="middle"
                fontSize="10"
                fill="rgba(71, 85, 105, 0.65)"
              >
                {edge.predicate.slice(0, 14)}
              </text>
            </g>
          );
        })}

        {nodeNames.map((name, index) => {
          const point = positions.get(name);
          if (!point) {
            return null;
          }

          const fill = index % 3 === 0 ? "#1C1C1E" : index % 3 === 1 ? "#475569" : "#94A3B8";

          return (
            <g key={name}>
              <circle cx={point.x} cy={point.y} r={22} fill={fill} opacity="0.92" />
              <text x={point.x} y={point.y + 38} textAnchor="middle" fontSize="11" fill="#334155">
                {name.length > 16 ? `${name.slice(0, 14)}…` : name}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

export function RatioBadge({ value, label }: { value: number; label: string }) {
  return (
    <div className="rounded-[20px] border border-white/70 bg-white/75 px-4 py-3 text-sm shadow-float">
      <div className="flex items-center gap-2 text-slate-500">
        <Dot className="h-4 w-4" />
        <span>{label}</span>
      </div>
      <p className="mt-2 text-xl font-bold text-slate-900">{formatPercent(value, 0)}</p>
    </div>
  );
}
