"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";

import { EmptyState, GlassPanel } from "@/components/dashboard-ui";
import { fetchBrowserJson } from "@/lib/client-api";
import { cx, formatTimestamp } from "@/lib/format";
import { AppLocale, translate } from "@/lib/i18n";
import { AgentProfile, AgentProfileDetail, AgentProfileRegistryData } from "@/lib/types";

function linesToList(value: string) {
  return value
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function csvToList(value: string) {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function profileToDraft(profile?: AgentProfile | null) {
  return {
    agent_type: String(profile?.agent_type ?? "").trim(),
    role: String(profile?.role ?? "dev").trim() || "dev",
    label: String(profile?.label ?? "").trim(),
    description: String(profile?.description ?? "").trim(),
    prompt_blocks_text: Array.isArray(profile?.prompt_blocks) ? profile!.prompt_blocks.join("\n") : "",
    tool_profile: String(profile?.tool_profile ?? "").trim(),
    tool_subset_text: Array.isArray(profile?.tool_subset) ? profile!.tool_subset.join(", ") : "",
    prompts_root: String(profile?.prompts_root ?? "").trim(),
    enabled: profile?.enabled !== false,
    default_for_role: Boolean(profile?.default_for_role),
    builtin: Boolean(profile?.builtin),
  };
}

type AgentProfileManagerProps = {
  locale: AppLocale;
  initialRegistry: AgentProfileRegistryData;
  initialDetail?: AgentProfileDetail | null;
};

export function AgentProfileManager({ locale, initialRegistry, initialDetail = null }: AgentProfileManagerProps) {
  const t = useMemo(() => (key: string, values?: Record<string, string | number>) => translate(locale, key, values), [locale]);
  const [registry, setRegistry] = useState<AgentProfileRegistryData>(initialRegistry);
  const [selectedAgentType, setSelectedAgentType] = useState<string>(initialDetail?.profile.agent_type ?? initialRegistry.profiles[0]?.agent_type ?? "");
  const [detail, setDetail] = useState<AgentProfileDetail | null>(initialDetail);
  const [draft, setDraft] = useState(() => profileToDraft(initialDetail?.profile ?? initialRegistry.profiles[0] ?? null));
  const [pendingAction, setPendingAction] = useState<"save" | "delete" | "refresh" | null>(null);
  const [message, setMessage] = useState<string>("");
  const [error, setError] = useState<string>("");

  useEffect(() => {
    setRegistry(initialRegistry);
  }, [initialRegistry]);

  useEffect(() => {
    if (!selectedAgentType) {
      setDetail(null);
      setDraft(profileToDraft(null));
      return;
    }
    const localProfile = registry.profiles.find((item) => item.agent_type === selectedAgentType) ?? null;
    setDraft(profileToDraft(localProfile));
  }, [registry.profiles, selectedAgentType]);

  async function refreshRegistry(nextAgentType?: string) {
    setPendingAction("refresh");
    try {
      const nextRegistry = await fetchBrowserJson<AgentProfileRegistryData>("/v1/system/agent-profiles");
      setRegistry(nextRegistry);
      const agentType = String(nextAgentType ?? selectedAgentType ?? "").trim();
      if (agentType) {
        const nextDetail = await fetchBrowserJson<AgentProfileDetail>(`/v1/system/agent-profiles/${encodeURIComponent(agentType)}`);
        setDetail(nextDetail);
        setSelectedAgentType(agentType);
        setDraft(profileToDraft(nextDetail.profile));
      } else {
        setDetail(null);
        setDraft(profileToDraft(null));
      }
    } finally {
      setPendingAction(null);
    }
  }

  async function handleSelect(agentType: string) {
    const normalized = String(agentType || "").trim();
    setSelectedAgentType(normalized);
    setMessage("");
    setError("");
    if (!normalized) {
      setDetail(null);
      setDraft(profileToDraft(null));
      return;
    }
    setPendingAction("refresh");
    try {
      const nextDetail = await fetchBrowserJson<AgentProfileDetail>(`/v1/system/agent-profiles/${encodeURIComponent(normalized)}`);
      setDetail(nextDetail);
      setDraft(profileToDraft(nextDetail.profile));
    } catch (loadError) {
      setDetail(null);
      setDraft(profileToDraft(registry.profiles.find((item) => item.agent_type === normalized) ?? null));
      setError(loadError instanceof Error ? loadError.message : t("agentConfig.form.error"));
    } finally {
      setPendingAction(null);
    }
  }

  function handleCreateProfile() {
    setSelectedAgentType("");
    setDetail(null);
    setDraft(profileToDraft(null));
    setMessage("");
    setError("");
  }

  async function handleSave(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const agentType = draft.agent_type.trim();
    if (!agentType) {
      setError(t("agentConfig.form.agentTypeRequired"));
      return;
    }

    setPendingAction("save");
    setMessage("");
    setError("");
    try {
      const payload = await fetchBrowserJson<{ status: string; message?: string; profile: AgentProfile }>(
        `/v1/system/agent-profiles/${encodeURIComponent(agentType)}`,
        {
          method: "POST",
          body: JSON.stringify({
            role: draft.role,
            label: draft.label,
            description: draft.description,
            prompt_blocks: linesToList(draft.prompt_blocks_text),
            tool_profile: draft.tool_profile,
            tool_subset: csvToList(draft.tool_subset_text),
            prompts_root: draft.prompts_root.trim() || undefined,
            enabled: draft.enabled,
            default_for_role: draft.default_for_role,
          }),
        }
      );
      setMessage(payload.message ?? t("agentConfig.form.saveSuccess"));
      await refreshRegistry(agentType);
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : t("agentConfig.form.error"));
    } finally {
      setPendingAction(null);
    }
  }

  async function handleDelete() {
    const agentType = draft.agent_type.trim();
    if (!agentType || draft.builtin) {
      return;
    }
    setPendingAction("delete");
    setMessage("");
    setError("");
    try {
      const payload = await fetchBrowserJson<{ status: string; message?: string }>(
        `/v1/system/agent-profiles/${encodeURIComponent(agentType)}`,
        { method: "DELETE" }
      );
      setMessage(payload.message ?? t("agentConfig.form.deleteSuccess"));
      await refreshRegistry("");
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : t("agentConfig.form.error"));
    } finally {
      setPendingAction(null);
    }
  }

  const selectedProfile = registry.profiles.find((item) => item.agent_type === selectedAgentType) ?? detail?.profile ?? null;
  const promptPresets = Object.entries(registry.tool_profile_presets ?? {});
  const promptTemplates = registry.prompt_templates ?? [];

  return (
    <div className="grid gap-6 xl:grid-cols-[0.9fr_1.1fr]">
      <GlassPanel
        eyebrow={t("agentConfig.registry.eyebrow")}
        title={t("agentConfig.registry.title")}
        description={t("agentConfig.registry.description")}
        actions={
          <button
            type="button"
            onClick={handleCreateProfile}
            className="rounded-full border border-white/70 bg-white/80 px-3 py-1.5 text-xs font-semibold text-slate-600"
          >
            {t("agentConfig.registry.newProfile")}
          </button>
        }
      >
        {registry.profiles.length === 0 ? (
          <EmptyState title={t("agentConfig.registry.emptyTitle")} description={t("agentConfig.registry.emptyDescription")} />
        ) : (
          <div className="space-y-3">
            {registry.profiles.map((profile) => {
              const active = profile.agent_type === selectedAgentType;
              return (
                <button
                  key={profile.agent_type}
                  type="button"
                  onClick={() => handleSelect(profile.agent_type)}
                  className={cx(
                    "w-full rounded-[24px] border px-4 py-4 text-left transition duration-200 ease-embla",
                    active
                      ? "border-slate-900/15 bg-slate-900 text-white shadow-[0_18px_42px_-28px_rgba(15,23,42,0.75)]"
                      : "border-white/70 bg-white/80 text-slate-700 hover:bg-white/90"
                  )}
                >
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <p className="text-sm font-semibold break-all">{profile.agent_type}</p>
                    <div className="flex flex-wrap gap-2 text-[11px] uppercase tracking-[0.16em]">
                      <span className={cx("rounded-full border px-2 py-1", active ? "border-white/20 bg-white/10 text-white/80" : "border-white/70 bg-white text-slate-500")}>{profile.role}</span>
                      {profile.default_for_role ? (
                        <span className={cx("rounded-full border px-2 py-1", active ? "border-emerald-300/30 bg-emerald-300/10 text-white/80" : "border-emerald-200/80 bg-emerald-50 text-emerald-700")}>{t("agentConfig.registry.defaultBadge")}</span>
                      ) : null}
                      {profile.builtin ? (
                        <span className={cx("rounded-full border px-2 py-1", active ? "border-sky-300/30 bg-sky-300/10 text-white/80" : "border-sky-200/80 bg-sky-50 text-sky-700")}>{t("agentConfig.registry.builtinBadge")}</span>
                      ) : null}
                      {profile.enabled === false ? (
                        <span className={cx("rounded-full border px-2 py-1", active ? "border-amber-300/30 bg-amber-300/10 text-white/80" : "border-amber-200/80 bg-amber-50 text-amber-700")}>{t("agentConfig.registry.disabledBadge")}</span>
                      ) : null}
                    </div>
                  </div>
                  <p className={cx("mt-3 text-sm leading-6", active ? "text-white/85" : "text-slate-500")}>
                    {profile.description || t("common.label.noDescription")}
                  </p>
                  <div className={cx("mt-3 flex flex-wrap gap-3 text-xs", active ? "text-white/70" : "text-slate-400")}>
                    <span>{t("agentConfig.registry.promptBlocks", { count: profile.prompt_blocks.length })}</span>
                    <span>{profile.tool_profile || t("agentConfig.registry.customTools")}</span>
                    <span>{formatTimestamp(profile.updated_at, locale)}</span>
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </GlassPanel>

      <div className="space-y-6">
        <GlassPanel
          eyebrow={t("agentConfig.editor.eyebrow")}
          title={t("agentConfig.editor.title")}
          description={t("agentConfig.editor.description")}
        >
          <form className="space-y-4" onSubmit={handleSave}>
            <div className="grid gap-4 md:grid-cols-2">
              <label className="space-y-2 text-sm text-slate-600">
                <span className="font-semibold text-slate-900">{t("agentConfig.form.agentType")}</span>
                <input
                  value={draft.agent_type}
                  onChange={(event) => setDraft((current) => ({ ...current, agent_type: event.target.value }))}
                  className="h-11 w-full rounded-[16px] border border-white/70 bg-white/80 px-4 text-sm text-slate-900 outline-none"
                  placeholder="code_reviewer"
                />
              </label>
              <label className="space-y-2 text-sm text-slate-600">
                <span className="font-semibold text-slate-900">{t("agentConfig.form.role")}</span>
                <select
                  value={draft.role}
                  onChange={(event) => setDraft((current) => ({ ...current, role: event.target.value }))}
                  className="h-11 w-full rounded-[16px] border border-white/70 bg-white/80 px-4 text-sm text-slate-900 outline-none"
                >
                  {(registry.allowed_roles.length > 0 ? registry.allowed_roles : ["expert", "dev", "review"]).map((role) => (
                    <option key={role} value={role}>{role}</option>
                  ))}
                </select>
              </label>
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <label className="space-y-2 text-sm text-slate-600">
                <span className="font-semibold text-slate-900">{t("agentConfig.form.label")}</span>
                <input
                  value={draft.label}
                  onChange={(event) => setDraft((current) => ({ ...current, label: event.target.value }))}
                  className="h-11 w-full rounded-[16px] border border-white/70 bg-white/80 px-4 text-sm text-slate-900 outline-none"
                />
              </label>
              <label className="space-y-2 text-sm text-slate-600">
                <span className="font-semibold text-slate-900">{t("agentConfig.form.toolProfile")}</span>
                <input
                  value={draft.tool_profile}
                  onChange={(event) => setDraft((current) => ({ ...current, tool_profile: event.target.value }))}
                  list="agent-tool-profile-presets"
                  className="h-11 w-full rounded-[16px] border border-white/70 bg-white/80 px-4 text-sm text-slate-900 outline-none"
                  placeholder="review"
                />
                <datalist id="agent-tool-profile-presets">
                  {promptPresets.map(([profileName]) => (
                    <option key={profileName} value={profileName} />
                  ))}
                </datalist>
              </label>
            </div>

            <label className="space-y-2 text-sm text-slate-600">
              <span className="font-semibold text-slate-900">{t("agentConfig.form.description")}</span>
              <textarea
                value={draft.description}
                onChange={(event) => setDraft((current) => ({ ...current, description: event.target.value }))}
                className="min-h-24 w-full rounded-[16px] border border-white/70 bg-white/80 px-4 py-3 text-sm text-slate-900 outline-none"
              />
            </label>

            <div className="grid gap-4 md:grid-cols-2">
              <label className="space-y-2 text-sm text-slate-600">
                <span className="font-semibold text-slate-900">{t("agentConfig.form.promptBlocks")}</span>
                <textarea
                  value={draft.prompt_blocks_text}
                  onChange={(event) => setDraft((current) => ({ ...current, prompt_blocks_text: event.target.value }))}
                  className="min-h-36 w-full rounded-[16px] border border-white/70 bg-white/80 px-4 py-3 text-sm text-slate-900 outline-none"
                  placeholder={t("agentConfig.form.promptBlocksPlaceholder")}
                />
                <p className="text-xs leading-5 text-slate-500">{t("agentConfig.form.promptBlocksHint")}</p>
              </label>
              <div className="space-y-4">
                <label className="space-y-2 text-sm text-slate-600">
                  <span className="font-semibold text-slate-900">{t("agentConfig.form.toolSubset")}</span>
                  <textarea
                    value={draft.tool_subset_text}
                    onChange={(event) => setDraft((current) => ({ ...current, tool_subset_text: event.target.value }))}
                    className="min-h-24 w-full rounded-[16px] border border-white/70 bg-white/80 px-4 py-3 text-sm text-slate-900 outline-none"
                    placeholder="memory_read, memory_grep, memory_tag"
                  />
                  <p className="text-xs leading-5 text-slate-500">{t("agentConfig.form.toolSubsetHint")}</p>
                </label>
                <label className="space-y-2 text-sm text-slate-600">
                  <span className="font-semibold text-slate-900">{t("agentConfig.form.promptsRoot")}</span>
                  <input
                    value={draft.prompts_root}
                    onChange={(event) => setDraft((current) => ({ ...current, prompts_root: event.target.value }))}
                    className="h-11 w-full rounded-[16px] border border-white/70 bg-white/80 px-4 text-sm text-slate-900 outline-none"
                    placeholder={t("agentConfig.form.promptsRootPlaceholder")}
                  />
                  <p className="text-xs leading-5 text-slate-500">{t("agentConfig.form.promptsRootHint")}</p>
                </label>
                <div className="grid gap-3 sm:grid-cols-2">
                  <label className="flex items-center gap-2 rounded-[16px] border border-white/70 bg-white/75 px-4 py-3 text-sm text-slate-700">
                    <input
                      type="checkbox"
                      checked={draft.enabled}
                      onChange={(event) => setDraft((current) => ({ ...current, enabled: event.target.checked }))}
                    />
                    <span>{t("agentConfig.form.enabled")}</span>
                  </label>
                  <label className="flex items-center gap-2 rounded-[16px] border border-white/70 bg-white/75 px-4 py-3 text-sm text-slate-700">
                    <input
                      type="checkbox"
                      checked={draft.default_for_role}
                      onChange={(event) => setDraft((current) => ({ ...current, default_for_role: event.target.checked }))}
                    />
                    <span>{t("agentConfig.form.defaultForRole")}</span>
                  </label>
                </div>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-3">
              <button
                type="submit"
                disabled={pendingAction === "save" || pendingAction === "refresh"}
                className="rounded-xl bg-[#1C1C1E] px-5 py-3 text-sm font-bold text-white shadow-[0_10px_24px_-10px_rgba(0,0,0,0.45)] transition duration-200 ease-embla hover:brightness-110 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-60"
              >
                {pendingAction === "save" ? t("agentConfig.form.saving") : t("agentConfig.form.save")}
              </button>
              <button
                type="button"
                onClick={() => setDraft(profileToDraft(selectedProfile))}
                className="rounded-xl border border-white/70 bg-white/80 px-5 py-3 text-sm font-semibold text-slate-600"
              >
                {t("agentConfig.form.reset")}
              </button>
              {!draft.builtin && draft.agent_type ? (
                <button
                  type="button"
                  onClick={handleDelete}
                  disabled={pendingAction === "delete" || pendingAction === "save"}
                  className="rounded-xl border border-rose-200 bg-rose-50 px-5 py-3 text-sm font-semibold text-rose-700 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {pendingAction === "delete" ? t("agentConfig.form.deleting") : t("agentConfig.form.delete")}
                </button>
              ) : null}
              {message ? <span className="text-sm text-emerald-600">{message}</span> : null}
              {error ? <span className="text-sm text-rose-600">{error}</span> : null}
            </div>
          </form>
        </GlassPanel>

        <GlassPanel
          eyebrow={t("agentConfig.preview.eyebrow")}
          title={t("agentConfig.preview.title")}
          description={t("agentConfig.preview.description")}
        >
          {!detail || detail.prompt_block_previews.length === 0 ? (
            <EmptyState title={t("agentConfig.preview.emptyTitle")} description={t("agentConfig.preview.emptyDescription")} />
          ) : (
            <div className="space-y-3">
              {detail.prompt_block_previews.map((preview) => (
                <div key={preview.relative_path} className="rounded-[24px] border border-white/70 bg-white/80 p-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <p className="text-sm font-semibold text-slate-900 break-all">{preview.relative_path}</p>
                    <div className="text-xs text-slate-400">
                      {preview.exists ? formatTimestamp(preview.updated_at, locale) : t("agentConfig.preview.missing")}
                    </div>
                  </div>
                  <pre className="mt-3 overflow-x-auto whitespace-pre-wrap rounded-[18px] bg-slate-950 px-4 py-3 text-xs leading-6 text-slate-100">{preview.content_preview || t("agentConfig.preview.noContent")}</pre>
                </div>
              ))}
            </div>
          )}
        </GlassPanel>

        <GlassPanel
          eyebrow={t("agentConfig.catalog.eyebrow")}
          title={t("agentConfig.catalog.title")}
          description={t("agentConfig.catalog.description")}
        >
          <div className="grid gap-4 lg:grid-cols-2">
            <div className="soft-inset p-4">
              <p className="text-sm font-semibold text-slate-900">{t("agentConfig.catalog.toolProfiles")}</p>
              <div className="mt-3 space-y-3">
                {promptPresets.map(([profileName, tools]) => (
                  <div key={profileName} className="rounded-[18px] border border-white/70 bg-white/80 p-3">
                    <p className="text-sm font-semibold text-slate-900">{profileName}</p>
                    <p className="mt-2 text-xs leading-5 text-slate-500">{tools.join(", ")}</p>
                  </div>
                ))}
              </div>
            </div>
            <div className="soft-inset p-4">
              <p className="text-sm font-semibold text-slate-900">{t("agentConfig.catalog.promptTemplates")}</p>
              <div className="mt-3 max-h-[360px] space-y-3 overflow-y-auto pr-1">
                {promptTemplates.map((template) => (
                  <div key={`${template.relative_path ?? template.name}`} className="rounded-[18px] border border-white/70 bg-white/80 p-3">
                    <p className="text-sm font-semibold text-slate-900 break-all">{template.relative_path || template.name}</p>
                    <p className="mt-2 text-xs text-slate-500">{template.name}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </GlassPanel>
      </div>
    </div>
  );
}
