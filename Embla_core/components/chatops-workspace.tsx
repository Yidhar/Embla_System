"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ChatOpsConsole } from "@/components/chatops-console";
import { EmptyState, GlassPanel, StatusBadge } from "@/components/dashboard-ui";
import { buildBrowserApiUrl, extractApiErrorMessage } from "@/lib/client-api";
import { cx, formatTimestamp } from "@/lib/format";
import { AppLocale, createTranslator, humanizeEnum } from "@/lib/i18n";
import {
  ChatCoreAsyncUpdate,
  ChatRouteSessionStateData,
  ChatSessionMessage,
  ShellToolDefinition,
  TaskHeartbeatRecord,
  TaskHeartbeatSession
} from "@/lib/types";
import { numberValue } from "@/lib/view-models";

type StreamEventPayload = Record<string, unknown>;
type StreamLifecycle = "idle" | "connecting" | "live" | "reconnecting" | "error";

type ChatOpsWorkspaceProps = {
  locale: AppLocale;
  selectedSessionId?: string;
  initialMessages?: ChatSessionMessage[];
  initialTools?: ShellToolDefinition[];
  initialRouteState?: ChatRouteSessionStateData | null;
};

function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function listValue<T = unknown>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

function stringValue(value: unknown, fallback = "") {
  const text = String(value ?? "").trim();
  return text || fallback;
}

function normalizeCoreAsyncUpdate(input: unknown): ChatCoreAsyncUpdate | null {
  const row = recordValue(input);
  const seq = numberValue(row.seq, 0);
  const content = stringValue(row.content);
  const coreJobId = stringValue(row.core_job_id);
  const runContextId = stringValue(row.run_context_id || row.core_execution_session_id);
  if (seq <= 0 && !content && !coreJobId) {
    return null;
  }
  return {
    seq,
    from_id: stringValue(row.from_id),
    to_id: stringValue(row.to_id),
    message_type: stringValue(row.message_type),
    kind: stringValue(row.kind),
    status: stringValue(row.status),
    core_job_id: coreJobId,
    run_context_id: runContextId,
    core_runtime_id: stringValue(row.core_runtime_id),
    core_execution_session_id: runContextId || undefined,
    pipeline_id: stringValue(row.pipeline_id),
    pending_descendant_count: numberValue(row.pending_descendant_count),
    content,
    created_at: stringValue(row.created_at),
    metadata: recordValue(row.metadata),
    is_terminal: Boolean(row.is_terminal)
  };
}

function normalizeTaskHeartbeatSession(input: unknown): TaskHeartbeatSession | null {
  const row = recordValue(input);
  const sessionId = stringValue(row.session_id);
  if (!sessionId) {
    return null;
  }
  return {
    session_id: sessionId,
    parent_id: stringValue(row.parent_id),
    role: stringValue(row.role),
    status: stringValue(row.status),
    heartbeat_summary: recordValue(row.heartbeat_summary)
  };
}

function normalizeTaskHeartbeatRecord(input: unknown): TaskHeartbeatRecord | null {
  const row = recordValue(input);
  const sessionId = stringValue(row.session_id);
  const taskId = stringValue(row.task_id);
  if (!sessionId || !taskId) {
    return null;
  }
  return {
    session_id: sessionId,
    task_id: taskId,
    parent_id: stringValue(row.parent_id),
    role: stringValue(row.role),
    scope: stringValue(row.scope),
    status: stringValue(row.status),
    message: stringValue(row.message),
    progress: row.progress === null || row.progress === undefined ? null : numberValue(row.progress),
    stage: stringValue(row.stage),
    ttl_seconds: numberValue(row.ttl_seconds),
    sequence: numberValue(row.sequence),
    generated_at: stringValue(row.generated_at),
    expires_at: stringValue(row.expires_at),
    stale_level: stringValue(row.stale_level),
    escalation_state: stringValue(row.escalation_state),
    seconds_since_heartbeat: row.seconds_since_heartbeat === null || row.seconds_since_heartbeat === undefined
      ? null
      : numberValue(row.seconds_since_heartbeat),
    details: recordValue(row.details)
  };
}

