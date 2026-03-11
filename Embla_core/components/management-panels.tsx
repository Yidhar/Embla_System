"use client";

import { FormEvent, useState } from "react";

import { GlassPanel } from "@/components/dashboard-ui";
import { buildBrowserApiUrl, extractApiErrorMessage } from "@/lib/client-api";
import { AppLocale, translate } from "@/lib/i18n";

type McpPreset = {
  key: string;
  name: string;
  config: Record<string, unknown>;
};

const MCP_CATALOG_LINKS = [
  { label: "Official Registry", href: "https://registry.modelcontextprotocol.io/" },
  { label: "Official Servers Repo", href: "https://github.com/modelcontextprotocol/servers" },
  { label: "PulseMCP", href: "https://www.pulsemcp.com/" },
  { label: "Awesome MCP Servers", href: "https://github.com/punkpeye/awesome-mcp-servers" }
] as const;

const MCP_PRESETS: McpPreset[] = [
  {
    key: "presetFetch",
    name: "fetch",
    config: {
      command: "npx",
      args: ["-y", "@modelcontextprotocol/server-fetch"]
    }
  },
  {
    key: "presetFilesystem",
    name: "filesystem",
    config: {
      command: "npx",
      args: ["-y", "@modelcontextprotocol/server-filesystem", "/home/yun/Embla_System"]
    }
  },
  {
    key: "presetGit",
    name: "git",
    config: {
      command: "uvx",
      args: ["mcp-server-git", "--repository", "/home/yun/Embla_System"]
    }
  },
  {
    key: "presetMemory",
    name: "memory",
    config: {
      command: "npx",
      args: ["-y", "@modelcontextprotocol/server-memory"]
    }
  }
];

