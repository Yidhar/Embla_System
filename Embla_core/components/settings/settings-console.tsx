"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchSystemConfig, updateSystemConfig } from "@/lib/api/system";
import { formatNumber, type AppLang } from "@/lib/i18n";

type QuickForm = {
  apiKey: string;
  apiBaseUrl: string;
  apiModel: string;
  apiProvider: string;
  apiProtocol: string;
  apiTemperature: string;
  apiTimeout: string;
  embeddingApiKey: string;
  embeddingApiBaseUrl: string;
  embeddingModel: string;
  embeddingDimensions: string;
  embeddingEncodingFormat: string;
  embeddingMaxInputTokens: string;
  embeddingRequestTimeoutSeconds: string;
  gragVectorIndexEnabled: boolean;
  gragVectorIndexName: string;
  gragVectorQueryTopK: string;
  autonomousEnabled: boolean;
  autonomousCycleSeconds: string;
  releaseGuardEnabled: boolean;
  releaseMaxErrorRate: string;
  releaseMaxLatencyP95: string;
  emblaAuditLedgerFile: string;
  emblaApprovalRequiredScopes: string;
  userName: string;
  logLevel: string;
  debugMode: boolean;
};

type SettingsConsoleProps = {
  lang: AppLang;
};

type SectionKey = "api" | "autonomous" | "runtimeGovernance" | "ui" | "patch";

type DiffRow = {
  path: string;
  before: unknown;
  after: unknown;
  sensitive: boolean;
};

const FORM_DEFAULT: QuickForm = {
  apiKey: "",
  apiBaseUrl: "",
  apiModel: "",
  apiProvider: "openai_compatible",
  apiProtocol: "auto",
  apiTemperature: "0.7",
  apiTimeout: "120",
  embeddingApiKey: "",
  embeddingApiBaseUrl: "",
  embeddingModel: "text-embedding-v4",
  embeddingDimensions: "1024",
  embeddingEncodingFormat: "float",
  embeddingMaxInputTokens: "8192",
  embeddingRequestTimeoutSeconds: "30",
  gragVectorIndexEnabled: true,
  gragVectorIndexName: "entity_embedding_index",
  gragVectorQueryTopK: "8",
  autonomousEnabled: false,
  autonomousCycleSeconds: "3600",
  releaseGuardEnabled: true,
  releaseMaxErrorRate: "0.02",
  releaseMaxLatencyP95: "1500",
  emblaAuditLedgerFile: "scratch/runtime/audit_ledger.jsonl",
  emblaApprovalRequiredScopes: "core,policy,prompt_dna,tools_registry",
  userName: "",
  logLevel: "INFO",
  debugMode: false,
};

const COLLAPSED_DEFAULT: Record<SectionKey, boolean> = {
  api: false,
  autonomous: false,
  runtimeGovernance: false,
  ui: false,
  patch: false,
};

const SENSITIVE_PATHS: Array<{ id: string; path: string[]; labelKey: string }> = [
  { id: "api.api_key", path: ["api", "api_key"], labelKey: "apiKey" },
  { id: "embedding.api_key", path: ["embedding", "api_key"], labelKey: "embeddingApiKey" },
  { id: "grag.neo4j_password", path: ["grag", "neo4j_password"], labelKey: "neo4jPassword" },
  { id: "computer_control.api_key", path: ["computer_control", "api_key"], labelKey: "computerControlApiKey" },
  {
    id: "computer_control.grounding_api_key",
    path: ["computer_control", "grounding_api_key"],
    labelKey: "groundingApiKey",
  },
];

const LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR"] as const;
const API_PROVIDER_OPTIONS = ["openai_compatible", "openai", "google", "gemini", "auto"] as const;
const API_PROTOCOL_OPTIONS = ["auto", "openai_chat_completions"] as const;

const PAGE_COPY: Record<
  AppLang,
  {
    title: string;
    subtitle: string;
    loading: string;
    summary: {
      apiModel: string;
      autonomous: string;
      debug: string;
      enabled: string;
      disabled: string;
    };
    quick: {
      title: string;
      save: string;
      reload: string;
      saving: string;
      sections: {
        api: string;
        autonomous: string;
        runtimeGovernance: string;
        ui: string;
      };
      fields: {
        apiKey: string;
        apiBaseUrl: string;
        apiModel: string;
        apiProvider: string;
        apiProtocol: string;
        apiTemperature: string;
        apiTimeout: string;
        embeddingApiKey: string;
        embeddingApiBaseUrl: string;
        embeddingModel: string;
        embeddingDimensions: string;
        embeddingEncodingFormat: string;
        embeddingMaxInputTokens: string;
        embeddingRequestTimeoutSeconds: string;
        gragVectorIndexEnabled: string;
        gragVectorIndexName: string;
        gragVectorQueryTopK: string;
        autonomousEnabled: string;
        autonomousCycleSeconds: string;
        releaseGuardEnabled: string;
        releaseMaxErrorRate: string;
        releaseMaxLatencyP95: string;
        emblaAuditLedgerFile: string;
        emblaApprovalRequiredScopes: string;
        userName: string;
        logLevel: string;
        debugMode: string;
      };
      hints: {
        apiTemperature: string;
        releaseMaxErrorRate: string;
        emblaApprovalRequiredScopes: string;
        embedding: string;
      };
    };
    preview: {
      title: string;
      description: string;
      noChange: string;
      changedCount: string;
      path: string;
      before: string;
      after: string;
      sensitiveMasked: string;
      invalid: string;
    };
    patch: {
      title: string;
      description: string;
      apply: string;
      placeholder: string;
      parseOk: string;
    };
    secrets: {
      title: string;
      description: string;
      configured: string;
      empty: string;
      labels: {
        apiKey: string;
        embeddingApiKey: string;
        neo4jPassword: string;
        computerControlApiKey: string;
        groundingApiKey: string;
      };
    };
    status: {
      loadFailed: string;
      saveFailed: string;
      invalidNumber: string;
      invalidPatch: string;
      saveSuccess: string;
      patchSuccess: string;
    };
  }
