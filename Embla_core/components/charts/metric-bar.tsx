import type { ReactNode } from "react";

export type MetricBarTone = "healthy" | "warning" | "critical" | "unknown";

const TONE_CLASS: Record<MetricBarTone, string> = {
  healthy: "bg-emerald-500",
  warning: "bg-amber-500",
  critical: "bg-rose-500",
  unknown: "bg-gray-400",
};

export function MetricBar({
  label,
  value,
  ratio,
  tone,
  hint,
  right,
}: {
  label: string;
  value: string;
  ratio: number | null;
  tone: MetricBarTone;
  hint?: string;
  right?: ReactNode;
}) {
  const safeRatio = typeof ratio === "number" && Number.isFinite(ratio) ? Math.max(0, Math.min(1, ratio)) : 0;

  return (
    <article className="rounded-2xl border border-gray-200/60 bg-white/70 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-gray-500">{label}</p>
          <p className="mt-1 text-lg font-extrabold tracking-tight text-[#1c1c1e]">{value}</p>
        </div>
        <div className="text-right text-xs text-gray-500">{right}</div>
      </div>
      <div className="mt-3 h-2 rounded-full bg-gray-100">
        <div className={`h-2 rounded-full transition-all ${TONE_CLASS[tone]}`} style={{ width: `${safeRatio * 100}%` }} />
      </div>
      {hint ? <p className="mt-2 text-xs text-gray-500">{hint}</p> : null}
    </article>
  );
}
