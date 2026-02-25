import { AlertCircle, CheckCircle2, CircleHelp } from "lucide-react";

export type SignalState = "healthy" | "warning" | "critical" | "unknown";

const STATE_STYLE: Record<SignalState, string> = {
  healthy: "text-emerald-700 bg-emerald-50 border-emerald-200/60",
  warning: "text-amber-700 bg-amber-50 border-amber-200/60",
  critical: "text-rose-700 bg-rose-50 border-rose-200/60",
  unknown: "text-slate-600 bg-slate-50 border-slate-200/60",
};

function StateIcon({ state }: { state: SignalState }) {
  if (state === "critical" || state === "warning") {
    return <AlertCircle size={14} strokeWidth={1.8} />;
  }
  if (state === "healthy") {
    return <CheckCircle2 size={14} strokeWidth={1.8} />;
  }
  return <CircleHelp size={14} strokeWidth={1.8} />;
}

export function SignalCard({
  title,
  value,
  note,
  state,
  stateLabel,
}: {
  title: string;
  value: string;
  note: string;
  state: SignalState;
  stateLabel?: string;
}) {
  return (
    <section className="glass-card p-6">
      <p className="text-[10px] font-bold uppercase tracking-[0.25em] text-gray-500">{title}</p>
      <h3 className="mt-3 text-3xl font-extrabold tracking-tight text-[#1C1C1E]">{value}</h3>
      <div className="mt-4 flex items-center justify-between">
        <p className="text-sm text-gray-600">{note}</p>
        <span
          className={`inline-flex items-center gap-1 rounded-xl border px-2 py-1 text-[10px] font-bold uppercase tracking-[0.16em] ${STATE_STYLE[state]}`}
        >
          <StateIcon state={state} />
          {stateLabel || state}
        </span>
      </div>
    </section>
  );
}