> = {
  en: {
    title: "Settings",
    subtitle: "Configure API, autonomous runtime guard, and UI behavior.",
    loading: "Loading settings from backend...",
    summary: {
      apiModel: "API Model",
      autonomous: "Autonomous",
      debug: "Debug",
      enabled: "Enabled",
      disabled: "Disabled",
    },
    quick: {
      title: "Quick Settings",
      save: "Save Quick Settings",
      reload: "Reload",
      saving: "Saving...",
      sections: {
        api: "API & Model",
        autonomous: "Autonomous Guard",
        runtimeGovernance: "Runtime Governance",
        ui: "UI & Diagnostics",
      },
      fields: {
        apiKey: "API Key",
        apiBaseUrl: "API Base URL",
        apiModel: "Model",
        apiProvider: "Provider",
        apiProtocol: "Protocol",
        apiTemperature: "Temperature",
        apiTimeout: "Request Timeout (s)",
        embeddingApiKey: "Embedding API Key",
        embeddingApiBaseUrl: "Embedding API Base URL",
        embeddingModel: "Embedding Model",
        embeddingDimensions: "Embedding Dimensions",
        embeddingEncodingFormat: "Embedding Encoding Format",
        embeddingMaxInputTokens: "Embedding Max Input Tokens",
        embeddingRequestTimeoutSeconds: "Embedding Request Timeout (s)",
        gragVectorIndexEnabled: "Enable Neo4j Vector Index",
        gragVectorIndexName: "Vector Index Name",
        gragVectorQueryTopK: "Vector Query Top-K",
        autonomousEnabled: "Enable Autonomous Runtime",
        autonomousCycleSeconds: "Cycle Interval (s)",
        releaseGuardEnabled: "Enable Release Guard",
        releaseMaxErrorRate: "Max Error Rate",
        releaseMaxLatencyP95: "Max Latency P95 (ms)",
        emblaAuditLedgerFile: "Audit Ledger File",
        emblaApprovalRequiredScopes: "Approval Required Scopes",
        userName: "UI User Name",
        logLevel: "Log Level",
        debugMode: "Debug Mode",
      },
      hints: {
        apiTemperature: "Recommended range: 0.0 - 1.5",
        releaseMaxErrorRate: "Recommended range: 0.0 - 1.0",
        emblaApprovalRequiredScopes: "Use comma-separated scope names, for example: core,policy,prompt_dna,tools_registry",
        embedding: "OpenAI-compatible embedding endpoint. Keep API Base/Key empty to fallback to API settings.",
      },
    },
    preview: {
      title: "Change Preview",
      description: "Review changes before applying quick settings.",
      noChange: "No quick-setting change detected.",
      changedCount: "Changed fields",
      path: "Path",
      before: "Before",
      after: "After",
      sensitiveMasked: "Sensitive values are masked.",
      invalid: "Change preview unavailable due to invalid numeric input.",
    },
    patch: {
      title: "Advanced Patch (JSON)",
      description: "Apply a partial config patch. Only fields included in the JSON will be updated.",
      apply: "Apply Patch",
      placeholder: '{\n  "system": {\n    "debug": false\n  }\n}',
      parseOk: "JSON parse OK",
    },
    secrets: {
      title: "Secret Fields (Masked)",
      description: "Secrets are displayed in masked form for safety.",
      configured: "Configured",
      empty: "Empty",
      labels: {
        apiKey: "API Key",
        embeddingApiKey: "Embedding API Key",
        neo4jPassword: "Neo4j Password",
        computerControlApiKey: "Computer Control API Key",
        groundingApiKey: "Grounding API Key",
      },
    },
    status: {
      loadFailed: "Failed to load config from backend.",
      saveFailed: "Failed to save settings.",
      invalidNumber: "One or more numeric fields are invalid.",
      invalidPatch: "Patch JSON is invalid.",
      saveSuccess: "Quick settings saved successfully.",
      patchSuccess: "Advanced patch applied successfully.",
    },
  },
  "zh-CN": {
    title: "设置",
    subtitle: "配置 API、自主运行门禁和 UI 行为。",
    loading: "正在从后端加载配置...",
    summary: {
      apiModel: "API 模型",
      autonomous: "自主运行",
      debug: "调试模式",
      enabled: "已启用",
      disabled: "未启用",
    },
    quick: {
      title: "快捷设置",
      save: "保存快捷设置",
      reload: "重新加载",
      saving: "保存中...",
      sections: {
        api: "API 与模型",
        autonomous: "自主运行门禁",
        runtimeGovernance: "运行态治理",
        ui: "界面与诊断",
      },
      fields: {
        apiKey: "API 密钥",
        apiBaseUrl: "API Base URL",
        apiModel: "模型",
        apiProvider: "Provider",
        apiProtocol: "Protocol",
        apiTemperature: "Temperature",
        apiTimeout: "请求超时（秒）",
        embeddingApiKey: "Embedding API 密钥",
        embeddingApiBaseUrl: "Embedding API Base URL",
        embeddingModel: "Embedding 模型",
        embeddingDimensions: "Embedding 维度",
        embeddingEncodingFormat: "Embedding 编码格式",
        embeddingMaxInputTokens: "Embedding 最大输入 Token",
        embeddingRequestTimeoutSeconds: "Embedding 请求超时（秒）",
        gragVectorIndexEnabled: "启用 Neo4j 向量索引",
        gragVectorIndexName: "向量索引名称",
        gragVectorQueryTopK: "向量检索 Top-K",
        autonomousEnabled: "启用自主运行",
        autonomousCycleSeconds: "循环间隔（秒）",
        releaseGuardEnabled: "启用发布门禁",
        releaseMaxErrorRate: "最大错误率",
        releaseMaxLatencyP95: "最大 P95 延迟（毫秒）",
        emblaAuditLedgerFile: "审计账本文件路径",
        emblaApprovalRequiredScopes: "需人工审批的范围",
        userName: "界面用户名",
        logLevel: "日志级别",
        debugMode: "调试模式",
      },
      hints: {
        apiTemperature: "建议区间：0.0 - 1.5",
        releaseMaxErrorRate: "建议区间：0.0 - 1.0",
        emblaApprovalRequiredScopes: "使用英文逗号分隔，例如：core,policy,prompt_dna,tools_registry",
        embedding: "OpenAI 兼容 Embedding 接口。若留空 API Base/API Key，将回退到主 API 配置。",
      },
    },
    preview: {
      title: "变更预览",
      description: "保存快捷设置前先查看字段变更。",
      noChange: "当前未检测到快捷设置变更。",
      changedCount: "变更字段数",
      path: "路径",
      before: "变更前",
      after: "变更后",
      sensitiveMasked: "敏感字段已掩码显示。",
      invalid: "存在无效数字输入，无法生成变更预览。",
    },
    patch: {
      title: "高级补丁（JSON）",
      description: "提交部分配置补丁。仅会更新 JSON 中提供的字段。",
      apply: "应用补丁",
      placeholder: '{\n  "system": {\n    "debug": false\n  }\n}',
      parseOk: "JSON 解析成功",
    },
    secrets: {
      title: "敏感字段（掩码）",
      description: "为安全起见，敏感值仅展示掩码。",
      configured: "已配置",
      empty: "为空",
      labels: {
        apiKey: "API 密钥",
        embeddingApiKey: "Embedding API 密钥",
        neo4jPassword: "Neo4j 密码",
        computerControlApiKey: "电脑控制 API 密钥",
        groundingApiKey: "Grounding API 密钥",
      },
    },
    status: {
      loadFailed: "从后端加载配置失败。",
      saveFailed: "保存设置失败。",
      invalidNumber: "存在无效的数字字段。",
      invalidPatch: "补丁 JSON 格式无效。",
      saveSuccess: "快捷设置保存成功。",
      patchSuccess: "高级补丁应用成功。",
    },
  },
};

