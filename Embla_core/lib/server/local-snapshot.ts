import "server-only";

import { readFile, readdir } from "node:fs/promises";
import path from "node:path";

import { mockMcpFabric } from "@/lib/mock/ops";
import { McpFabricData, OpsEnvelope } from "@/lib/types";

async function exists(targetPath: string) {
  try {
    await readFile(targetPath, "utf-8");
    return true;
  } catch {
    return false;
  }
}

export function resolveRepoRoot() {
  return process.env.EMBLA_SYSTEM_ROOT ?? path.resolve(process.cwd(), "..");
}

async function readJsonFile<T>(filePath: string): Promise<T | null> {
  try {
    const content = await readFile(filePath, "utf-8");
    return JSON.parse(content) as T;
  } catch {
    return null;
  }
}

export async function buildLocalMcpFabricSnapshot(): Promise<OpsEnvelope<McpFabricData>> {
  const repoRoot = resolveRepoRoot();
  const mcpserverDir = path.join(repoRoot, "mcpserver");
  const skillsDir = path.join(repoRoot, "skills");
  const mcporterConfigPath = path.join(process.env.HOME ?? "", ".mcporter", "config.json");

  try {
    const serviceDirs = await readdir(mcpserverDir, { withFileTypes: true });
    const services = [] as McpFabricData["services"];

    for (const dirent of serviceDirs) {
      if (!dirent.isDirectory()) {
        continue;
      }

      const manifestPath = path.join(mcpserverDir, dirent.name, "agent-manifest.json");
      const manifest = await readJsonFile<Record<string, unknown>>(manifestPath);
      if (!manifest || manifest.agentType !== "mcp") {
        continue;
      }

      services.push({
        name: String(manifest.name ?? dirent.name),
        display_name: String(manifest.displayName ?? manifest.name ?? dirent.name),
        description: String(manifest.description ?? ""),
        source: "builtin",
        status_label: "discovered",
        status_reason: "后端聚合接口不可用，当前展示本地 manifest 发现结果。"
      });
    }

    const mcporterConfig = await readJsonFile<{ mcpServers?: Record<string, Record<string, unknown>> }>(mcporterConfigPath);
    const externalEntries = Object.entries(mcporterConfig?.mcpServers ?? {});
    for (const [name, config] of externalEntries) {
      const command = String(config.command ?? "").trim();
      const args = Array.isArray(config.args) ? config.args.join(" ") : "";
      services.push({
        name,
        display_name: name,
        description: [command, args].filter(Boolean).join(" "),
        source: "mcporter",
        status_label: "configured",
        status_reason: "基于 ~/.mcporter/config.json 读取，未执行在线可用性探测。"
      });
    }

    const skillEntries = await readdir(skillsDir, { withFileTypes: true });
    const bundledSkills = [] as Array<{ name: string; path: string }>;
    for (const dirent of skillEntries) {
      if (!dirent.isDirectory()) {
        continue;
      }
      const skillPath = path.join(skillsDir, dirent.name, "SKILL.md");
      if (await exists(skillPath)) {
        bundledSkills.push({
          name: dirent.name,
          path: path.relative(repoRoot, skillPath).replaceAll(path.sep, "/")
        });
      }
    }

    const builtinServices = services.filter((service) => service.source === "builtin").length;
    const mcporterServices = services.filter((service) => service.source === "mcporter").length;

    return {
      ...mockMcpFabric,
      generated_at: new Date().toISOString(),
      severity: services.length > 0 ? "warning" : "unknown",
      reason_code: "LOCAL_MCP_SNAPSHOT",
      reason_text: "后端 MCP 聚合端点不可用，当前展示本地目录与配置快照。",
      source_reports: [path.relative(repoRoot, mcpserverDir).replaceAll(path.sep, "/"), path.relative(repoRoot, skillsDir).replaceAll(path.sep, "/")],
      source_endpoints: ["/v1/ops/mcp/fabric", "/mcp/services"],
      meta: {
        mode: "local-fallback",
        note: "local mcp snapshot"
      },
      data: {
        summary: {
          total_services: services.length,
          available_services: 0,
          builtin_services: builtinServices,
          mcporter_services: mcporterServices,
          isolated_worker_services: 0,
          rejected_plugin_manifests: 0,
          discovery_mode: "local_snapshot"
        },
        services,
        tasks: {
          total: services.length,
          tasks: services.map((service) => ({
            task_id: `${service.source}:${service.name}`,
            service_name: service.name,
            status: service.source === "builtin" ? "discovered" : "configured",
            source: service.source
          }))
        },
        registry: {
          registered_services: services.length,
          source: "local_snapshot"
        },
        runtime_snapshot: {
          server: "degraded",
          timestamp: new Date().toISOString()
        },
        tool_inventory: {
          total_tools: 0,
          memory_tools: 0,
          native_tools: 0,
          dynamic_tools: 0,
          tool_names: []
        },
        skill_inventory: {
          total_skills: bundledSkills.length,
          bundled_skills: bundledSkills.slice(0, 12)
        }
      }
    };
  } catch {
    return {
      ...mockMcpFabric,
      generated_at: new Date().toISOString(),
      meta: { mode: "mock", note: "mcp fallback mock" }
    };
  }
}
