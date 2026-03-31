"use client";

import { FormEvent, useState } from "react";

import { EmptyState, GlassPanel } from "@/components/dashboard-ui";
import { buildBrowserApiUrl, extractApiErrorMessage } from "@/lib/client-api";
import { AppLocale, translate } from "@/lib/i18n";

interface SearchResult {
  subject: string;
  subject_type?: string;
  predicate: string;
  object: string;
  object_type?: string;
}

interface SearchResponse {
  count?: number;
  quintuples?: SearchResult[];
  detail?: string;
  reason_text?: string | null;
  data?: {
    summary?: {
      result_count?: number;
      returned_count?: number;
    };
    results?: SearchResult[];
  };
}

function normalizeSearchResult(row: unknown): SearchResult | null {
  if (!row || typeof row !== "object" || Array.isArray(row)) {
    return null;
  }

  const item = row as Record<string, unknown>;
  const subject = String(item.subject ?? item.entity ?? "").trim();
  const predicate = String(item.predicate ?? item.relation ?? "").trim();
  const object = String(item.object ?? item.target ?? "").trim();
  if (!subject && !predicate && !object) {
    return null;
  }

  return {
    subject,
    subject_type: String(item.subject_type ?? item.entity_type ?? "").trim(),
    predicate,
    object,
    object_type: String(item.object_type ?? item.target_type ?? "").trim()
  };
}

function extractSearchResults(payload: SearchResponse) {
  const canonicalItems = Array.isArray(payload.data?.results) ? payload.data?.results : [];
  const rawItems = Array.isArray(payload.quintuples) ? payload.quintuples : [];
  const items = (canonicalItems.length > 0 ? canonicalItems : rawItems)
    .map((item) => normalizeSearchResult(item))
    .filter((item): item is SearchResult => Boolean(item));
  const total = Number(payload.data?.summary?.result_count ?? payload.count ?? items.length);
  return { items, total };
}

async function fetchSearchPayload(endpoint: string, keywords: string) {
  const url = new URL(buildBrowserApiUrl(endpoint));
  url.searchParams.set("keywords", keywords);
  url.searchParams.set("limit", "12");

  const response = await fetch(url.toString(), { cache: "no-store" });
  const payload = (await response.json()) as SearchResponse;
  if (!response.ok) {
    throw new Error(extractApiErrorMessage(payload, "Request failed"));
  }
  return payload;
}

export function MemorySearchPanel({ defaultKeywords, locale }: { defaultKeywords: string[]; locale: AppLocale }) {
  const [keywords, setKeywords] = useState(defaultKeywords.join(", "));
  const [results, setResults] = useState<SearchResult[]>([]);
  const [meta, setMeta] = useState<string>(translate(locale, "memorySearch.initialMeta"));
  const [pending, setPending] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setMeta(translate(locale, "memorySearch.submitting"));

    try {
      const startedAt = performance.now();
      let payload: SearchResponse;

      try {
        payload = await fetchSearchPayload("/v1/ops/memory/search", keywords);
      } catch {
        payload = await fetchSearchPayload("/memory/quintuples/search", keywords);
      }

      const elapsed = Math.round(performance.now() - startedAt);
      const { items, total } = extractSearchResults(payload);
      setResults(items.slice(0, 12));
      setMeta(translate(locale, "memorySearch.resultMeta", { total, elapsed }));
    } catch (error) {
      setResults([]);
      setMeta(error instanceof Error ? error.message : translate(locale, "common.label.queryFailed"));
    } finally {
      setPending(false);
    }
  }

  return (
    <GlassPanel eyebrow={translate(locale, "memorySearch.eyebrow")} title={translate(locale, "memorySearch.title")} description={translate(locale, "memorySearch.description")}>
      <form className="flex flex-col gap-3 lg:flex-row" onSubmit={handleSubmit}>
        <div className="soft-inset flex-1 p-2">
          <input
            className="h-11 w-full rounded-[16px] border border-white/70 bg-white/80 px-4 text-sm text-slate-900 outline-none"
            value={keywords}
            onChange={(event) => setKeywords(event.target.value)}
            placeholder={translate(locale, "memorySearch.placeholder")}
          />
        </div>
        <button
          type="submit"
          disabled={pending}
          className="rounded-xl bg-[#1C1C1E] px-5 py-3 text-sm font-bold text-white shadow-[0_10px_24px_-10px_rgba(0,0,0,0.45)] transition duration-200 ease-embla hover:brightness-110 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-60"
        >
          {pending ? translate(locale, "memorySearch.submitting") : translate(locale, "memorySearch.submit")}
        </button>
      </form>

      <p className="mt-4 text-sm text-slate-500">{meta}</p>

      <div className="mt-4 space-y-3">
        {results.length === 0 ? (
          <EmptyState title={translate(locale, "memorySearch.emptyTitle")} description={translate(locale, "memorySearch.emptyDescription")} />
        ) : (
          results.map((item, index) => (
            <div key={`${item.subject}-${item.object}-${item.predicate}-${index}`} className="soft-inset p-4">
              <p className="text-sm font-semibold text-slate-900">
                {item.subject} <span className="text-slate-400">{item.predicate}</span> {item.object}
              </p>
              <p className="mt-2 text-xs text-slate-500">
                {item.subject_type || translate(locale, "memorySearch.unknownType")} → {item.object_type || translate(locale, "memorySearch.unknownType")}
              </p>
            </div>
          ))
        )}
      </div>
    </GlassPanel>
  );
}