function mergeCoreAsyncUpdates(
  current: ChatCoreAsyncUpdate[],
  incoming: ChatCoreAsyncUpdate[],
  limit = 12
) {
  const merged = new Map<number, ChatCoreAsyncUpdate>();
  for (const item of current) {
    merged.set(numberValue(item.seq), item);
  }
  for (const item of incoming) {
    merged.set(numberValue(item.seq), item);
  }
  return [...merged.values()]
    .sort((left, right) => numberValue(right.seq) - numberValue(left.seq))
    .slice(0, limit);
}

function createEmptyRouteState(sessionId: string): ChatRouteSessionStateData {
  return {
    status: "success",
    shell_session_id: sessionId,
    run_context_id: "",
    shell_session_exists: true,
    run_context_exists: false,
    child_heartbeat_summary: {},
    child_heartbeat_sessions: [],
    child_heartbeats: [],
    state: {},
    recent_route_events: [],
    recent_core_updates: [],
    unread_core_updates: [],
    pending_core_update_count: 0,
    active_core_job: {},
    latest_core_job: {}
  };
}

function normalizeRouteState(input: unknown, sessionIdFallback = ""): ChatRouteSessionStateData | null {
  const row = recordValue(input);
  const shellSessionId = stringValue(row.shell_session_id, sessionIdFallback);
  const runContextId = stringValue(row.run_context_id || row.core_execution_session_id);
  const runContextExists = Boolean(row.run_context_exists ?? row.core_execution_session_exists ?? runContextId);
  const state = recordValue(row.state);
  if (!shellSessionId) {
    return null;
  }
  const childHeartbeatSessions = listValue(row.child_heartbeat_sessions)
    .map((item) => normalizeTaskHeartbeatSession(item))
    .filter((item): item is TaskHeartbeatSession => Boolean(item));
  const childHeartbeats = listValue(row.child_heartbeats)
    .map((item) => normalizeTaskHeartbeatRecord(item))
    .filter((item): item is TaskHeartbeatRecord => Boolean(item));
  return {
    status: stringValue(row.status, "success"),
    shell_session_id: shellSessionId,
    run_context_id: runContextId,
    core_execution_session_id: runContextId || undefined,
    last_run_context_id: stringValue(row.last_run_context_id || state.last_run_context_id || row.last_core_execution_session_id),
    last_core_execution_session_id: stringValue(row.last_core_execution_session_id || row.last_run_context_id || state.last_run_context_id),
    shell_session_exists: row.shell_session_exists !== false,
    run_context_exists: runContextExists,
    core_execution_session_exists: Boolean(row.core_execution_session_exists ?? runContextExists),
    core_runtime_id: stringValue(row.core_runtime_id),
    active_core_job_id: stringValue(row.active_core_job_id),
    active_core_job_ids: listValue(row.active_core_job_ids).map((item) => stringValue(item)).filter(Boolean),
    current_core_job_id: stringValue(row.current_core_job_id),
    queued_core_job_ids: listValue(row.queued_core_job_ids).map((item) => stringValue(item)).filter(Boolean),
    core_worker_status: stringValue(row.core_worker_status),
    core_queue_depth: numberValue(row.core_queue_depth),
    core_pipeline_depth: numberValue(row.core_pipeline_depth),
    core_mailbox_cursor_seq: numberValue(row.core_mailbox_cursor_seq),
    last_core_handoff_message_seq: numberValue(row.last_core_handoff_message_seq),
    last_core_completion_message_seq: numberValue(row.last_core_completion_message_seq),
    core_recovery_restart_total: numberValue(row.core_recovery_restart_total),
    core_job_watch_dedup_skipped_count: numberValue(row.core_job_watch_dedup_skipped_count),
    core_last_dedup_message_seq: numberValue(row.core_last_dedup_message_seq),
    latest_core_job_id: stringValue(row.latest_core_job_id),
    active_core_job: recordValue(row.active_core_job),
    latest_core_job: recordValue(row.latest_core_job),
    recent_core_jobs: listValue(row.recent_core_jobs).map((item) => recordValue(item)),
    recent_core_updates: listValue(row.recent_core_updates)
      .map((item) => normalizeCoreAsyncUpdate(item))
      .filter((item): item is ChatCoreAsyncUpdate => Boolean(item)),
    unread_core_updates: listValue(row.unread_core_updates)
      .map((item) => normalizeCoreAsyncUpdate(item))
      .filter((item): item is ChatCoreAsyncUpdate => Boolean(item)),
    pending_core_update_count: numberValue(row.pending_core_update_count),
    recent_core_reports: listValue(row.recent_core_reports).map((item) => recordValue(item)),
    child_heartbeat_summary: recordValue(row.child_heartbeat_summary),
    child_heartbeat_sessions: childHeartbeatSessions,
    child_heartbeats: childHeartbeats,
    state,
    recent_route_events: listValue(row.recent_route_events).map((item) => recordValue(item))
  };
}

