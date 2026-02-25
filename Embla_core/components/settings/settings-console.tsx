"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchSystemConfig, updateSystemConfig } from "@/lib/api/system";
import { formatNumber, type AppLang } from "@/lib/i18n";

type QuickForm = {
  apiBaseUrl: string;
  apiModel: string;
  apiTemperature: string;
  apiTimeout: string;
  voiceEnabled: boolean;
  realtimeVoiceEnabled: boolean;
  realtimeVoiceMode: string;
  realtimeTtsVoice: string;
  autonomousEnabled: boolean;
  autonomousCycleSeconds: string;
  releaseGuardEnabled: boolean;
  releaseMaxErrorRate: string;
  releaseMaxLatencyP95: string;
  userName: string;
  logLevel: string;
  debugMode: boolean;
};

type SettingsConsoleProps = {
  lang: AppLang;
};

const FORM_DEFAULT: QuickForm = {
  apiBaseUrl: "",
  apiModel: "",
  apiTemperature: "0.7",
  apiTimeout: "120",
  voiceEnabled: true,
  realtimeVoiceEnabled: false,
  realtimeVoiceMode: "auto",
  realtimeTtsVoice: "zh-CN-XiaoyiNeural",
  autonomousEnabled: false,
  autonomousCycleSeconds: "3600",
  releaseGuardEnabled: true,
  releaseMaxErrorRate: "0.02",
  releaseMaxLatencyP95: "1500",
  userName: "",
  logLevel: "INFO",
  debugMode: false,
};

