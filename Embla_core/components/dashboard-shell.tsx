"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  AlertTriangle,
  Blocks,
  Bot,
  Cable,
  FileText,
  GitBranch,
  Settings2,
  SlidersHorizontal,
  Workflow
} from "lucide-react";

import { LocaleSwitcher } from "@/components/locale-switcher";
import { cx } from "@/lib/format";
import { AppLocale, translate } from "@/lib/i18n";

const navItems = [
  { href: "/runtime-posture", key: "runtimePosture", icon: Activity },
  { href: "/mcp-fabric", key: "mcpFabric", icon: Cable },
  { href: "/memory-graph", key: "memoryGraph", icon: GitBranch },
  { href: "/workflow-events", key: "workflowEvents", icon: Workflow },
  { href: "/incidents", key: "incidents", icon: AlertTriangle },
  { href: "/evidence", key: "evidence", icon: FileText },
  { href: "/chatops", key: "chatops", icon: Blocks },
  { href: "/agent-config", key: "agentConfig", icon: SlidersHorizontal },
  { href: "/settings", key: "settings", icon: Settings2 },
] as const;

export function DashboardShell({ children, locale }: { children: React.ReactNode; locale: AppLocale }) {
  const pathname = usePathname();

  return (
    <div className="page-shell">
      <div className="mx-auto grid max-w-[1800px] gap-6 xl:grid-cols-[290px_minmax(0,1fr)]">
        <aside className="glass-panel relative z-10 h-fit xl:sticky xl:top-6">
          <div className="flex flex-col gap-4">
            <div className="flex min-w-0 items-center gap-3">
              <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-[20px] bg-[#1C1C1E] text-white shadow-[0_10px_24px_-10px_rgba(0,0,0,0.45)]">
                <Bot className="h-6 w-6" strokeWidth={1.75} />
              </div>
              <div className="min-w-0">
                <p className="eyebrow">{translate(locale, "layout.brandEyebrow")}</p>
                <h1 className="text-xl font-extrabold leading-tight">{translate(locale, "layout.brandTitle")}</h1>
              </div>
            </div>
            <LocaleSwitcher locale={locale} className="w-full" />
          </div>

          <div className="mt-6 rounded-[26px] border border-white/60 bg-white/60 p-4 shadow-float">
            <p className="text-sm leading-6 text-slate-600">
              {translate(locale, "layout.brandDescription")}
            </p>
          </div>

          <nav className="mt-6 space-y-2">
            {navItems.map((item) => {
              const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
              const Icon = item.icon;

              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={cx(
                    "group flex items-start gap-3 rounded-[24px] border px-4 py-3 transition duration-200 ease-embla active:scale-[0.98]",
                    active
                      ? "border-slate-900/10 bg-[#1C1C1E] text-white shadow-[0_18px_36px_-18px_rgba(0,0,0,0.45)]"
                      : "border-white/60 bg-white/65 text-slate-700 hover:border-white/80 hover:bg-white/80"
                  )}
                >
                  <span
                    className={cx(
                      "mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-[16px] border",
                      active ? "border-white/20 bg-white/10" : "border-slate-200/70 bg-slate-50/80"
                    )}
                  >
                    <Icon className="h-5 w-5" strokeWidth={1.75} />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className={cx("block text-sm font-bold", active ? "text-white" : "text-slate-900")}>
                      {translate(locale, `layout.nav.${item.key}.label`)}
                    </span>
                    <span className={cx("mt-1 block text-xs leading-5", active ? "text-white/75" : "text-slate-500")}>
                      {translate(locale, `layout.nav.${item.key}.description`)}
                    </span>
                  </span>
                </Link>
              );
            })}
          </nav>
        </aside>

        <main className="space-y-6">{children}</main>
      </div>
    </div>
  );
}