function applyCoreAsyncEnvelope(
  current: ChatRouteSessionStateData | null,
  sessionId: string,
  payload: StreamEventPayload
) {
  const next = current ? { ...current } : createEmptyRouteState(sessionId);
  const nextState = { ...recordValue(next.state) };
  const eventType = stringValue(payload.type);
  const runContextId = stringValue(payload.run_context_id || payload.core_execution_session_id, next.run_context_id);
  const activeCoreJob = recordValue(payload.active_core_job);
  const latestCoreJob = recordValue(payload.latest_core_job);

  if (eventType === "core_job_accepted") {
    const acceptedStatus = stringValue(payload.status, "accepted");
    const coreJobId = stringValue(payload.core_job_id);
    next.core_runtime_id = stringValue(payload.core_runtime_id, next.core_runtime_id);
    next.run_context_id = runContextId;
    next.run_context_exists = Boolean(runContextId);
    next.core_execution_session_exists = Boolean(runContextId);
    next.active_core_job_id = coreJobId;
    next.current_core_job_id = coreJobId;
    next.latest_core_job_id = coreJobId;
    next.core_worker_status = stringValue(payload.worker_status, next.core_worker_status);
    next.core_queue_depth = numberValue(payload.queue_depth, next.core_queue_depth);
    next.core_pipeline_depth = numberValue(payload.pipeline_depth, next.core_pipeline_depth);
    next.active_core_job = {
      ...(next.active_core_job ?? {}),
      job_id: coreJobId,
      status: acceptedStatus,
      goal: stringValue(payload.goal),
      queue_position: numberValue(payload.queue_position),
      queue_depth: numberValue(payload.queue_depth),
      pipeline_depth: numberValue(payload.pipeline_depth),
      run_context_id: runContextId
    };
    next.latest_core_job = {
      ...(next.latest_core_job ?? {}),
      ...(next.active_core_job ?? {})
    };
    next.pending_core_update_count = Math.max(0, numberValue(next.pending_core_update_count));
    nextState.last_dispatch_to_core = true;
    nextState.last_route_semantic = "core_execution";
    nextState.last_handoff_tool = "dispatch_to_core";
    nextState.last_core_job_id = coreJobId;
    nextState.current_core_job_id = coreJobId;
  } else if (eventType === "core_async_state") {
    if (runContextId) {
      next.run_context_id = runContextId;
      next.run_context_exists = true;
      next.core_execution_session_exists = true;
    }
    next.active_core_job = activeCoreJob;
    next.latest_core_job = latestCoreJob;
    next.active_core_job_id = stringValue(activeCoreJob.job_id, next.active_core_job_id);
    next.latest_core_job_id = stringValue(latestCoreJob.job_id, next.latest_core_job_id);
    next.current_core_job_id = stringValue(activeCoreJob.job_id, next.current_core_job_id);
    next.core_worker_status = stringValue(payload.core_worker_status, next.core_worker_status);
    next.pending_core_update_count = numberValue(payload.pending_core_update_count, next.pending_core_update_count);
    const asyncStatePayloadState = recordValue(payload.state);
    nextState.core_outbox_cursor_seq = numberValue(asyncStatePayloadState.core_outbox_cursor_seq ?? payload.core_outbox_cursor_seq, numberValue(nextState.core_outbox_cursor_seq));
    nextState.last_core_outbox_seq = numberValue(asyncStatePayloadState.last_core_outbox_seq ?? payload.last_core_outbox_seq, numberValue(nextState.last_core_outbox_seq));
    nextState.pending_core_update_count = next.pending_core_update_count;
  } else if (eventType === "core_async_update") {
    const incomingUpdates = listValue(payload.updates)
      .map((item) => normalizeCoreAsyncUpdate(item))
      .filter((item): item is ChatCoreAsyncUpdate => Boolean(item));
    if (runContextId) {
      next.run_context_id = runContextId;
      next.run_context_exists = true;
      next.core_execution_session_exists = true;
    }
    next.active_core_job = activeCoreJob;
    next.latest_core_job = latestCoreJob;
    next.active_core_job_id = stringValue(activeCoreJob.job_id, next.active_core_job_id);
    next.latest_core_job_id = stringValue(latestCoreJob.job_id, next.latest_core_job_id);
    next.recent_core_updates = mergeCoreAsyncUpdates(next.recent_core_updates ?? [], incomingUpdates);
    next.unread_core_updates = mergeCoreAsyncUpdates(next.unread_core_updates ?? [], incomingUpdates, 8);
    next.pending_core_update_count = numberValue(payload.pending_core_update_count, next.pending_core_update_count);
    next.core_worker_status = stringValue(payload.core_worker_status, next.core_worker_status);
    const asyncUpdatePayloadState = recordValue(payload.state);
    nextState.core_outbox_cursor_seq = numberValue(asyncUpdatePayloadState.core_outbox_cursor_seq ?? payload.core_outbox_cursor_seq, numberValue(nextState.core_outbox_cursor_seq));
    nextState.last_core_outbox_seq = numberValue(asyncUpdatePayloadState.last_core_outbox_seq ?? payload.last_core_outbox_seq, numberValue(nextState.last_core_outbox_seq));
    nextState.pending_core_update_count = next.pending_core_update_count;
  }

  next.state = nextState;
  return next;
}