const PAGE_COPY: Record<
  AppLang,
  {
    title: string;
    subtitle: string;
    loading: string;
    summary: {
      apiModel: string;
      voice: string;
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
        voice: string;
        autonomous: string;
        ui: string;
      };
      fields: {
        apiBaseUrl: string;
        apiModel: string;
        apiTemperature: string;
        apiTimeout: string;
        voiceEnabled: string;
        realtimeVoiceEnabled: string;
        realtimeVoiceMode: string;
        realtimeTtsVoice: string;
        autonomousEnabled: string;
        autonomousCycleSeconds: string;
        releaseGuardEnabled: string;
        releaseMaxErrorRate: string;
        releaseMaxLatencyP95: string;
        userName: string;
        logLevel: string;
        debugMode: string;
      };
      hints: {
        apiTemperature: string;
        releaseMaxErrorRate: string;
      };
    };
    patch: {
      title: string;
      description: string;
      apply: string;
      placeholder: string;
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
    subtitle: "Configure API, voice, autonomous runtime guard, and UI behavior.",
    loading: "Loading settings from backend...",
    summary: {
      apiModel: "API Model",
      voice: "Voice",
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
        voice: "Voice",
        autonomous: "Autonomous Guard",
        ui: "UI & Diagnostics",
      },
      fields: {
        apiBaseUrl: "API Base URL",
        apiModel: "Model",
        apiTemperature: "Temperature",
        apiTimeout: "Request Timeout (s)",
        voiceEnabled: "Enable Voice Output",
        realtimeVoiceEnabled: "Enable Realtime Voice",
        realtimeVoiceMode: "Realtime Voice Mode",
        realtimeTtsVoice: "Realtime TTS Voice",
        autonomousEnabled: "Enable Autonomous Runtime",
        autonomousCycleSeconds: "Cycle Interval (s)",
        releaseGuardEnabled: "Enable Release Guard",
        releaseMaxErrorRate: "Max Error Rate",
        releaseMaxLatencyP95: "Max Latency P95 (ms)",
        userName: "UI User Name",
        logLevel: "Log Level",
        debugMode: "Debug Mode",
      },
      hints: {
        apiTemperature: "Recommended range: 0.0 - 1.5",
        releaseMaxErrorRate: "Recommended range: 0.0 - 1.0",
      },
    },
    patch: {
      title: "Advanced Patch (JSON)",
      description: "Apply a partial config patch. Only fields included in the JSON will be updated.",
      apply: "Apply Patch",
      placeholder: '{\n  "system": {\n    "debug": false\n  }\n}',
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
    subtitle: "配置 API、语音、自主运行门禁和 UI 行为。",
    loading: "正在从后端加载配置...",
    summary: {
      apiModel: "API 模型",
      voice: "语音",
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
        voice: "语音",
        autonomous: "自主运行门禁",
        ui: "界面与诊断",
      },
      fields: {
        apiBaseUrl: "API Base URL",
        apiModel: "模型",
        apiTemperature: "Temperature",
        apiTimeout: "请求超时（秒）",
        voiceEnabled: "启用语音输出",
        realtimeVoiceEnabled: "启用实时语音",
        realtimeVoiceMode: "实时语音模式",
        realtimeTtsVoice: "实时 TTS 声线",
        autonomousEnabled: "启用自主运行",
        autonomousCycleSeconds: "循环间隔（秒）",
        releaseGuardEnabled: "启用发布门禁",
        releaseMaxErrorRate: "最大错误率",
        releaseMaxLatencyP95: "最大 P95 延迟（毫秒）",
        userName: "界面用户名",
        logLevel: "日志级别",
        debugMode: "调试模式",
      },
      hints: {
        apiTemperature: "建议区间：0.0 - 1.5",
        releaseMaxErrorRate: "建议区间：0.0 - 1.0",
      },
    },
    patch: {
      title: "高级补丁（JSON）",
      description: "提交部分配置补丁。仅会更新 JSON 中提供的字段。",
      apply: "应用补丁",
      placeholder: '{\n  "system": {\n    "debug": false\n  }\n}',
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

function getNestedValue(root: Record<string, unknown>, path: string[]): unknown {
  let current: unknown = root;
  for (const key of path) {
    if (typeof current !== "object" || current === null) {
      return undefined;
    }
    current = (current as Record<string, unknown>)[key];
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
  return {
    apiBaseUrl: getNestedString(config, ["api", "base_url"], ""),
    apiModel: getNestedString(config, ["api", "model"], ""),
    apiTemperature: getNestedString(config, ["api", "temperature"], "0.7"),
    apiTimeout: getNestedString(config, ["api", "request_timeout"], "120"),
    voiceEnabled: getNestedBoolean(config, ["system", "voice_enabled"], true),
    realtimeVoiceEnabled: getNestedBoolean(config, ["voice_realtime", "enabled"], false),
    realtimeVoiceMode: getNestedString(config, ["voice_realtime", "voice_mode"], "auto"),
    realtimeTtsVoice: getNestedString(config, ["voice_realtime", "tts_voice"], "zh-CN-XiaoyiNeural"),
    autonomousEnabled: getNestedBoolean(config, ["autonomous", "enabled"], false),
    autonomousCycleSeconds: getNestedString(config, ["autonomous", "cycle_interval_seconds"], "3600"),
    releaseGuardEnabled: getNestedBoolean(config, ["autonomous", "release", "enabled"], true),
    releaseMaxErrorRate: getNestedString(config, ["autonomous", "release", "max_error_rate"], "0.02"),
    releaseMaxLatencyP95: getNestedString(config, ["autonomous", "release", "max_latency_p95_ms"], "1500"),
    userName: getNestedString(config, ["ui", "user_name"], ""),
    logLevel: getNestedString(config, ["system", "log_level"], "INFO"),
    debugMode: getNestedBoolean(config, ["system", "debug"], false),
  };
}

function sectionTitle(title: string) {
  return <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-gray-500">{title}</p>;
}

export function SettingsConsole({ lang }: SettingsConsoleProps) {
  const copy = PAGE_COPY[lang];
  const [config, setConfig] = useState<Record<string, unknown> | null>(null);
  const [form, setForm] = useState<QuickForm>(FORM_DEFAULT);
  const [patchText, setPatchText] = useState<string>(copy.patch.placeholder);
  const [loading, setLoading] = useState(true);
  const [savingQuick, setSavingQuick] = useState(false);
  const [savingPatch, setSavingPatch] = useState(false);
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
      voiceEnabled: getNestedBoolean(snapshot, ["system", "voice_enabled"], false),
      autonomousEnabled: getNestedBoolean(snapshot, ["autonomous", "enabled"], false),
      debugEnabled: getNestedBoolean(snapshot, ["system", "debug"], false),
    };
  }, [config]);

  const setField = <K extends keyof QuickForm>(key: K, value: QuickForm[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const saveQuickSettings = async () => {
    setError("");
    setMessage("");

    const apiTemperature = Number(form.apiTemperature);
    const apiTimeout = Number(form.apiTimeout);
    const cycleSeconds = Number(form.autonomousCycleSeconds);
    const releaseMaxErrorRate = Number(form.releaseMaxErrorRate);
    const releaseMaxLatencyP95 = Number(form.releaseMaxLatencyP95);

    const numberValues = [apiTemperature, apiTimeout, cycleSeconds, releaseMaxErrorRate, releaseMaxLatencyP95];
    if (numberValues.some((value) => !Number.isFinite(value))) {
      setError(copy.status.invalidNumber);
      return;
    }

    const payload: Record<string, unknown> = {
      api: {
        base_url: form.apiBaseUrl.trim(),
        model: form.apiModel.trim(),
        temperature: apiTemperature,
        request_timeout: Math.max(1, Math.round(apiTimeout)),
      },
      system: {
        voice_enabled: form.voiceEnabled,
        log_level: form.logLevel.trim() || "INFO",
        debug: form.debugMode,
      },
      voice_realtime: {
        enabled: form.realtimeVoiceEnabled,
        voice_mode: form.realtimeVoiceMode.trim() || "auto",
        tts_voice: form.realtimeTtsVoice.trim(),
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
    };

    setSavingQuick(true);
    const result = await updateSystemConfig(payload);
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
    let payload: Record<string, unknown>;
    try {
      const parsed = JSON.parse(patchText);
      if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
        setError(copy.status.invalidPatch);
        return;
      }
      payload = parsed as Record<string, unknown>;
    } catch {
      setError(copy.status.invalidPatch);
      return;
    }

    setSavingPatch(true);
    const result = await updateSystemConfig(payload);
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
        <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-4">
          <div className="rounded-xl bg-white/70 px-3 py-2 text-xs text-gray-700">
            {copy.summary.apiModel}: <span className="font-bold">{summary.apiModel}</span>
          </div>
          <div className="rounded-xl bg-white/70 px-3 py-2 text-xs text-gray-700">
            {copy.summary.voice}:{" "}
            <span className="font-bold">{summary.voiceEnabled ? copy.summary.enabled : copy.summary.disabled}</span>
          </div>
          <div className="rounded-xl bg-white/70 px-3 py-2 text-xs text-gray-700">
            {copy.summary.autonomous}:{" "}
            <span className="font-bold">{summary.autonomousEnabled ? copy.summary.enabled : copy.summary.disabled}</span>
          </div>
          <div className="rounded-xl bg-white/70 px-3 py-2 text-xs text-gray-700">
            {copy.summary.debug}: <span className="font-bold">{summary.debugEnabled ? copy.summary.enabled : copy.summary.disabled}</span>
          </div>
        </div>
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
            {sectionTitle(copy.quick.sections.api)}
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
          </article>

          <article className="space-y-3 rounded-2xl border border-gray-200/60 bg-white/70 p-4">
            {sectionTitle(copy.quick.sections.voice)}
            <label className="flex items-center justify-between rounded-xl bg-white/80 px-3 py-2 text-xs text-gray-700">
              <span>{copy.quick.fields.voiceEnabled}</span>
              <input
                type="checkbox"
                checked={form.voiceEnabled}
                onChange={(event) => setField("voiceEnabled", event.target.checked)}
                className="h-4 w-4"
              />
            </label>
            <label className="flex items-center justify-between rounded-xl bg-white/80 px-3 py-2 text-xs text-gray-700">
              <span>{copy.quick.fields.realtimeVoiceEnabled}</span>
              <input
                type="checkbox"
                checked={form.realtimeVoiceEnabled}
                onChange={(event) => setField("realtimeVoiceEnabled", event.target.checked)}
                className="h-4 w-4"
              />
            </label>
            <label className="block">
              <p className="mb-1 text-xs text-gray-600">{copy.quick.fields.realtimeVoiceMode}</p>
              <select
                value={form.realtimeVoiceMode}
                onChange={(event) => setField("realtimeVoiceMode", event.target.value)}
                className="h-10 w-full rounded-xl border border-white/70 bg-white/85 px-3 text-sm outline-none"
              >
                <option value="auto">auto</option>
                <option value="realtime">realtime</option>
                <option value="hybrid">hybrid</option>
              </select>
            </label>
            <label className="block">
              <p className="mb-1 text-xs text-gray-600">{copy.quick.fields.realtimeTtsVoice}</p>
              <input
                value={form.realtimeTtsVoice}
                onChange={(event) => setField("realtimeTtsVoice", event.target.value)}
                className="h-10 w-full rounded-xl border border-white/70 bg-white/85 px-3 text-sm outline-none"
              />
            </label>
          </article>

          <article className="space-y-3 rounded-2xl border border-gray-200/60 bg-white/70 p-4">
            {sectionTitle(copy.quick.sections.autonomous)}
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
          </article>

          <article className="space-y-3 rounded-2xl border border-gray-200/60 bg-white/70 p-4">
            {sectionTitle(copy.quick.sections.ui)}
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
                <option value="DEBUG">DEBUG</option>
                <option value="INFO">INFO</option>
                <option value="WARNING">WARNING</option>
                <option value="ERROR">ERROR</option>
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
          </article>
        </div>
      </section>

      <section className="glass-card p-6">
        <p className="text-[10px] font-bold uppercase tracking-[0.25em] text-gray-500">{copy.patch.title}</p>
        <p className="mt-2 text-sm text-gray-600">{copy.patch.description}</p>
        <textarea
          value={patchText}
          onChange={(event) => setPatchText(event.target.value)}
          className="mt-4 h-64 w-full rounded-2xl border border-gray-200/60 bg-white/80 p-4 font-mono text-xs text-gray-700 outline-none"
          spellCheck={false}
        />
        <div className="mt-4">
          <button
            type="button"
            onClick={() => void applyPatch()}
            disabled={savingPatch}
            className="rounded-xl border border-white/70 bg-[#1c1c1e] px-4 py-2 text-xs font-bold uppercase tracking-[0.18em] text-white active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-60"
          >
            {savingPatch ? copy.quick.saving : copy.patch.apply}
          </button>
        </div>
      </section>
    </div>
  );
}
