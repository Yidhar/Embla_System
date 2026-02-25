"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { Activity, Blocks, Brain, Workflow, SlidersHorizontal } from "lucide-react";
import type { ReactNode } from "react";
import { normalizeLang, type AppLang } from "@/lib/i18n";

const NAV_ITEMS = [
  { href: "/runtime-posture", key: "runtimePosture", icon: Activity },
  { href: "/mcp-fabric", key: "mcpFabric", icon: Blocks },
  { href: "/memory-graph", key: "memoryGraph", icon: Brain },
  { href: "/workflow-events", key: "workflowEvents", icon: Workflow },
  { href: "/settings", key: "settings", icon: SlidersHorizontal },
];

const LAYOUT_COPY: Record<
  AppLang,
  {
    brand: string;
    title: string;
    languageLabel: string;
    nav: Record<string, string>;
  }
> = {
  en: {
    brand: "Embla Core",
    title: "Operations Console",
    languageLabel: "Language",
    nav: {
      runtimePosture: "Runtime Posture",
      mcpFabric: "MCP Fabric",
      memoryGraph: "Memory Graph",
      workflowEvents: "Workflow & Events",
      settings: "Settings",
    },
  },
  "zh-CN": {
    brand: "Embla 核心",
    title: "运行态势控制台",
    languageLabel: "语言",
    nav: {
      runtimePosture: "运行态势",
      mcpFabric: "MCP 织网",
      memoryGraph: "记忆图谱",
      workflowEvents: "工作流与事件",
      settings: "设置",
    },
  },
};

function langToQueryValue(lang: AppLang): string {
  return lang === "zh-CN" ? "zh-cn" : "en";
}

export function DashboardShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const lang = normalizeLang(searchParams.get("lang"));
  const copy = LAYOUT_COPY[lang];

  const buildHref = (basePath: string, targetLang: AppLang): string => {
    const params = new URLSearchParams(searchParams.toString());
    params.set("lang", langToQueryValue(targetLang));
    const query = params.toString();
    return query ? `${basePath}?${query}` : basePath;
  };

  const buildCurrentPathHref = (targetLang: AppLang): string => {
    const params = new URLSearchParams(searchParams.toString());
    params.set("lang", langToQueryValue(targetLang));
    const query = params.toString();
    return query ? `${pathname}?${query}` : pathname;
  };

  return (
    <div className="min-h-screen bg-embla-base p-4 md:p-8">
      <div className="glass-panel mx-auto flex min-h-[calc(100vh-2rem)] w-full max-w-[1800px] flex-col gap-6 p-6 md:p-8">
        <header className="flex flex-col gap-6 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <p className="text-[10px] font-bold uppercase tracking-[0.25em] text-gray-500">{copy.brand}</p>
            <h1 className="mt-2 text-3xl font-extrabold tracking-tight text-[#1C1C1E]">{copy.title}</h1>
          </div>
          <div className="space-y-2">
            <div className="flex items-center justify-end gap-2">
              <span className="text-[10px] font-bold uppercase tracking-[0.2em] text-gray-500">{copy.languageLabel}</span>
              <Link
                href={buildCurrentPathHref("en")}
                className={
                  lang === "en"
                    ? "rounded-lg border border-white/70 bg-[#1C1C1E] px-3 py-1 text-[10px] font-bold uppercase tracking-[0.18em] text-white"
                    : "rounded-lg border border-gray-200/50 bg-white/75 px-3 py-1 text-[10px] font-bold uppercase tracking-[0.18em] text-gray-600"
                }
              >
                EN
              </Link>
              <Link
                href={buildCurrentPathHref("zh-CN")}
                className={
                  lang === "zh-CN"
                    ? "rounded-lg border border-white/70 bg-[#1C1C1E] px-3 py-1 text-[10px] font-bold uppercase tracking-[0.18em] text-white"
                    : "rounded-lg border border-gray-200/50 bg-white/75 px-3 py-1 text-[10px] font-bold uppercase tracking-[0.18em] text-gray-600"
                }
              >
                ZH-CN
              </Link>
            </div>
            <div className="rounded-[20px] bg-gray-100/55 p-2 shadow-insetEmbla">
            <nav className="flex flex-wrap gap-2">
              {NAV_ITEMS.map(({ href, icon: Icon, key }) => {
                const active = pathname === href;
                return (
                  <Link
                    key={href}
                    href={buildHref(href, lang)}
                    className={
                      active
                        ? "rounded-xl border border-white/70 bg-[#1C1C1E] px-4 py-2 text-xs font-bold uppercase tracking-[0.2em] text-white shadow-float transition active:scale-[0.98]"
                        : "rounded-xl border border-gray-200/40 bg-white/75 px-4 py-2 text-xs font-bold uppercase tracking-[0.2em] text-gray-600 shadow-float transition hover:border-white/80 hover:bg-white/90 active:scale-[0.98]"
                    }
                  >
                    <span className="inline-flex items-center gap-2">
                      <Icon size={16} strokeWidth={1.8} />
                      {copy.nav[key]}
                    </span>
                  </Link>
                );
              })}
            </nav>
          </div>
          </div>
        </header>
        <main className="flex-1">{children}</main>
      </div>
    </div>
  );
}
