"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Activity, Blocks, Brain, Workflow } from "lucide-react";
import type { ReactNode } from "react";

const NAV_ITEMS = [
  { href: "/runtime-posture", label: "Runtime Posture", icon: Activity },
  { href: "/mcp-fabric", label: "MCP Fabric", icon: Blocks },
  { href: "/memory-graph", label: "Memory Graph", icon: Brain },
  { href: "/workflow-events", label: "Workflow & Events", icon: Workflow },
];

export function DashboardShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="min-h-screen bg-embla-base p-4 md:p-8">
      <div className="glass-panel mx-auto flex min-h-[calc(100vh-2rem)] w-full max-w-[1800px] flex-col gap-6 p-6 md:p-8">
        <header className="flex flex-col gap-6 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <p className="text-[10px] font-bold uppercase tracking-[0.25em] text-gray-500">Embla Core</p>
            <h1 className="mt-2 text-3xl font-extrabold tracking-tight text-[#1C1C1E]">Operations Console</h1>
          </div>
          <div className="rounded-[20px] bg-gray-100/55 p-2 shadow-insetEmbla">
            <nav className="flex flex-wrap gap-2">
              {NAV_ITEMS.map(({ href, icon: Icon, label }) => {
                const active = pathname === href;
                return (
                  <Link
                    key={href}
                    href={href}
                    className={
                      active
                        ? "rounded-xl border border-white/70 bg-[#1C1C1E] px-4 py-2 text-xs font-bold uppercase tracking-[0.2em] text-white shadow-float transition active:scale-[0.98]"
                        : "rounded-xl border border-gray-200/40 bg-white/75 px-4 py-2 text-xs font-bold uppercase tracking-[0.2em] text-gray-600 shadow-float transition hover:border-white/80 hover:bg-white/90 active:scale-[0.98]"
                    }
                  >
                    <span className="inline-flex items-center gap-2">
                      <Icon size={16} strokeWidth={1.8} />
                      {label}
                    </span>
                  </Link>
                );
              })}
            </nav>
          </div>
        </header>
        <main className="flex-1">{children}</main>
      </div>
    </div>
  );
}
