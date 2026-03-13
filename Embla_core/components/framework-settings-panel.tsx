"use client";

import Link from "next/link";
import { FormEvent, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { GlassPanel } from "@/components/dashboard-ui";
import { buildBrowserApiUrl, extractApiErrorMessage } from "@/lib/client-api";
import { AppLocale } from "@/lib/i18n";

const BACKEND_OPTIONS = ["boxlite", "native"] as const;
const CLEANUP_OPTIONS = ["retain", "ttl", "destroy"] as const;
const BOXLITE_MODE_OPTIONS = ["required", "preferred", "disabled"] as const;

type FrameworkSettingsPanelProps = {
  locale: AppLocale;
  initialConfig: Record<string, unknown>;
  registryPath: string;
  promptTemplateCount: number;
  enabledProfiles: number;
  totalProfiles: number;
};

type EditorState = {
  emblaProfile: string;
  heartbeatIntervalSeconds: number;
  maxRoundsDefault: number;
  maxTaskCostUsd: number;
  childCleanupMode: string;
  childCleanupTtlSeconds: number;
  enforceDualLane: boolean;
  approvalRequiredScopes: string;
  auditLedgerFile: string;
  auditSigningKeyEnv: string;
  immutableRuntimePrompts: string;
  immutableIdentityPrompts: string;
  defaultExecutionBackend: string;
  selfRepoExecutionBackend: string;
  boxliteEnabled: boolean;
  boxliteMode: string;
  boxliteProvider: string;
  boxliteImage: string;
  boxliteWorkingDir: string;
  boxliteCpus: number;
  boxliteMemoryMib: number;
  boxliteSecurityPreset: string;
  boxliteNetworkEnabled: boolean;
  boxliteAutoInstallSdk: boolean;
  boxliteInstallTimeoutSeconds: number;
  boxliteSdkPackageSpec: string;
  watcherToolsRegistryRoot: string;
  watcherBackend: string;
  postureEndpoint: string;
  incidentsLatestEndpoint: string;
};

type Copy = {
  surfaceEyebrow: string;
  surfaceTitle: string;
  surfaceDescription: string;
  mcpTitle: string;
  mcpDescription: string;
  agentTitle: string;
  agentDescription: string;
  registryTitle: string;
  registryDescription: string;
  frameworkEyebrow: string;
  frameworkTitle: string;
  frameworkDescription: string;
  basicSection: string;
  runtimeSection: string;
  securitySection: string;
  boxliteSection: string;
  advancedTitle: string;
  advancedDescription: string;
  save: string;
  saving: string;
  reset: string;
  saved: string;
  saveFailed: string;
  patchPreview: string;
  labels: Record<string, string>;
};

function getCopy(locale: AppLocale): Copy {
  if (locale === "en-US") {
    return {
      surfaceEyebrow: "Surface Routing",
      surfaceTitle: "Settings scope",
      surfaceDescription: "Keep duplicated operational controls out of this page. MCP installation belongs to MCP Fabric, and prompt/profile maintenance belongs to Agent Config.",
      mcpTitle: "MCP Fabric",
      mcpDescription: "Install and inspect MCP servers from the dedicated fabric page instead of duplicating those controls in Settings.",
      agentTitle: "Agent Config",
      agentDescription: "Manage child-agent prompt blocks, tool profiles, and agent_type registry from the dedicated configuration page.",
      registryTitle: "Control-plane registry snapshot",
      registryDescription: "A quick readonly view of the profile registry exposed by the current control plane.",
      frameworkEyebrow: "Framework Settings",
      frameworkTitle: "Core framework controls",
      frameworkDescription: "Edit the runtime defaults that shape Embla System itself. Advanced and lower-frequency options are tucked into the expandable drawer below.",
      basicSection: "Core defaults",
      runtimeSection: "Runtime & cleanup",
      securitySection: "Security baseline",
      boxliteSection: "BoxLite execution",
      advancedTitle: "Advanced settings",
      advancedDescription: "Expose lower-frequency fields only when needed, to avoid overwhelming the page during routine maintenance.",
      save: "Save settings",
      saving: "Saving…",
      reset: "Reset to loaded values",
      saved: "Framework settings updated successfully.",
      saveFailed: "Failed to update framework settings",
      patchPreview: "Patch preview",
      labels: {
        emblaProfile: "Framework profile",
        defaultExecutionBackend: "Default execution backend",
        selfRepoExecutionBackend: "Self-repo backend",
        heartbeatIntervalSeconds: "Heartbeat interval (s)",
        maxRoundsDefault: "Default max rounds",
        maxTaskCostUsd: "Task cost cap (USD)",
        childCleanupMode: "Child session cleanup mode",
        childCleanupTtlSeconds: "Cleanup TTL (s)",
        enforceDualLane: "Enforce dual-lane governance",
        approvalRequiredScopes: "Approval-required scopes",
        auditLedgerFile: "Audit ledger file",
        auditSigningKeyEnv: "Audit signing key env",
        immutableRuntimePrompts: "Immutable runtime prompts",
        immutableIdentityPrompts: "Immutable identity prompts",
        boxliteEnabled: "Enable BoxLite-first execution",
        boxliteMode: "BoxLite availability mode",
        boxliteProvider: "Provider",
        boxliteImage: "Image",
        boxliteWorkingDir: "Working directory",
        boxliteCpus: "CPUs",
        boxliteMemoryMib: "Memory (MiB)",
        boxliteSecurityPreset: "Security preset",
        boxliteNetworkEnabled: "Allow network",
        boxliteAutoInstallSdk: "Auto-install SDK",
        boxliteInstallTimeoutSeconds: "SDK install timeout (s)",
        boxliteSdkPackageSpec: "SDK package spec",
        watcherToolsRegistryRoot: "Tools registry root",
        watcherBackend: "Watcher backend",
        postureEndpoint: "Posture endpoint",
        incidentsLatestEndpoint: "Incidents endpoint",
        registryPath: "Registry path",
        promptTemplates: "Prompt templates",
        agentProfiles: "Enabled profiles"
      }
    };
  }

  return {
    surfaceEyebrow: "Surface Routing",
    surfaceTitle: "设置页范围",
    surfaceDescription: "把重复的运维入口移出本页：MCP 安装归 MCP Fabric，提示词与 Profile 维护归 Agent Config。",
    mcpTitle: "MCP Fabric",
    mcpDescription: "MCP 服务安装、连通状态与工具发现统一放在专门的 MCP 页面，不再在设置页重复提供。",
    agentTitle: "Agent Config",
    agentDescription: "子代理的 prompt block、tool profile 与 agent_type 注册表统一放在专门的 Agent 配置页维护。",
    registryTitle: "控制面注册表快照",
    registryDescription: "只读展示当前控制面暴露出来的 Profile 注册表摘要，便于快速确认配置面是否在线。",
    frameworkEyebrow: "Framework Settings",
    frameworkTitle: "框架核心设置",
    frameworkDescription: "这里聚焦 Embla System 自身的运行时默认项；低频和高级选项统一收进下方展开栏，避免页面一次暴露过多设置。",
    basicSection: "核心默认项",
    runtimeSection: "运行时与清理",
    securitySection: "安全基线",
    boxliteSection: "BoxLite 执行面",
    advancedTitle: "高级设置",
    advancedDescription: "将低频字段折叠起来，日常维护只看核心项，需要时再展开细调。",
    save: "保存设置",
    saving: "保存中…",
    reset: "恢复为已加载值",
    saved: "框架设置已更新。",
    saveFailed: "框架设置更新失败",
    patchPreview: "补丁预览",
    labels: {
      emblaProfile: "框架 Profile",
      defaultExecutionBackend: "默认执行后端",
      selfRepoExecutionBackend: "自维护仓库后端",
      heartbeatIntervalSeconds: "Heartbeat 间隔（秒）",
      maxRoundsDefault: "默认最大轮数",
      maxTaskCostUsd: "任务成本上限（USD）",
      childCleanupMode: "子会话清理模式",
      childCleanupTtlSeconds: "清理 TTL（秒）",
      enforceDualLane: "启用双轨治理",
      approvalRequiredScopes: "需要审批的范围",
      auditLedgerFile: "审计台账文件",
      auditSigningKeyEnv: "审计签名环境变量",
      immutableRuntimePrompts: "Immutable 运行时提示词",
      immutableIdentityPrompts: "Immutable 身份提示词",
      boxliteEnabled: "启用 BoxLite-first 执行",
      boxliteMode: "BoxLite 可用性模式",
      boxliteProvider: "Provider",
      boxliteImage: "镜像",
      boxliteWorkingDir: "工作目录",
      boxliteCpus: "CPU 数",
      boxliteMemoryMib: "内存（MiB）",
      boxliteSecurityPreset: "安全预设",
      boxliteNetworkEnabled: "允许网络",
      boxliteAutoInstallSdk: "自动安装 SDK",
      boxliteInstallTimeoutSeconds: "SDK 安装超时（秒）",
      boxliteSdkPackageSpec: "SDK 包规格",
      watcherToolsRegistryRoot: "工具注册根目录",
      watcherBackend: "Watcher 后端",
      postureEndpoint: "Posture 接口",
      incidentsLatestEndpoint: "Incidents 接口",
      registryPath: "注册表路径",
      promptTemplates: "提示词模板数",
      agentProfiles: "已启用 Profile"
    }
  };
}

function recordValue(input: unknown): Record<string, unknown> {
  return input && typeof input === "object" && !Array.isArray(input) ? (input as Record<string, unknown>) : {};
}

function stringValue(input: unknown, fallback = ""): string {
  const text = String(input ?? "").trim();
  return text || fallback;
}

function numberValue(input: unknown, fallback = 0): number {
  const next = Number(input);
  return Number.isFinite(next) ? next : fallback;
}

function booleanValue(input: unknown, fallback = false): boolean {
  if (typeof input === "boolean") {
    return input;
  }
  if (typeof input === "string") {
    const normalized = input.trim().toLowerCase();
    if (["1", "true", "yes", "on"].includes(normalized)) {
      return true;
    }
    if (["0", "false", "no", "off"].includes(normalized)) {
      return false;
    }
  }
  return fallback;
}

function listToTextarea(input: unknown): string {
  return Array.isArray(input)
    ? input.map((item) => stringValue(item)).filter(Boolean).join("\n")
    : "";
}

function listToCsv(input: unknown): string {
  return Array.isArray(input)
    ? input.map((item) => stringValue(item)).filter(Boolean).join(", ")
    : "";
}

function csvToList(input: string): string[] {
  return input
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function textareaToList(input: string): string[] {
  return input
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function buildEditorState(config: Record<string, unknown>): EditorState {
  const emblaSystem = recordValue(config.embla_system);
  const runtime = recordValue(emblaSystem.runtime);
  const cleanup = recordValue(runtime.child_session_cleanup);
  const security = recordValue(emblaSystem.security);
  const watchers = recordValue(emblaSystem.watchers);
  const ops = recordValue(emblaSystem.ops);
  const sandbox = recordValue(config.sandbox);
  const boxlite = recordValue(sandbox.boxlite);

  return {
    emblaProfile: stringValue(emblaSystem.profile, "pythonic-secure"),
    heartbeatIntervalSeconds: numberValue(runtime.heartbeat_interval_seconds, 5),
    maxRoundsDefault: numberValue(runtime.max_rounds_default, 500),
    maxTaskCostUsd: numberValue(runtime.max_task_cost_usd, 5),
    childCleanupMode: stringValue(cleanup.mode, "retain"),
    childCleanupTtlSeconds: numberValue(cleanup.ttl_seconds, 86400),
    enforceDualLane: booleanValue(security.enforce_dual_lane, true),
    approvalRequiredScopes: listToCsv(security.approval_required_scopes),
    auditLedgerFile: stringValue(security.audit_ledger_file, "scratch/runtime/audit_ledger.jsonl"),
    auditSigningKeyEnv: stringValue(security.audit_signing_key_env, "EMBLA_AUDIT_SIGNING_KEY"),
    immutableRuntimePrompts: listToTextarea(security.immutable_dna_runtime_prompts),
    immutableIdentityPrompts: listToTextarea(security.immutable_agent_identity_prompts),
    defaultExecutionBackend: stringValue(sandbox.default_execution_backend, "boxlite"),
    selfRepoExecutionBackend: stringValue(sandbox.self_repo_execution_backend, "boxlite"),
    boxliteEnabled: booleanValue(boxlite.enabled, true),
    boxliteMode: stringValue(boxlite.mode, "required"),
    boxliteProvider: stringValue(boxlite.provider, "sdk"),
    boxliteImage: stringValue(boxlite.image, "python:slim"),
    boxliteWorkingDir: stringValue(boxlite.working_dir, "/workspace"),
    boxliteCpus: numberValue(boxlite.cpus, 2),
    boxliteMemoryMib: numberValue(boxlite.memory_mib, 1024),
    boxliteSecurityPreset: stringValue(boxlite.security_preset, "maximum"),
    boxliteNetworkEnabled: booleanValue(boxlite.network_enabled, false),
    boxliteAutoInstallSdk: booleanValue(boxlite.auto_install_sdk, true),
    boxliteInstallTimeoutSeconds: numberValue(boxlite.install_timeout_seconds, 300),
    boxliteSdkPackageSpec: stringValue(boxlite.sdk_package_spec, "boxlite"),
    watcherToolsRegistryRoot: stringValue(watchers.tools_registry_root, "workspace/tools_registry"),
    watcherBackend: stringValue(watchers.backend, "watchdog"),
    postureEndpoint: stringValue(ops.posture_endpoint, "/v1/ops/runtime/posture"),
    incidentsLatestEndpoint: stringValue(ops.incidents_latest_endpoint, "/v1/ops/incidents/latest")
  };
}

function buildPatch(state: EditorState): Record<string, unknown> {
  return {
    embla_system: {
      profile: stringValue(state.emblaProfile, "pythonic-secure"),
      runtime: {
        heartbeat_interval_seconds: Math.max(1, Math.trunc(numberValue(state.heartbeatIntervalSeconds, 5))),
        max_rounds_default: Math.max(1, Math.trunc(numberValue(state.maxRoundsDefault, 500))),
        max_task_cost_usd: Math.max(0, numberValue(state.maxTaskCostUsd, 5)),
        child_session_cleanup: {
          mode: stringValue(state.childCleanupMode, "retain"),
          ttl_seconds: Math.max(0, Math.trunc(numberValue(state.childCleanupTtlSeconds, 86400)))
        }
      },
      security: {
        enforce_dual_lane: Boolean(state.enforceDualLane),
        approval_required_scopes: csvToList(state.approvalRequiredScopes),
        audit_ledger_file: stringValue(state.auditLedgerFile, "scratch/runtime/audit_ledger.jsonl"),
        audit_signing_key_env: stringValue(state.auditSigningKeyEnv, "EMBLA_AUDIT_SIGNING_KEY"),
        immutable_dna_runtime_prompts: textareaToList(state.immutableRuntimePrompts),
        immutable_agent_identity_prompts: textareaToList(state.immutableIdentityPrompts)
      },
      watchers: {
        tools_registry_root: stringValue(state.watcherToolsRegistryRoot, "workspace/tools_registry"),
        backend: stringValue(state.watcherBackend, "watchdog")
      },
      ops: {
        posture_endpoint: stringValue(state.postureEndpoint, "/v1/ops/runtime/posture"),
        incidents_latest_endpoint: stringValue(state.incidentsLatestEndpoint, "/v1/ops/incidents/latest")
      }
    },
    sandbox: {
      default_execution_backend: stringValue(state.defaultExecutionBackend, "boxlite"),
      self_repo_execution_backend: stringValue(state.selfRepoExecutionBackend, "boxlite"),
      boxlite: {
        enabled: Boolean(state.boxliteEnabled),
        mode: stringValue(state.boxliteMode, "required"),
        provider: stringValue(state.boxliteProvider, "sdk"),
        image: stringValue(state.boxliteImage, "python:slim"),
        working_dir: stringValue(state.boxliteWorkingDir, "/workspace"),
        cpus: Math.max(1, Math.trunc(numberValue(state.boxliteCpus, 2))),
        memory_mib: Math.max(128, Math.trunc(numberValue(state.boxliteMemoryMib, 1024))),
        security_preset: stringValue(state.boxliteSecurityPreset, "maximum"),
        network_enabled: Boolean(state.boxliteNetworkEnabled),
        auto_install_sdk: Boolean(state.boxliteAutoInstallSdk),
        install_timeout_seconds: Math.max(10, Math.trunc(numberValue(state.boxliteInstallTimeoutSeconds, 300))),
        sdk_package_spec: stringValue(state.boxliteSdkPackageSpec, "boxlite")
      }
    }
  };
}

function TextField({ label, value, onChange, type = "text" }: { label: string; value: string | number; onChange: (value: string) => void; type?: string }) {
  return (
    <label className="soft-inset flex flex-col gap-2 p-4">
      <span className="text-sm font-semibold text-slate-900">{label}</span>
      <input
        className="h-11 rounded-[16px] border border-white/70 bg-white/85 px-4 text-sm text-slate-900 outline-none"
        type={type}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}

function SelectField({ label, value, options, onChange }: { label: string; value: string; options: readonly string[]; onChange: (value: string) => void }) {
  return (
    <label className="soft-inset flex flex-col gap-2 p-4">
      <span className="text-sm font-semibold text-slate-900">{label}</span>
      <select
        className="h-11 rounded-[16px] border border-white/70 bg-white/85 px-4 text-sm text-slate-900 outline-none"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    </label>
  );
}

function TextareaField({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <label className="soft-inset flex flex-col gap-2 p-4">
      <span className="text-sm font-semibold text-slate-900">{label}</span>
      <textarea
        className="min-h-28 rounded-[16px] border border-white/70 bg-white/85 px-4 py-3 text-sm text-slate-900 outline-none"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}

function CheckboxField({ label, checked, onChange }: { label: string; checked: boolean; onChange: (value: boolean) => void }) {
  return (
    <label className="soft-inset flex min-h-[88px] items-start gap-3 p-4">
      <input className="mt-1 h-4 w-4 rounded border-slate-300" type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
      <span className="text-sm font-semibold leading-6 text-slate-900">{label}</span>
    </label>
  );
}

export function FrameworkSettingsPanel({ locale, initialConfig, registryPath, promptTemplateCount, enabledProfiles, totalProfiles }: FrameworkSettingsPanelProps) {
  const router = useRouter();
  const copy = getCopy(locale);
  const [state, setState] = useState<EditorState>(() => buildEditorState(initialConfig));
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const patchPreview = useMemo(() => JSON.stringify(buildPatch(state), null, 2), [state]);

  function update<K extends keyof EditorState>(key: K, value: EditorState[K]) {
    setState((current) => ({ ...current, [key]: value }));
  }

  function resetToLoaded() {
    setState(buildEditorState(initialConfig));
    setMessage(null);
    setError(null);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setMessage(null);
    setError(null);

    try {
      const response = await fetch(buildBrowserApiUrl("/system/config"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(buildPatch(state))
      });
      const payload = (await response.json()) as { message?: string; detail?: string };
      if (!response.ok) {
        throw new Error(extractApiErrorMessage(payload, copy.saveFailed));
      }
      setMessage(payload.message ?? copy.saved);
      router.refresh();
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : copy.saveFailed);
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="grid gap-6 xl:grid-cols-[1fr_1fr_1fr]">
        <GlassPanel eyebrow={copy.surfaceEyebrow} title={copy.surfaceTitle} description={copy.surfaceDescription}>
          <div className="space-y-3 text-sm leading-6 text-slate-600">
            <div className="soft-inset p-4">
              <p className="text-sm font-semibold text-slate-900">{copy.mcpTitle}</p>
              <p className="mt-2">{copy.mcpDescription}</p>
              <Link href="/mcp-fabric" className="mt-3 inline-flex rounded-full border border-white/70 bg-white/85 px-3 py-1.5 text-xs font-semibold text-slate-700">
                /mcp-fabric
              </Link>
            </div>
          </div>
        </GlassPanel>

        <GlassPanel eyebrow={copy.surfaceEyebrow} title={copy.surfaceTitle} description={copy.surfaceDescription}>
          <div className="space-y-3 text-sm leading-6 text-slate-600">
            <div className="soft-inset p-4">
              <p className="text-sm font-semibold text-slate-900">{copy.agentTitle}</p>
              <p className="mt-2">{copy.agentDescription}</p>
              <Link href="/agent-config" className="mt-3 inline-flex rounded-full border border-white/70 bg-white/85 px-3 py-1.5 text-xs font-semibold text-slate-700">
                /agent-config
              </Link>
            </div>
          </div>
        </GlassPanel>

        <GlassPanel eyebrow={copy.surfaceEyebrow} title={copy.registryTitle} description={copy.registryDescription}>
          <div className="grid gap-3 text-sm leading-6 text-slate-600">
            <div className="soft-inset p-4">
              <p className="text-sm font-semibold text-slate-900">{copy.labels.registryPath}</p>
              <p className="mt-2 break-all">{registryPath || "-"}</p>
            </div>
            <div className="soft-inset p-4">
              <p className="text-sm font-semibold text-slate-900">{copy.labels.promptTemplates}</p>
              <p className="mt-2">{String(promptTemplateCount)}</p>
            </div>
            <div className="soft-inset p-4">
              <p className="text-sm font-semibold text-slate-900">{copy.labels.agentProfiles}</p>
              <p className="mt-2">{enabledProfiles}/{totalProfiles}</p>
            </div>
          </div>
        </GlassPanel>
      </div>

      <GlassPanel eyebrow={copy.frameworkEyebrow} title={copy.frameworkTitle} description={copy.frameworkDescription}>
        <form className="space-y-6" onSubmit={handleSubmit}>
          <div className="space-y-3">
            <p className="eyebrow">{copy.basicSection}</p>
            <div className="grid gap-4 xl:grid-cols-3">
              <TextField label={copy.labels.emblaProfile} value={state.emblaProfile} onChange={(value) => update("emblaProfile", value)} />
              <SelectField label={copy.labels.defaultExecutionBackend} value={state.defaultExecutionBackend} options={BACKEND_OPTIONS} onChange={(value) => update("defaultExecutionBackend", value)} />
              <SelectField label={copy.labels.selfRepoExecutionBackend} value={state.selfRepoExecutionBackend} options={BACKEND_OPTIONS} onChange={(value) => update("selfRepoExecutionBackend", value)} />
            </div>
          </div>

          <div className="space-y-3">
            <p className="eyebrow">{copy.runtimeSection}</p>
            <div className="grid gap-4 xl:grid-cols-4">
              <TextField label={copy.labels.heartbeatIntervalSeconds} value={state.heartbeatIntervalSeconds} onChange={(value) => update("heartbeatIntervalSeconds", numberValue(value, state.heartbeatIntervalSeconds))} type="number" />
              <TextField label={copy.labels.maxRoundsDefault} value={state.maxRoundsDefault} onChange={(value) => update("maxRoundsDefault", numberValue(value, state.maxRoundsDefault))} type="number" />
              <TextField label={copy.labels.maxTaskCostUsd} value={state.maxTaskCostUsd} onChange={(value) => update("maxTaskCostUsd", numberValue(value, state.maxTaskCostUsd))} type="number" />
              <SelectField label={copy.labels.childCleanupMode} value={state.childCleanupMode} options={CLEANUP_OPTIONS} onChange={(value) => update("childCleanupMode", value)} />
              <TextField label={copy.labels.childCleanupTtlSeconds} value={state.childCleanupTtlSeconds} onChange={(value) => update("childCleanupTtlSeconds", numberValue(value, state.childCleanupTtlSeconds))} type="number" />
            </div>
          </div>

          <div className="space-y-3">
            <p className="eyebrow">{copy.securitySection}</p>
            <div className="grid gap-4 xl:grid-cols-3">
              <CheckboxField label={copy.labels.enforceDualLane} checked={state.enforceDualLane} onChange={(value) => update("enforceDualLane", value)} />
            </div>
          </div>

          <div className="space-y-3">
            <p className="eyebrow">{copy.boxliteSection}</p>
            <div className="grid gap-4 xl:grid-cols-3">
              <CheckboxField label={copy.labels.boxliteEnabled} checked={state.boxliteEnabled} onChange={(value) => update("boxliteEnabled", value)} />
              <SelectField label={copy.labels.boxliteMode} value={state.boxliteMode} options={BOXLITE_MODE_OPTIONS} onChange={(value) => update("boxliteMode", value)} />
              <TextField label={copy.labels.boxliteImage} value={state.boxliteImage} onChange={(value) => update("boxliteImage", value)} />
            </div>
          </div>

          <details className="soft-inset overflow-hidden p-4">
            <summary className="cursor-pointer list-none select-none text-sm font-semibold text-slate-900">
              {copy.advancedTitle}
            </summary>
            <p className="mt-3 text-sm leading-6 text-slate-500">{copy.advancedDescription}</p>

            <div className="mt-4 grid gap-4 xl:grid-cols-2">
              <TextareaField label={copy.labels.approvalRequiredScopes} value={state.approvalRequiredScopes} onChange={(value) => update("approvalRequiredScopes", value)} />
              <TextareaField label={copy.labels.immutableRuntimePrompts} value={state.immutableRuntimePrompts} onChange={(value) => update("immutableRuntimePrompts", value)} />
              <TextareaField label={copy.labels.immutableIdentityPrompts} value={state.immutableIdentityPrompts} onChange={(value) => update("immutableIdentityPrompts", value)} />
              <TextField label={copy.labels.auditLedgerFile} value={state.auditLedgerFile} onChange={(value) => update("auditLedgerFile", value)} />
              <TextField label={copy.labels.auditSigningKeyEnv} value={state.auditSigningKeyEnv} onChange={(value) => update("auditSigningKeyEnv", value)} />
              <TextField label={copy.labels.watcherToolsRegistryRoot} value={state.watcherToolsRegistryRoot} onChange={(value) => update("watcherToolsRegistryRoot", value)} />
              <TextField label={copy.labels.watcherBackend} value={state.watcherBackend} onChange={(value) => update("watcherBackend", value)} />
              <TextField label={copy.labels.postureEndpoint} value={state.postureEndpoint} onChange={(value) => update("postureEndpoint", value)} />
              <TextField label={copy.labels.incidentsLatestEndpoint} value={state.incidentsLatestEndpoint} onChange={(value) => update("incidentsLatestEndpoint", value)} />
              <TextField label={copy.labels.boxliteProvider} value={state.boxliteProvider} onChange={(value) => update("boxliteProvider", value)} />
              <TextField label={copy.labels.boxliteWorkingDir} value={state.boxliteWorkingDir} onChange={(value) => update("boxliteWorkingDir", value)} />
              <TextField label={copy.labels.boxliteCpus} value={state.boxliteCpus} onChange={(value) => update("boxliteCpus", numberValue(value, state.boxliteCpus))} type="number" />
              <TextField label={copy.labels.boxliteMemoryMib} value={state.boxliteMemoryMib} onChange={(value) => update("boxliteMemoryMib", numberValue(value, state.boxliteMemoryMib))} type="number" />
              <TextField label={copy.labels.boxliteSecurityPreset} value={state.boxliteSecurityPreset} onChange={(value) => update("boxliteSecurityPreset", value)} />
              <TextField label={copy.labels.boxliteInstallTimeoutSeconds} value={state.boxliteInstallTimeoutSeconds} onChange={(value) => update("boxliteInstallTimeoutSeconds", numberValue(value, state.boxliteInstallTimeoutSeconds))} type="number" />
              <TextField label={copy.labels.boxliteSdkPackageSpec} value={state.boxliteSdkPackageSpec} onChange={(value) => update("boxliteSdkPackageSpec", value)} />
              <CheckboxField label={copy.labels.boxliteNetworkEnabled} checked={state.boxliteNetworkEnabled} onChange={(value) => update("boxliteNetworkEnabled", value)} />
              <CheckboxField label={copy.labels.boxliteAutoInstallSdk} checked={state.boxliteAutoInstallSdk} onChange={(value) => update("boxliteAutoInstallSdk", value)} />
            </div>

            <div className="mt-4 soft-inset p-4">
              <p className="text-sm font-semibold text-slate-900">{copy.patchPreview}</p>
              <pre className="mt-3 overflow-x-auto whitespace-pre-wrap break-words text-xs leading-6 text-slate-600">{patchPreview}</pre>
            </div>
          </details>

          <div className="flex flex-wrap gap-3">
            <button
              type="submit"
              disabled={pending}
              className="rounded-xl bg-[#1C1C1E] px-5 py-3 text-sm font-bold text-white shadow-[0_10px_24px_-10px_rgba(0,0,0,0.45)] transition duration-200 ease-embla hover:brightness-110 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {pending ? copy.saving : copy.save}
            </button>
            <button
              type="button"
              onClick={resetToLoaded}
              className="rounded-xl border border-white/70 bg-white/85 px-5 py-3 text-sm font-semibold text-slate-700"
            >
              {copy.reset}
            </button>
          </div>

          {message ? <p className="text-sm text-emerald-600">{message}</p> : null}
          {error ? <p className="text-sm text-rose-600">{error}</p> : null}
        </form>
      </GlassPanel>
    </div>
  );
}