function getCoreStreamSeverity(state: StreamLifecycle) {
  if (state === "live") {
    return "ok" as const;
  }
  if (state === "connecting" || state === "reconnecting") {
    return "warning" as const;
  }
  if (state === "error") {
    return "critical" as const;
  }
  return "unknown" as const;
}

function getCoreJobSeverity(status: string) {
  const normalized = status.trim().toLowerCase();
  if (normalized === "completed" || normalized === "running" || normalized === "accepted") {
    return "ok" as const;
  }
  if (normalized === "waiting_descendants" || normalized === "queued" || normalized === "resumed") {
    return "warning" as const;
  }
  if (normalized === "blocked" || normalized === "failed" || normalized === "reject") {
    return "critical" as const;
  }
  return "unknown" as const;
}

function hasSelectedCoreJobWatch(routeState: ChatRouteSessionStateData | null, sessionId: string) {
  if (!routeState || stringValue(routeState.shell_session_id) !== stringValue(sessionId)) {
    return false;
  }
  if (stringValue(routeState.active_core_job_id) || stringValue(routeState.latest_core_job_id)) {
    return true;
  }
  if (numberValue(routeState.pending_core_update_count) > 0) {
    return true;
  }
  if ((routeState.recent_core_updates ?? []).length > 0 || (routeState.unread_core_updates ?? []).length > 0) {
    return true;
  }
  return Boolean(recordValue(routeState.state).last_dispatch_to_core);
}