function asRecord(value: unknown): Record<string, unknown> {
  if (typeof value === "object" && value !== null) {
    return value as Record<string, unknown>;
  }
  return {};
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function getNestedValue(root: Record<string, unknown>, path: string[]): unknown {
  let current: unknown = root;
  for (const key of path) {
    if (!isPlainObject(current)) {
      return undefined;
    }
    current = current[key];
  }
  return current;
}

function getNestedString(root: Record<string, unknown>, path: string[], fallback = ""): string {
  const value = getNestedValue(root, path);
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" && Number.isFinite(value)) {
    return String(value);
  }
  return fallback;
}

function getNestedBoolean(root: Record<string, unknown>, path: string[], fallback = false): boolean {
  const value = getNestedValue(root, path);
  if (typeof value === "boolean") {
    return value;
  }
  return fallback;
}

function buildQuickForm(config: Record<string, unknown>): QuickForm {
  const emblaScopesRaw = getNestedValue(config, ["embla_system", "security", "approval_required_scopes"]);
  const emblaScopes = Array.isArray(emblaScopesRaw)
    ? emblaScopesRaw
        .map((item) => String(item ?? "").trim())
        .filter(Boolean)
        .join(",")
    : "core,policy,prompt_dna,tools_registry";
  return {
    apiKey: getNestedString(config, ["api", "api_key"], ""),
    apiBaseUrl: getNestedString(config, ["api", "base_url"], ""),
    apiModel: getNestedString(config, ["api", "model"], ""),
    apiProvider: getNestedString(config, ["api", "provider"], "openai_compatible"),
    apiProtocol: getNestedString(config, ["api", "protocol"], "auto"),
    apiTemperature: getNestedString(config, ["api", "temperature"], "0.7"),
    apiTimeout: getNestedString(config, ["api", "request_timeout"], "120"),
    embeddingApiKey: getNestedString(config, ["embedding", "api_key"], ""),
    embeddingApiBaseUrl: getNestedString(config, ["embedding", "api_base"], ""),
    embeddingModel: getNestedString(config, ["embedding", "model"], "text-embedding-v4"),
    embeddingDimensions: getNestedString(config, ["embedding", "dimensions"], "1024"),
    embeddingEncodingFormat: getNestedString(config, ["embedding", "encoding_format"], "float"),
    embeddingMaxInputTokens: getNestedString(config, ["embedding", "max_input_tokens"], "8192"),
    embeddingRequestTimeoutSeconds: getNestedString(config, ["embedding", "request_timeout_seconds"], "30"),
    gragVectorIndexEnabled: getNestedBoolean(config, ["grag", "vector_index_enabled"], true),
    gragVectorIndexName: getNestedString(config, ["grag", "vector_index_name"], "entity_embedding_index"),
    gragVectorQueryTopK: getNestedString(config, ["grag", "vector_query_top_k"], "8"),
    autonomousEnabled: getNestedBoolean(config, ["autonomous", "enabled"], false),
    autonomousCycleSeconds: getNestedString(config, ["autonomous", "cycle_interval_seconds"], "3600"),
    releaseGuardEnabled: getNestedBoolean(config, ["autonomous", "release", "enabled"], true),
    releaseMaxErrorRate: getNestedString(config, ["autonomous", "release", "max_error_rate"], "0.02"),
    releaseMaxLatencyP95: getNestedString(config, ["autonomous", "release", "max_latency_p95_ms"], "1500"),
    emblaAuditLedgerFile: getNestedString(
      config,
      ["embla_system", "security", "audit_ledger_file"],
      "scratch/runtime/audit_ledger.jsonl",
    ),
    emblaApprovalRequiredScopes: emblaScopes,
    userName: getNestedString(config, ["ui", "user_name"], ""),
    logLevel: getNestedString(config, ["system", "log_level"], "INFO"),
    debugMode: getNestedBoolean(config, ["system", "debug"], false),
  };
}

function isSensitivePath(path: string): boolean {
  const lowered = path.toLowerCase();
  return (
    lowered.includes("api_key") ||
    lowered.includes("password") ||
    lowered.includes("secret") ||
    lowered.includes("token")
  );
}

function maskSecret(value: unknown): string {
  const text = String(value ?? "").trim();
  if (!text) {
    return "******";
  }
  if (text.length <= 4) {
    return "*".repeat(text.length);
  }
  return `${text.slice(0, 2)}${"*".repeat(Math.max(3, text.length - 4))}${text.slice(-2)}`;
}

function primitiveEquals(a: unknown, b: unknown): boolean {
  if (typeof a === "number" && typeof b === "number") {
    if (!Number.isFinite(a) && !Number.isFinite(b)) {
      return true;
    }
    return Object.is(a, b);
  }
  return Object.is(a, b);
}