export function ManagementPanels({ locale }: { locale: AppLocale }) {
  const [mcpName, setMcpName] = useState("");
  const [mcpConfig, setMcpConfig] = useState('{\n  "command": "npx",\n  "args": ["-y", "@modelcontextprotocol/server-fetch"]\n}');
  const [skillName, setSkillName] = useState("");
  const [skillContent, setSkillContent] = useState(translate(locale, "management.skill.defaultContent"));
  const [mcpMessage, setMcpMessage] = useState<string | null>(null);
  const [skillMessage, setSkillMessage] = useState<string | null>(null);
  const [pending, setPending] = useState<"mcp" | "skill" | null>(null);

  function handleApplyPreset(preset: McpPreset) {
    setMcpName(preset.name);
    setMcpConfig(JSON.stringify(preset.config, null, 2));
    setMcpMessage(null);
  }

  async function handleMcpSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending("mcp");
    setMcpMessage(null);

    try {
      const config = JSON.parse(mcpConfig) as Record<string, unknown>;
      const response = await fetch(buildBrowserApiUrl("/mcp/import"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: mcpName, config })
      });
      const payload = (await response.json()) as { message?: string; detail?: string };
      if (!response.ok) {
        throw new Error(extractApiErrorMessage(payload, translate(locale, "management.mcp.submitError")));
      }
      setMcpMessage(payload.message ?? translate(locale, "management.mcp.submitSuccess"));
      setMcpName("");
    } catch (error) {
      setMcpMessage(error instanceof Error ? error.message : translate(locale, "management.mcp.submitError"));
    } finally {
      setPending(null);
    }
  }

  async function handleSkillSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending("skill");
    setSkillMessage(null);

    try {
      const response = await fetch(buildBrowserApiUrl("/skills/import"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: skillName, content: skillContent })
      });
      const payload = (await response.json()) as { message?: string; detail?: string };
      if (!response.ok) {
        throw new Error(extractApiErrorMessage(payload, translate(locale, "management.skill.submitError")));
      }
      setSkillMessage(payload.message ?? translate(locale, "management.skill.submitSuccess"));
      setSkillName("");
    } catch (error) {
      setSkillMessage(error instanceof Error ? error.message : translate(locale, "management.skill.submitError"));
    } finally {
      setPending(null);
    }
  }

  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <GlassPanel eyebrow={translate(locale, "management.mcp.eyebrow")} title={translate(locale, "management.mcp.title")} description={translate(locale, "management.mcp.description")}>
        <div className="grid gap-4 lg:grid-cols-[1.15fr_0.85fr]">
          <div className="soft-inset p-4">
            <p className="text-sm font-semibold text-slate-900">{translate(locale, "management.mcp.catalogTitle")}</p>
            <p className="mt-2 text-sm leading-6 text-slate-500">{translate(locale, "management.mcp.catalogDescription")}</p>
            <div className="mt-4 flex flex-wrap gap-2">
              {MCP_CATALOG_LINKS.map((item) => (
                <a
                  key={item.href}
                  href={item.href}
                  target="_blank"
                  rel="noreferrer"
                  className="rounded-full border border-white/70 bg-white/80 px-3 py-1.5 text-xs font-semibold text-slate-600"
                >
                  {item.label}
                </a>
              ))}
            </div>
          </div>

          <div className="soft-inset p-4">
            <p className="text-sm font-semibold text-slate-900">{translate(locale, "management.mcp.presetsTitle")}</p>
            <div className="mt-4 flex flex-wrap gap-2">
              {MCP_PRESETS.map((preset) => (
                <button
                  key={preset.key}
                  type="button"
                  onClick={() => handleApplyPreset(preset)}
                  className="rounded-full border border-white/70 bg-white/80 px-3 py-1.5 text-xs font-semibold text-slate-600"
                >
                  {translate(locale, `management.mcp.${preset.key}`)} · {translate(locale, "management.mcp.presetUse")}
                </button>
              ))}
            </div>
          </div>
        </div>

        <form className="mt-4 space-y-4" onSubmit={handleMcpSubmit}>
          <div className="soft-inset p-2">
            <input
              className="h-11 w-full rounded-[16px] border border-white/70 bg-white/80 px-4 text-sm text-slate-900 outline-none"
              placeholder={translate(locale, "management.mcp.placeholder")}
              value={mcpName}
              onChange={(event) => setMcpName(event.target.value)}
              required
            />
          </div>
          <div className="soft-inset p-2">
            <textarea
              className="min-h-48 w-full rounded-[16px] border border-white/70 bg-white/80 px-4 py-3 text-sm text-slate-900 outline-none"
              value={mcpConfig}
              onChange={(event) => setMcpConfig(event.target.value)}
              required
            />
          </div>
          <button
            type="submit"
            disabled={pending === "mcp"}
            className="rounded-xl bg-[#1C1C1E] px-5 py-3 text-sm font-bold text-white shadow-[0_10px_24px_-10px_rgba(0,0,0,0.45)] transition duration-200 ease-embla hover:brightness-110 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-60"
          >
            {pending === "mcp" ? translate(locale, "management.mcp.submitting") : translate(locale, "management.mcp.submit")}
          </button>
          {mcpMessage ? <p className="text-sm text-slate-500">{mcpMessage}</p> : null}
        </form>
      </GlassPanel>

      <GlassPanel eyebrow={translate(locale, "management.skill.eyebrow")} title={translate(locale, "management.skill.title")} description={translate(locale, "management.skill.description")}>
        <form className="space-y-4" onSubmit={handleSkillSubmit}>
          <div className="soft-inset p-2">
            <input
              className="h-11 w-full rounded-[16px] border border-white/70 bg-white/80 px-4 text-sm text-slate-900 outline-none"
              placeholder={translate(locale, "management.skill.placeholder")}
              value={skillName}
              onChange={(event) => setSkillName(event.target.value)}
              required
            />
          </div>
          <div className="soft-inset p-2">
            <textarea
              className="min-h-48 w-full rounded-[16px] border border-white/70 bg-white/80 px-4 py-3 text-sm text-slate-900 outline-none"
              value={skillContent}
              onChange={(event) => setSkillContent(event.target.value)}
              required
            />
          </div>
          <button
            type="submit"
            disabled={pending === "skill"}
            className="rounded-xl bg-[#1C1C1E] px-5 py-3 text-sm font-bold text-white shadow-[0_10px_24px_-10px_rgba(0,0,0,0.45)] transition duration-200 ease-embla hover:brightness-110 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-60"
          >
            {pending === "skill" ? translate(locale, "management.skill.submitting") : translate(locale, "management.skill.submit")}
          </button>
          {skillMessage ? <p className="text-sm text-slate-500">{skillMessage}</p> : null}
        </form>
      </GlassPanel>
    </div>
  );
}