export function ChatOpsWorkspace({
  locale,
  selectedSessionId = "",
  initialMessages = [],
  initialTools = [],
  initialRouteState = null
}: ChatOpsWorkspaceProps) {
  const t = createTranslator(locale);
  const [sessionId, setSessionId] = useState(selectedSessionId);
  const [routeState, setRouteState] = useState<ChatRouteSessionStateData | null>(initialRouteState);
  const [streamLifecycle, setStreamLifecycle] = useState<StreamLifecycle>("idle");
  const [streamError, setStreamError] = useState<string | null>(null);
  const [lastAsyncUpdateAt, setLastAsyncUpdateAt] = useState("");
  const eventSourceRef = useRef<EventSource | null>(null);
  const refreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const sessionIdRef = useRef(selectedSessionId);

  useEffect(() => {
    sessionIdRef.current = sessionId;
  }, [sessionId]);

  useEffect(() => {
    setSessionId(selectedSessionId);
    setRouteState(initialRouteState);
    setStreamLifecycle("idle");
    setStreamError(null);
    setLastAsyncUpdateAt("");
  }, [initialRouteState, selectedSessionId]);

  const refreshRouteState = useCallback(async (targetSessionId: string) => {
    const normalizedSessionId = stringValue(targetSessionId);
    if (!normalizedSessionId) {
      return;
    }
    try {
      const response = await fetch(buildBrowserApiUrl(`/v1/chat/route_session_state/${encodeURIComponent(normalizedSessionId)}`), {
        cache: "no-store"
      });
      if (!response.ok) {
        if (response.status === 404) {
          setRouteState(null);
          return;
        }
        const payload = await response.json().catch(() => ({}));
        throw new Error(extractApiErrorMessage(payload, `route_session_state ${response.status}`));
      }
      const payload = normalizeRouteState(await response.json(), normalizedSessionId);
      if (sessionIdRef.current === normalizedSessionId) {
        setRouteState(payload);
      }
    } catch (error) {
      if (sessionIdRef.current === normalizedSessionId) {
        setStreamError(error instanceof Error ? error.message : t("chatops.jobWatch.snapshotError"));
      }
    }
  }, [t]);

  const hydrateCoreInbox = useCallback(async (targetSessionId: string) => {
    const normalizedSessionId = stringValue(targetSessionId);
    if (!normalizedSessionId) {
      return;
    }
    try {
      const response = await fetch(buildBrowserApiUrl(`/v1/chat/core_job_watch/${encodeURIComponent(normalizedSessionId)}?limit=20&ack=false`), {
        cache: "no-store"
      });
      if (!response.ok) {
        if (response.status === 404) {
          return;
        }
        const payload = await response.json().catch(() => ({}));
        throw new Error(extractApiErrorMessage(payload, `core_job_watch ${response.status}`));
      }
      const payload = recordValue(await response.json());
      const envelope: StreamEventPayload = {
        type: "core_async_update",
        shell_session_id: normalizedSessionId,
        run_context_id: stringValue(payload.run_context_id || payload.core_execution_session_id),
        core_execution_session_id: stringValue(payload.run_context_id || payload.core_execution_session_id),
        active_core_job: recordValue(payload.active_core_job),
        latest_core_job: recordValue(payload.latest_core_job),
        core_worker_status: stringValue(payload.core_worker_status),
        pending_core_update_count: numberValue(payload.pending_core_update_count),
        core_outbox_cursor_seq: numberValue(payload.core_outbox_cursor_seq),
        last_core_outbox_seq: numberValue(payload.last_core_outbox_seq),
        updates: listValue(payload.unread_core_updates).length > 0 ? payload.unread_core_updates : payload.recent_core_updates
      };
      setRouteState((current) => applyCoreAsyncEnvelope(current, normalizedSessionId, envelope));
    } catch (error) {
      if (sessionIdRef.current === normalizedSessionId) {
        setStreamError(error instanceof Error ? error.message : t("chatops.jobWatch.snapshotError"));
      }
    }
  }, [t]);

  const scheduleRouteRefresh = useCallback((targetSessionId: string) => {
    const normalizedSessionId = stringValue(targetSessionId);
    if (!normalizedSessionId) {
      return;
    }
    if (refreshTimerRef.current) {
      clearTimeout(refreshTimerRef.current);
    }
    refreshTimerRef.current = setTimeout(() => {
      refreshTimerRef.current = null;
      void refreshRouteState(normalizedSessionId);
    }, 300);
  }, [refreshRouteState]);

  const handleRuntimeEvent = useCallback((payload: StreamEventPayload) => {
    const eventType = stringValue(payload.type);
    const targetSessionId = stringValue(payload.shell_session_id, sessionIdRef.current);
    if (!targetSessionId) {
      return;
    }
    if (eventType === "session_meta") {
      const nextSessionId = stringValue(payload.session_id);
      if (nextSessionId) {
        setSessionId(nextSessionId);
      }
      return;
    }
    if (eventType !== "core_job_accepted" && eventType !== "core_async_state" && eventType !== "core_async_update") {
      return;
    }
    setLastAsyncUpdateAt(new Date().toISOString());
    setRouteState((current) => applyCoreAsyncEnvelope(current, targetSessionId, payload));
    scheduleRouteRefresh(targetSessionId);
  }, [scheduleRouteRefresh]);

  useEffect(() => {
    if (refreshTimerRef.current) {
      clearTimeout(refreshTimerRef.current);
      refreshTimerRef.current = null;
    }
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }

    const normalizedSessionId = stringValue(sessionId);
    if (!normalizedSessionId) {
      setStreamLifecycle("idle");
      return;
    }

    if (!initialRouteState || normalizedSessionId !== stringValue(initialRouteState.shell_session_id)) {
      void refreshRouteState(normalizedSessionId);
    }
    const hasWatchedJob = hasSelectedCoreJobWatch(routeState, normalizedSessionId);
    if (!hasWatchedJob) {
      setStreamLifecycle("idle");
      return;
    }

    void hydrateCoreInbox(normalizedSessionId);

    const connect = (reconnecting = false) => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
      setStreamLifecycle(reconnecting ? "reconnecting" : "connecting");
      const eventSource = new EventSource(
        buildBrowserApiUrl(`/v1/chat/core_job_watch/stream/${encodeURIComponent(normalizedSessionId)}?limit=20&heartbeat_seconds=2`)
      );
      eventSourceRef.current = eventSource;

      eventSource.onopen = () => {
        if (sessionIdRef.current !== normalizedSessionId) {
          eventSource.close();
          return;
        }
        setStreamLifecycle("live");
        setStreamError(null);
      };

      eventSource.onmessage = (event) => {
        try {
          const payload = JSON.parse(String(event.data ?? "{}")) as StreamEventPayload;
          handleRuntimeEvent(payload);
        } catch {
          return;
        }
      };

      eventSource.onerror = () => {
        eventSource.close();
        if (sessionIdRef.current !== normalizedSessionId) {
          return;
        }
        setStreamLifecycle("reconnecting");
        if (reconnectTimerRef.current) {
          clearTimeout(reconnectTimerRef.current);
        }
        reconnectTimerRef.current = setTimeout(() => {
          reconnectTimerRef.current = null;
          if (sessionIdRef.current === normalizedSessionId) {
            void hydrateCoreInbox(normalizedSessionId);
            connect(true);
          }
        }, 1500);
      };
    };

    connect(false);

    return () => {
      if (refreshTimerRef.current) {
        clearTimeout(refreshTimerRef.current);
        refreshTimerRef.current = null;
      }
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
        eventSourceRef.current = null;
      }
    };
  }, [handleRuntimeEvent, hydrateCoreInbox, initialRouteState, refreshRouteState, routeState, sessionId]);

  const coreUpdates = useMemo(
    () => (routeState?.recent_core_updates ?? []).slice(0, 6),
    [routeState?.recent_core_updates]
  );

  const activeCoreJob = recordValue(routeState?.active_core_job);
  const latestCoreJob = recordValue(routeState?.latest_core_job);
  const activeCoreJobId = stringValue(activeCoreJob.job_id || routeState?.active_core_job_id);
  const activeCoreJobStatus = stringValue(activeCoreJob.status || routeState?.core_worker_status);
  const pendingCoreUpdateCount = numberValue(routeState?.pending_core_update_count);
  const coreStreamLabelKey =
    streamLifecycle === "live"
      ? "chatops.jobWatch.streamLive"
      : streamLifecycle === "connecting"
        ? "chatops.jobWatch.streamConnecting"
        : streamLifecycle === "reconnecting"
          ? "chatops.jobWatch.streamReconnecting"
          : streamLifecycle === "error"
            ? "chatops.jobWatch.streamError"
            : "chatops.jobWatch.streamIdle";

  return (
    <div className="space-y-6">
      <ChatOpsConsole
        locale={locale}
        selectedSessionId={sessionId}
        initialMessages={initialMessages}
        initialTools={initialTools}
        onSessionIdChange={setSessionId}
        onStreamEvent={handleRuntimeEvent}
      />

      {!sessionId ? (
        <GlassPanel eyebrow={t("chatops.waiting.eyebrow")} title={t("chatops.waiting.title")} description={t("chatops.waiting.description")}>
          <EmptyState title={t("chatops.waiting.emptyTitle")} description={t("chatops.waiting.emptyDescription")} />
        </GlassPanel>
      ) : !routeState ? (
        <GlassPanel eyebrow={t("chatops.lookupMiss.eyebrow")} title={t("chatops.lookupMiss.title")} description={t("chatops.lookupMiss.description")}>
          <EmptyState title={t("chatops.lookupMiss.emptyTitle")} description={t("chatops.lookupMiss.emptyDescription", { sessionId })} />
        </GlassPanel>
      ) : (
        <div className="grid gap-6 xl:grid-cols-3">
          <GlassPanel
            eyebrow={t("chatops.jobWatch.eyebrow")}
            title={t("chatops.jobWatch.title")}
            description={t("chatops.jobWatch.description")}
            actions={<StatusBadge severity={getCoreStreamSeverity(streamLifecycle)} label={t(coreStreamLabelKey)} locale={locale} />}
          >
            {activeCoreJobId || coreUpdates.length > 0 || stringValue(latestCoreJob.job_id) ? (
              <div className="space-y-3">
                <div className="rounded-[24px] border border-white/70 bg-white/75 p-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <p className="text-sm font-semibold text-slate-900">{t("chatops.jobWatch.activeJob")}</p>
                    <StatusBadge severity={getCoreJobSeverity(activeCoreJobStatus)} label={activeCoreJobStatus || t("common.label.unknown")} locale={locale} />
                  </div>
                  <p className="mt-2 break-all text-sm text-slate-500">{activeCoreJobId || stringValue(latestCoreJob.job_id) || t("chatops.jobWatch.noJob")}</p>
                  {stringValue(activeCoreJob.goal || latestCoreJob.goal) ? (
                    <p className="mt-2 text-sm leading-6 text-slate-600">{stringValue(activeCoreJob.goal || latestCoreJob.goal)}</p>
                  ) : null}
                  <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-500">
                    <span className="rounded-full border border-white/70 bg-white/80 px-3 py-1">
                      {t("chatops.jobWatch.workerStatus")}: {stringValue(routeState.core_worker_status, t("common.label.unknown"))}
                    </span>
                    <span className="rounded-full border border-white/70 bg-white/80 px-3 py-1">
                      {t("chatops.jobWatch.queueDepth", { count: String(numberValue(routeState.core_queue_depth)) })}
                    </span>
                    <span className="rounded-full border border-white/70 bg-white/80 px-3 py-1">
                      {t("chatops.jobWatch.pendingUpdates", { count: String(pendingCoreUpdateCount) })}
                    </span>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-500">
                    <span className="rounded-full border border-white/70 bg-white/80 px-3 py-1">
                      {t("chatops.jobWatch.runContext")}: {routeState.run_context_id || t("chatops.jobWatch.noRunContext")}
                    </span>
                  </div>
                  {lastAsyncUpdateAt ? (
                    <p className="mt-3 text-xs text-slate-400">
                      {t("chatops.jobWatch.lastUpdate")}: {formatTimestamp(lastAsyncUpdateAt, locale)}
                    </p>
                  ) : null}
                  {streamError ? <p className="mt-2 text-sm text-rose-500">{streamError}</p> : null}
                </div>

                {coreUpdates.length === 0 ? (
                  <EmptyState title={t("chatops.jobWatch.emptyTitle")} description={t("chatops.jobWatch.emptyDescription")} />
                ) : (
                  <div className="space-y-3">
                    {coreUpdates.map((item) => (
                      <div key={`${item.seq}-${item.core_job_id || "core"}`} className="rounded-[24px] border border-white/70 bg-white/75 p-4">
                        <div className="flex flex-wrap items-center justify-between gap-3">
                          <p className="text-sm font-semibold text-slate-900">
                            {item.core_job_id || item.kind || item.message_type || t("chatops.jobWatch.update")}
                          </p>
                          <span className="text-xs uppercase tracking-[0.18em] text-slate-400">
                            {item.status || item.message_type || t("common.label.unknown")}
                          </span>
                        </div>
                        <p className="mt-2 text-sm text-slate-500">{item.created_at ? formatTimestamp(item.created_at, locale) : t("common.label.unknown")}</p>
                        <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-slate-600">
                          {item.content || JSON.stringify(item.metadata ?? {}, null, 2)}
                        </p>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ) : (
              <EmptyState title={t("chatops.jobWatch.emptyTitle")} description={t("chatops.jobWatch.emptyDescription")} />
            )}
          </GlassPanel>

          <GlassPanel eyebrow={t("chatops.heartbeat.eyebrow")} title={t("chatops.heartbeat.title")} description={t("chatops.heartbeat.description")}>
            {routeState.child_heartbeats.length === 0 ? (
              <EmptyState title={t("chatops.heartbeat.emptyTitle")} description={t("chatops.heartbeat.emptyDescription")} />
            ) : (
              <div className="space-y-3">
                {routeState.child_heartbeats.map((heartbeat) => (
                  <div key={`${heartbeat.session_id}-${heartbeat.task_id}`} className="rounded-[24px] border border-white/70 bg-white/75 p-4">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <p className="text-sm font-semibold text-slate-900">{heartbeat.task_id}</p>
                      <span className="text-xs uppercase tracking-[0.18em] text-slate-400">{humanizeEnum(locale, "staleLevel", heartbeat.stale_level ?? "fresh")}</span>
                    </div>
                    <p className="mt-2 text-sm text-slate-500">{heartbeat.session_id} · {heartbeat.stage || heartbeat.status || t("common.label.running")}</p>
                    <p className="mt-2 text-sm leading-6 text-slate-600">{heartbeat.message || t("chatops.heartbeat.noMessage")}</p>
                  </div>
                ))}
              </div>
            )}
          </GlassPanel>

          <GlassPanel eyebrow={t("chatops.routeSnapshot.eyebrow")} title={t("chatops.routeSnapshot.title")} description={t("chatops.routeSnapshot.description")}>
            <div className="space-y-3">
              <div className="rounded-[24px] border border-white/70 bg-white/75 p-4">
                <p className="text-sm font-semibold text-slate-900">{t("chatops.routeSnapshot.shellSession")}</p>
                <p className="mt-2 break-all text-sm text-slate-500">{routeState.shell_session_id}</p>
              </div>
              <div className="rounded-[24px] border border-white/70 bg-white/75 p-4">
                <p className="text-sm font-semibold text-slate-900">{t("chatops.routeSnapshot.coreRunContext")}</p>
                <p className="mt-2 break-all text-sm text-slate-500">{routeState.run_context_id || t("chatops.routeSnapshot.noHandoff")}</p>
              </div>
              <div className="rounded-[24px] border border-white/70 bg-white/75 p-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <p className="text-sm font-semibold text-slate-900">{t("chatops.routeSnapshot.recentRouteEvents")}</p>
                  <span className={cx("rounded-full border border-white/70 bg-white/80 px-3 py-1 text-xs font-semibold text-slate-600")}>
                    {t("chatops.routeSnapshot.pendingCoreUpdates", { count: String(pendingCoreUpdateCount) })}
                  </span>
                </div>
                <div className="mt-3 space-y-2">
                  {routeState.recent_route_events.slice(0, 6).map((event, index) => (
                    <div key={`${String(event.event_type ?? "event")}-${index}`} className="rounded-[18px] border border-white/70 bg-white/80 p-3">
                      <p className="text-sm font-semibold text-slate-900">{String(event.event_type ?? t("chatops.routeSnapshot.routeEvent"))}</p>
                      <p className="mt-2 text-sm text-slate-500">{humanizeEnum(locale, "routeSemantic", event.route_semantic ?? event.trigger ?? "unknown")}</p>
                    </div>
                  ))}
                  {routeState.recent_route_events.length === 0 ? (
                    <EmptyState title={t("chatops.routeSnapshot.emptyTitle")} description={t("chatops.routeSnapshot.emptyDescription")} />
                  ) : null}
                </div>
              </div>
            </div>
          </GlassPanel>
        </div>
      )}
    </div>
  );
}