function collectDiffRows(base: unknown, patch: unknown, path: string[] = []): DiffRow[] {
  if (isPlainObject(patch)) {
    let rows: DiffRow[] = [];
    for (const [key, value] of Object.entries(patch)) {
      const nextPath = [...path, key];
      const baseValue = isPlainObject(base) ? base[key] : undefined;
      rows = rows.concat(collectDiffRows(baseValue, value, nextPath));
    }
    return rows;
  }

  if (Array.isArray(patch)) {
    const beforeSerialized = JSON.stringify(base);
    const afterSerialized = JSON.stringify(patch);
    if (beforeSerialized === afterSerialized) {
      return [];
    }
    const pathText = path.join(".");
    return [{ path: pathText, before: base, after: patch, sensitive: isSensitivePath(pathText) }];
  }

  if (primitiveEquals(base, patch)) {
    return [];
  }

  const pathText = path.join(".");
  return [{ path: pathText, before: base, after: patch, sensitive: isSensitivePath(pathText) }];
}

function formatValueDisplay(value: unknown, lang: AppLang, masked = false): string {
  if (masked) {
    return maskSecret(value);
  }
  if (typeof value === "boolean") {
    return value ? "true" : "false";
  }
  if (typeof value === "number" && Number.isFinite(value)) {
    return formatNumber(value, lang, { maximumFractionDigits: 6, fallback: "--" });
  }
  if (typeof value === "string") {
    return value || '""';
  }
  if (value === null) {
    return "null";
  }
  if (typeof value === "undefined") {
    return "--";
  }
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function buildQuickPayload(form: QuickForm): { ok: true; payload: Record<string, unknown> } | { ok: false } {
  const apiTemperature = Number(form.apiTemperature);
  const apiTimeout = Number(form.apiTimeout);
  const embeddingDimensions = Number(form.embeddingDimensions);
  const embeddingMaxInputTokens = Number(form.embeddingMaxInputTokens);
  const embeddingRequestTimeoutSeconds = Number(form.embeddingRequestTimeoutSeconds);
  const gragVectorQueryTopK = Number(form.gragVectorQueryTopK);
  const cycleSeconds = Number(form.autonomousCycleSeconds);
  const releaseMaxErrorRate = Number(form.releaseMaxErrorRate);
  const releaseMaxLatencyP95 = Number(form.releaseMaxLatencyP95);
  const numberValues = [
    apiTemperature,
    apiTimeout,
    embeddingDimensions,
    embeddingMaxInputTokens,
    embeddingRequestTimeoutSeconds,
    gragVectorQueryTopK,
    cycleSeconds,
    releaseMaxErrorRate,
    releaseMaxLatencyP95,
  ];
  if (numberValues.some((value) => !Number.isFinite(value))) {
    return { ok: false };
  }
  const approvalScopes = form.emblaApprovalRequiredScopes
    .split(/[\n,]/g)
    .map((scope) => scope.trim().toLowerCase())
    .filter(Boolean);

  return {
    ok: true,
    payload: {
      api: {
        api_key: form.apiKey.trim(),
        base_url: form.apiBaseUrl.trim(),
        model: form.apiModel.trim(),
        provider: form.apiProvider.trim() || "openai_compatible",
        protocol: form.apiProtocol.trim() || "auto",
        temperature: apiTemperature,
        request_timeout: Math.max(1, Math.round(apiTimeout)),
      },
      embedding: {
        api_key: form.embeddingApiKey.trim(),
        api_base: form.embeddingApiBaseUrl.trim(),
        model: form.embeddingModel.trim() || "text-embedding-v4",
        dimensions: Math.max(0, Math.round(embeddingDimensions)),
        encoding_format: form.embeddingEncodingFormat.trim() || "float",
        max_input_tokens: Math.max(1, Math.round(embeddingMaxInputTokens)),
        request_timeout_seconds: Math.max(1, Math.round(embeddingRequestTimeoutSeconds)),
      },
      grag: {
        vector_index_enabled: form.gragVectorIndexEnabled,
        vector_index_name: form.gragVectorIndexName.trim() || "entity_embedding_index",
        vector_query_top_k: Math.max(1, Math.round(gragVectorQueryTopK)),
      },
      system: {
        log_level: form.logLevel.trim() || "INFO",
        debug: form.debugMode,
      },
      autonomous: {
        enabled: form.autonomousEnabled,
        cycle_interval_seconds: Math.max(10, Math.round(cycleSeconds)),
        release: {
          enabled: form.releaseGuardEnabled,
          max_error_rate: releaseMaxErrorRate,
          max_latency_p95_ms: releaseMaxLatencyP95,
        },
      },
      ui: {
        user_name: form.userName.trim(),
      },
      embla_system: {
        security: {
          audit_ledger_file: form.emblaAuditLedgerFile.trim() || "scratch/runtime/audit_ledger.jsonl",
          approval_required_scopes: approvalScopes.length > 0 ? approvalScopes : ["core", "policy", "prompt_dna", "tools_registry"],
        },
      },
    },
  };
}

function sectionHeader(title: string, section: SectionKey, collapsed: Record<SectionKey, boolean>, onToggle: (section: SectionKey) => void) {
  const isCollapsed = collapsed[section];
  return (
    <button
      type="button"
      onClick={() => onToggle(section)}
      className="flex w-full items-center justify-between rounded-xl bg-white/80 px-3 py-2 text-left text-[10px] font-bold uppercase tracking-[0.2em] text-gray-500"
    >
      <span>{title}</span>
      <span>{isCollapsed ? "+" : "−"}</span>
    </button>
  );
}

export function SettingsConsole({ lang }: SettingsConsoleProps) {
  const copy = PAGE_COPY[lang];
  const [config, setConfig] = useState<Record<string, unknown> | null>(null);
  const [form, setForm] = useState<QuickForm>(FORM_DEFAULT);
  const [patchText, setPatchText] = useState<string>(copy.patch.placeholder);
  const [loading, setLoading] = useState(true);
  const [savingQuick, setSavingQuick] = useState(false);
  const [savingPatch, setSavingPatch] = useState(false);
  const [collapsed, setCollapsed] = useState<Record<SectionKey, boolean>>(COLLAPSED_DEFAULT);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const loadConfig = useCallback(async () => {
    setLoading(true);
    setError("");
    setMessage("");
    const snapshot = await fetchSystemConfig();
    if (!snapshot) {
      setError(copy.status.loadFailed);
      setLoading(false);
      return;
    }
    setConfig(snapshot);
    setForm(buildQuickForm(snapshot));
    setLoading(false);
  }, [copy.status.loadFailed]);

  useEffect(() => {
    void loadConfig();
  }, [loadConfig]);

  useEffect(() => {
    setPatchText(copy.patch.placeholder);
  }, [copy.patch.placeholder, lang]);

  const summary = useMemo(() => {
    const snapshot = asRecord(config || {});
    return {
      apiModel: getNestedString(snapshot, ["api", "model"], "--"),
      autonomousEnabled: getNestedBoolean(snapshot, ["autonomous", "enabled"], false),
      debugEnabled: getNestedBoolean(snapshot, ["system", "debug"], false),
    };
  }, [config]);

  const secretRows = useMemo(() => {
    const snapshot = asRecord(config || {});
    return SENSITIVE_PATHS.map((item) => {
      const raw = getNestedValue(snapshot, item.path);
      const text = String(raw ?? "").trim();
      return {
        id: item.id,
        label: copy.secrets.labels[item.labelKey as keyof typeof copy.secrets.labels],
        configured: Boolean(text),
        masked: maskSecret(raw),
      };
    });
  }, [config, copy]);

  const quickPayloadResult = useMemo(() => buildQuickPayload(form), [form]);

  const quickDiffRows = useMemo(() => {
    if (!quickPayloadResult.ok) {
      return null;
    }
    const base = asRecord(config || {});
    return collectDiffRows(base, quickPayloadResult.payload);
  }, [config, quickPayloadResult]);

  const patchParseResult = useMemo(() => {
    try {
      const parsed = JSON.parse(patchText);
      if (!isPlainObject(parsed)) {
        return { ok: false as const };
      }
      return { ok: true as const, payload: parsed as Record<string, unknown> };
    } catch {
      return { ok: false as const };
    }
  }, [patchText]);

  const patchDiffRows = useMemo(() => {
    if (!patchParseResult.ok) {
      return null;
    }
    const base = asRecord(config || {});
    return collectDiffRows(base, patchParseResult.payload);
  }, [config, patchParseResult]);

  const setField = <K extends keyof QuickForm>(key: K, value: QuickForm[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const toggleSection = (section: SectionKey) => {
    setCollapsed((prev) => ({ ...prev, [section]: !prev[section] }));
  };

  const saveQuickSettings = async () => {
    setError("");
    setMessage("");
    if (!quickPayloadResult.ok) {
      setError(copy.status.invalidNumber);
      return;
    }

    setSavingQuick(true);
    const result = await updateSystemConfig(quickPayloadResult.payload);
    setSavingQuick(false);
    if (!result.ok) {
      setError(`${copy.status.saveFailed} ${result.message}`);
      return;
    }
    setMessage(copy.status.saveSuccess);
    await loadConfig();
  };

  const applyPatch = async () => {
    setError("");
    setMessage("");
    if (!patchParseResult.ok) {
      setError(copy.status.invalidPatch);
      return;
    }

    setSavingPatch(true);
    const result = await updateSystemConfig(patchParseResult.payload);
    setSavingPatch(false);
    if (!result.ok) {
      setError(`${copy.status.saveFailed} ${result.message}`);
      return;
    }
    setMessage(copy.status.patchSuccess);
    await loadConfig();
  };

  if (loading) {
    return (
      <div className="glass-card p-6 text-sm text-gray-600">
        <p>{copy.loading}</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <section className="glass-card p-6">
        <p className="text-[10px] font-bold uppercase tracking-[0.25em] text-gray-500">{copy.title}</p>
        <h2 className="mt-2 text-2xl font-extrabold tracking-tight text-[#1c1c1e]">{copy.subtitle}</h2>
        <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-3">
          <div className="rounded-xl bg-white/70 px-3 py-2 text-xs text-gray-700">
            {copy.summary.apiModel}: <span className="font-bold">{summary.apiModel}</span>
          </div>
          <div className="rounded-xl bg-white/70 px-3 py-2 text-xs text-gray-700">
            {copy.summary.autonomous}:{" "}
            <span className="font-bold">{summary.autonomousEnabled ? copy.summary.enabled : copy.summary.disabled}</span>
          </div>
          <div className="rounded-xl bg-white/70 px-3 py-2 text-xs text-gray-700">
            {copy.summary.debug}: <span className="font-bold">{summary.debugEnabled ? copy.summary.enabled : copy.summary.disabled}</span>
          </div>
        </div>

        <article className="mt-4 rounded-2xl border border-gray-200/60 bg-white/70 p-4">
          <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-gray-500">{copy.secrets.title}</p>
          <p className="mt-1 text-xs text-gray-600">{copy.secrets.description}</p>
          <div className="mt-3 grid grid-cols-1 gap-2 md:grid-cols-2">
            {secretRows.map((item) => (
              <div key={item.id} className="rounded-xl bg-white/80 px-3 py-2 text-xs text-gray-700">
                <p className="font-bold">{item.label}</p>
                <p className="mt-1 font-mono text-[10px] text-gray-500">{item.masked}</p>
                <p className="mt-1 text-[10px] text-gray-500">
                  {item.configured ? copy.secrets.configured : copy.secrets.empty}
                </p>
              </div>
            ))}
          </div>
        </article>

        {error ? <p className="mt-4 text-sm text-rose-600">{error}</p> : null}
        {message ? <p className="mt-4 text-sm text-emerald-600">{message}</p> : null}
      </section>

      <section className="glass-card p-6">
        <div className="flex items-center justify-between gap-3">
          <p className="text-[10px] font-bold uppercase tracking-[0.25em] text-gray-500">{copy.quick.title}</p>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => void loadConfig()}
              className="rounded-xl border border-gray-200/60 bg-white/80 px-4 py-2 text-xs font-bold uppercase tracking-[0.18em] text-gray-600 active:scale-[0.98]"
            >
              {copy.quick.reload}
            </button>
            <button
              type="button"
              onClick={() => void saveQuickSettings()}
              disabled={savingQuick}
              className="rounded-xl border border-white/70 bg-[#1c1c1e] px-4 py-2 text-xs font-bold uppercase tracking-[0.18em] text-white active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {savingQuick ? copy.quick.saving : copy.quick.save}
            </button>
          </div>
        </div>

        <div className="mt-4 grid grid-cols-1 gap-6 xl:grid-cols-2">
          <article className="space-y-3 rounded-2xl border border-gray-200/60 bg-white/70 p-4">
            {sectionHeader(copy.quick.sections.api, "api", collapsed, toggleSection)}
            {collapsed.api ? null : (
              <div className="space-y-3">
                <label className="block">
                  <p className="mb-1 text-xs text-gray-600">{copy.quick.fields.apiKey}</p>
                  <input
                    type="password"
                    autoComplete="off"
                    value={form.apiKey}
                    onChange={(event) => setField("apiKey", event.target.value)}
                    className="h-10 w-full rounded-xl border border-white/70 bg-white/85 px-3 text-sm outline-none"
                  />
                </label>
                <label className="block">
                  <p className="mb-1 text-xs text-gray-600">{copy.quick.fields.apiBaseUrl}</p>
                  <input
                    value={form.apiBaseUrl}
                    onChange={(event) => setField("apiBaseUrl", event.target.value)}
                    className="h-10 w-full rounded-xl border border-white/70 bg-white/85 px-3 text-sm outline-none"
                  />
                </label>
                <label className="block">
                  <p className="mb-1 text-xs text-gray-600">{copy.quick.fields.apiModel}</p>
                  <input
                    value={form.apiModel}
                    onChange={(event) => setField("apiModel", event.target.value)}
                    className="h-10 w-full rounded-xl border border-white/70 bg-white/85 px-3 text-sm outline-none"
                  />
                </label>
                <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                  <label className="block">
                    <p className="mb-1 text-xs text-gray-600">{copy.quick.fields.apiProvider}</p>
                    <select
                      value={form.apiProvider}
                      onChange={(event) => setField("apiProvider", event.target.value)}
                      className="h-10 w-full rounded-xl border border-white/70 bg-white/85 px-3 text-sm outline-none"
                    >
                      {API_PROVIDER_OPTIONS.map((provider) => (
                        <option key={provider} value={provider}>
                          {provider}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="block">
                    <p className="mb-1 text-xs text-gray-600">{copy.quick.fields.apiProtocol}</p>
                    <select
                      value={form.apiProtocol}
                      onChange={(event) => setField("apiProtocol", event.target.value)}
                      className="h-10 w-full rounded-xl border border-white/70 bg-white/85 px-3 text-sm outline-none"
                    >
                      {API_PROTOCOL_OPTIONS.map((protocol) => (
                        <option key={protocol} value={protocol}>
                          {protocol}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
                <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                  <label className="block">
                    <p className="mb-1 text-xs text-gray-600">{copy.quick.fields.apiTemperature}</p>
                    <input
                      type="number"
                      step="0.1"
                      value={form.apiTemperature}
                      onChange={(event) => setField("apiTemperature", event.target.value)}
                      className="h-10 w-full rounded-xl border border-white/70 bg-white/85 px-3 text-sm outline-none"
                    />
                    <p className="mt-1 text-[10px] text-gray-500">{copy.quick.hints.apiTemperature}</p>
                  </label>
                  <label className="block">
                    <p className="mb-1 text-xs text-gray-600">{copy.quick.fields.apiTimeout}</p>
                    <input
                      type="number"
                      min={1}
                      step={1}
                      value={form.apiTimeout}
                      onChange={(event) => setField("apiTimeout", event.target.value)}
                      className="h-10 w-full rounded-xl border border-white/70 bg-white/85 px-3 text-sm outline-none"
                    />
                  </label>
                </div>

                <article className="rounded-2xl border border-gray-200/60 bg-white/80 p-3">
                  <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-gray-500">Embedding (OpenAI-Compatible)</p>
                  <p className="mt-1 text-[10px] text-gray-500">{copy.quick.hints.embedding}</p>
                  <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
                    <label className="block">
                      <p className="mb-1 text-xs text-gray-600">{copy.quick.fields.embeddingApiKey}</p>
                      <input
                        type="password"
                        autoComplete="off"
                        value={form.embeddingApiKey}
                        onChange={(event) => setField("embeddingApiKey", event.target.value)}
                        className="h-10 w-full rounded-xl border border-white/70 bg-white/85 px-3 text-sm outline-none"
                      />
                    </label>
                    <label className="block">
                      <p className="mb-1 text-xs text-gray-600">{copy.quick.fields.embeddingApiBaseUrl}</p>
                      <input
                        value={form.embeddingApiBaseUrl}
                        onChange={(event) => setField("embeddingApiBaseUrl", event.target.value)}
                        className="h-10 w-full rounded-xl border border-white/70 bg-white/85 px-3 text-sm outline-none"
                      />
                    </label>
                    <label className="block">
                      <p className="mb-1 text-xs text-gray-600">{copy.quick.fields.embeddingModel}</p>
                      <input
                        value={form.embeddingModel}
                        onChange={(event) => setField("embeddingModel", event.target.value)}
                        className="h-10 w-full rounded-xl border border-white/70 bg-white/85 px-3 text-sm outline-none"
                      />
                    </label>
                    <label className="block">
                      <p className="mb-1 text-xs text-gray-600">{copy.quick.fields.embeddingEncodingFormat}</p>
                      <input
                        value={form.embeddingEncodingFormat}
                        onChange={(event) => setField("embeddingEncodingFormat", event.target.value)}
                        className="h-10 w-full rounded-xl border border-white/70 bg-white/85 px-3 text-sm outline-none"
                      />
                    </label>
                    <label className="block">
                      <p className="mb-1 text-xs text-gray-600">{copy.quick.fields.embeddingDimensions}</p>
                      <input
                        type="number"
                        min={0}
                        step={1}
                        value={form.embeddingDimensions}
                        onChange={(event) => setField("embeddingDimensions", event.target.value)}
                        className="h-10 w-full rounded-xl border border-white/70 bg-white/85 px-3 text-sm outline-none"
                      />
                    </label>
                    <label className="block">
                      <p className="mb-1 text-xs text-gray-600">{copy.quick.fields.embeddingMaxInputTokens}</p>
                      <input
                        type="number"
                        min={1}
                        step={1}
                        value={form.embeddingMaxInputTokens}
                        onChange={(event) => setField("embeddingMaxInputTokens", event.target.value)}
                        className="h-10 w-full rounded-xl border border-white/70 bg-white/85 px-3 text-sm outline-none"
                      />
                    </label>
                    <label className="block">
                      <p className="mb-1 text-xs text-gray-600">{copy.quick.fields.embeddingRequestTimeoutSeconds}</p>
                      <input
                        type="number"
                        min={1}
                        step={1}
                        value={form.embeddingRequestTimeoutSeconds}
                        onChange={(event) => setField("embeddingRequestTimeoutSeconds", event.target.value)}
                        className="h-10 w-full rounded-xl border border-white/70 bg-white/85 px-3 text-sm outline-none"
                      />
                    </label>
                    <label className="flex items-center justify-between rounded-xl bg-white/90 px-3 py-2 text-xs text-gray-700 md:col-span-2">
                      <span>{copy.quick.fields.gragVectorIndexEnabled}</span>
                      <input
                        type="checkbox"
                        checked={form.gragVectorIndexEnabled}
                        onChange={(event) => setField("gragVectorIndexEnabled", event.target.checked)}
                        className="h-4 w-4"
                      />
                    </label>
                    <label className="block">
                      <p className="mb-1 text-xs text-gray-600">{copy.quick.fields.gragVectorIndexName}</p>
                      <input
                        value={form.gragVectorIndexName}
                        onChange={(event) => setField("gragVectorIndexName", event.target.value)}
                        className="h-10 w-full rounded-xl border border-white/70 bg-white/85 px-3 text-sm outline-none"
                      />
                    </label>
                    <label className="block">
                      <p className="mb-1 text-xs text-gray-600">{copy.quick.fields.gragVectorQueryTopK}</p>
                      <input
                        type="number"
                        min={1}
                        step={1}
                        value={form.gragVectorQueryTopK}
                        onChange={(event) => setField("gragVectorQueryTopK", event.target.value)}
                        className="h-10 w-full rounded-xl border border-white/70 bg-white/85 px-3 text-sm outline-none"
                      />
                    </label>
                  </div>
                </article>
              </div>
            )}
          </article>

          <article className="space-y-3 rounded-2xl border border-gray-200/60 bg-white/70 p-4">
            {sectionHeader(copy.quick.sections.autonomous, "autonomous", collapsed, toggleSection)}
            {collapsed.autonomous ? null : (
              <div className="space-y-3">
                <label className="flex items-center justify-between rounded-xl bg-white/80 px-3 py-2 text-xs text-gray-700">
                  <span>{copy.quick.fields.autonomousEnabled}</span>
                  <input
                    type="checkbox"
                    checked={form.autonomousEnabled}
                    onChange={(event) => setField("autonomousEnabled", event.target.checked)}
                    className="h-4 w-4"
                  />
                </label>
                <label className="block">
                  <p className="mb-1 text-xs text-gray-600">{copy.quick.fields.autonomousCycleSeconds}</p>
                  <input
                    type="number"
                    min={10}
                    step={10}
                    value={form.autonomousCycleSeconds}
                    onChange={(event) => setField("autonomousCycleSeconds", event.target.value)}
                    className="h-10 w-full rounded-xl border border-white/70 bg-white/85 px-3 text-sm outline-none"
                  />
                </label>
                <label className="flex items-center justify-between rounded-xl bg-white/80 px-3 py-2 text-xs text-gray-700">
                  <span>{copy.quick.fields.releaseGuardEnabled}</span>
                  <input
                    type="checkbox"
                    checked={form.releaseGuardEnabled}
                    onChange={(event) => setField("releaseGuardEnabled", event.target.checked)}
                    className="h-4 w-4"
                  />
                </label>
                <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                  <label className="block">
                    <p className="mb-1 text-xs text-gray-600">{copy.quick.fields.releaseMaxErrorRate}</p>
                    <input
                      type="number"
                      step="0.01"
                      min={0}
                      max={1}
                      value={form.releaseMaxErrorRate}
                      onChange={(event) => setField("releaseMaxErrorRate", event.target.value)}
                      className="h-10 w-full rounded-xl border border-white/70 bg-white/85 px-3 text-sm outline-none"
                    />
                    <p className="mt-1 text-[10px] text-gray-500">{copy.quick.hints.releaseMaxErrorRate}</p>
                  </label>
                  <label className="block">
                    <p className="mb-1 text-xs text-gray-600">{copy.quick.fields.releaseMaxLatencyP95}</p>
                    <input
                      type="number"
                      min={10}
                      step={10}
                      value={form.releaseMaxLatencyP95}
                      onChange={(event) => setField("releaseMaxLatencyP95", event.target.value)}
                      className="h-10 w-full rounded-xl border border-white/70 bg-white/85 px-3 text-sm outline-none"
                    />
                  </label>
                </div>
              </div>
            )}
          </article>

          <article className="space-y-3 rounded-2xl border border-gray-200/60 bg-white/70 p-4">
            {sectionHeader(copy.quick.sections.ui, "ui", collapsed, toggleSection)}
            {collapsed.ui ? null : (
              <div className="space-y-3">
                <label className="block">
                  <p className="mb-1 text-xs text-gray-600">{copy.quick.fields.userName}</p>
                  <input
                    value={form.userName}
                    onChange={(event) => setField("userName", event.target.value)}
                    className="h-10 w-full rounded-xl border border-white/70 bg-white/85 px-3 text-sm outline-none"
                  />
                </label>
                <label className="block">
                  <p className="mb-1 text-xs text-gray-600">{copy.quick.fields.logLevel}</p>
                  <select
                    value={form.logLevel}
                    onChange={(event) => setField("logLevel", event.target.value)}
                    className="h-10 w-full rounded-xl border border-white/70 bg-white/85 px-3 text-sm outline-none"
                  >
                    {LOG_LEVELS.map((item) => (
                      <option key={item} value={item}>
                        {item}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="flex items-center justify-between rounded-xl bg-white/80 px-3 py-2 text-xs text-gray-700">
                  <span>{copy.quick.fields.debugMode}</span>
                  <input
                    type="checkbox"
                    checked={form.debugMode}
                    onChange={(event) => setField("debugMode", event.target.checked)}
                    className="h-4 w-4"
                  />
                </label>
                <div className="rounded-xl bg-white/80 px-3 py-2 text-xs text-gray-700">
                  <span className="font-bold">API timeout: </span>
                  {formatNumber(Number(form.apiTimeout), lang, { maximumFractionDigits: 0, fallback: "--" })} s
                </div>
              </div>
            )}
          </article>

          <article className="space-y-3 rounded-2xl border border-gray-200/60 bg-white/70 p-4">
            {sectionHeader(copy.quick.sections.runtimeGovernance, "runtimeGovernance", collapsed, toggleSection)}
            {collapsed.runtimeGovernance ? null : (
              <div className="space-y-3">
                <label className="block">
                  <p className="mb-1 text-xs text-gray-600">{copy.quick.fields.emblaAuditLedgerFile}</p>
                  <input
                    value={form.emblaAuditLedgerFile}
                    onChange={(event) => setField("emblaAuditLedgerFile", event.target.value)}
                    className="h-10 w-full rounded-xl border border-white/70 bg-white/85 px-3 text-sm outline-none"
                  />
                </label>
                <label className="block">
                  <p className="mb-1 text-xs text-gray-600">{copy.quick.fields.emblaApprovalRequiredScopes}</p>
                  <textarea
                    value={form.emblaApprovalRequiredScopes}
                    onChange={(event) => setField("emblaApprovalRequiredScopes", event.target.value)}
                    className="h-24 w-full rounded-xl border border-white/70 bg-white/85 px-3 py-2 text-sm outline-none"
                    spellCheck={false}
                  />
                  <p className="mt-1 text-[10px] text-gray-500">{copy.quick.hints.emblaApprovalRequiredScopes}</p>
                </label>
              </div>
            )}
          </article>
        </div>
      </section>

      <section className="glass-card p-6">
        <p className="text-[10px] font-bold uppercase tracking-[0.25em] text-gray-500">{copy.preview.title}</p>
        <p className="mt-2 text-sm text-gray-600">{copy.preview.description}</p>
        <div className="mt-3 rounded-xl bg-white/80 px-3 py-2 text-xs text-gray-700">
          {quickDiffRows === null ? (
            <span className="text-amber-600">{copy.preview.invalid}</span>
          ) : quickDiffRows.length === 0 ? (
            <span>{copy.preview.noChange}</span>
          ) : (
            <span>
              {copy.preview.changedCount}: <span className="font-bold">{quickDiffRows.length}</span>
            </span>
          )}
        </div>
        {quickDiffRows && quickDiffRows.length > 0 ? (
          <>
            <div className="mt-2 text-[10px] text-gray-500">{copy.preview.sensitiveMasked}</div>
            <div className="mt-3 overflow-auto rounded-2xl border border-gray-200/60 bg-white/80">
              <table className="min-w-full text-left text-xs text-gray-700">
                <thead>
                  <tr className="border-b border-gray-200/80">
                    <th className="px-3 py-2 uppercase tracking-[0.18em]">{copy.preview.path}</th>
                    <th className="px-3 py-2 uppercase tracking-[0.18em]">{copy.preview.before}</th>
                    <th className="px-3 py-2 uppercase tracking-[0.18em]">{copy.preview.after}</th>
                  </tr>
                </thead>
                <tbody>
                  {quickDiffRows.map((row) => (
                    <tr key={row.path} className="border-b border-gray-100/80">
                      <td className="px-3 py-2 font-mono">{row.path}</td>
                      <td className="px-3 py-2 font-mono">{formatValueDisplay(row.before, lang, row.sensitive)}</td>
                      <td className="px-3 py-2 font-mono">{formatValueDisplay(row.after, lang, row.sensitive)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        ) : null}
      </section>

      <section className="glass-card p-6">
        <div className="space-y-3">
          {sectionHeader(copy.patch.title, "patch", collapsed, toggleSection)}
          {collapsed.patch ? null : (
            <>
              <p className="text-sm text-gray-600">{copy.patch.description}</p>
              <textarea
                value={patchText}
                onChange={(event) => setPatchText(event.target.value)}
                className="h-64 w-full rounded-2xl border border-gray-200/60 bg-white/80 p-4 font-mono text-xs text-gray-700 outline-none"
                spellCheck={false}
              />
              <div className="rounded-xl bg-white/80 px-3 py-2 text-xs text-gray-700">
                {patchParseResult.ok ? copy.patch.parseOk : copy.status.invalidPatch}
              </div>
              {patchDiffRows && patchDiffRows.length > 0 ? (
                <div className="overflow-auto rounded-2xl border border-gray-200/60 bg-white/80">
                  <table className="min-w-full text-left text-xs text-gray-700">
                    <thead>
                      <tr className="border-b border-gray-200/80">
                        <th className="px-3 py-2 uppercase tracking-[0.18em]">{copy.preview.path}</th>
                        <th className="px-3 py-2 uppercase tracking-[0.18em]">{copy.preview.before}</th>
                        <th className="px-3 py-2 uppercase tracking-[0.18em]">{copy.preview.after}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {patchDiffRows.map((row) => (
                        <tr key={`${row.path}-patch`} className="border-b border-gray-100/80">
                          <td className="px-3 py-2 font-mono">{row.path}</td>
                          <td className="px-3 py-2 font-mono">{formatValueDisplay(row.before, lang, row.sensitive)}</td>
                          <td className="px-3 py-2 font-mono">{formatValueDisplay(row.after, lang, row.sensitive)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : null}
              <div className="mt-1">
                <button
                  type="button"
                  onClick={() => void applyPatch()}
                  disabled={savingPatch}
                  className="rounded-xl border border-white/70 bg-[#1c1c1e] px-4 py-2 text-xs font-bold uppercase tracking-[0.18em] text-white active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {savingPatch ? copy.quick.saving : copy.patch.apply}
                </button>
              </div>
            </>
          )}
        </div>
      </section>
    </div>
  );
}
