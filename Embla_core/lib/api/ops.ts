import "server-only";

import { buildLocalMcpFabricSnapshot } from "@/lib/server/local-snapshot";
import {
  AgentProfile,
  AgentProfileDetail,
  AgentProfilePromptPreview,
  AgentProfileRegistryData,
  ChatRouteSessionStateData,
  ChatSessionDetail,
  ChatSessionMessage,
  ChatSessionSummary,
  EvidenceData,
  HeartbeatSummary,
  IncidentsData,
  McpFabricData,
  McpService,
  McpTask,
  ToolInventory,
  MemoryGraphData,
  MemoryGraphEdge,
  MetricValue,
  OpsEnvelope,
  PromptTemplateMeta,
  RuntimePostureData,
  ShellToolCatalog,
  ShellToolDefinition,
  SkillInventory,
  SystemConfigData,
  SystemInfoData,
  TaskHeartbeatRecord,
  TaskHeartbeatSession,
  WorkflowEventData
} from "@/lib/types";
import {
  mockEvidence,
  mockIncidents,
  mockMcpFabric,
  mockMemoryGraph,
  mockRuntimePosture,
  mockWorkflowEvents
} from "@/lib/mock/ops";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? process.env.API_BASE_URL ?? "http://127.0.0.1:8000";
const REVALIDATE_SECONDS = 5;

function buildUrl(endpoint: string) {
  if (endpoint.startsWith("http://") || endpoint.startsWith("https://")) {
    return endpoint;
  }
  return `${API_BASE}${endpoint}`;
}

async function fetchJson<T>(endpoint: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 6000);

  try {
    const response = await fetch(buildUrl(endpoint), {
      ...init,
      signal: controller.signal,
      next: { revalidate: REVALIDATE_SECONDS },
      headers: {
        "Content-Type": "application/json",
        ...(init?.headers ?? {})
      }
    });

    if (!response.ok) {
      const message = await response.text();
      throw new Error(`${endpoint} -> ${response.status} ${message}`);
    }

    return (await response.json()) as T;
  } finally {
    clearTimeout(timeout);
  }
}

function envelopeWithMeta<T>(
  envelope: OpsEnvelope<T>,
  mode: OpsEnvelope<T>["meta"] extends infer M ? M : never,
  reasonText?: string
): OpsEnvelope<T> {
  return {
    ...envelope,
    reason_text: reasonText ?? envelope.reason_text,
    meta: mode
  };
}

function toSeverity(status?: string): MetricValue["status"] {
  if (status === "critical" || status === "warning" || status === "ok" || status === "unknown") {
    return status;
  }
  return "unknown";
}

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

function displayText(value: unknown, fallback = "") {
  if (value === null || value === undefined) {
    return fallback;
  }
  if (typeof value === "string") {
    return stringValue(value, fallback);
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  try {
    const text = JSON.stringify(value);
    return text ? text : fallback;
  } catch {
    return stringValue(value, fallback);
  }
}

function numberValue(value: unknown, fallback = 0) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : fallback;
}

function normalizeStringList(value: unknown): string[] {
  return listValue(value).map((item) => stringValue(item)).filter(Boolean);
}

function normalizeMcpService(service: unknown): McpService {
  const row = recordValue(service);
  const source = stringValue(row.source, "unknown").toLowerCase() || "unknown";
  const name = stringValue(row.name ?? row.service_name ?? row.id);
  const displayName = stringValue(row.display_name ?? row.displayName, name);
  const description = stringValue(row.description ?? row.summary);
  const available = Boolean(row.available);

  let statusLabel = stringValue(row.status_label).toLowerCase();
  if (!statusLabel) {
    if (source === "official") {
      statusLabel = available ? "online" : "configured";
    } else if (source === "builtin") {
      statusLabel = available ? "online" : "offline";
    } else if (source === "mcporter") {
      statusLabel = available ? "configured" : "missing_command";
    } else {
      statusLabel = available ? "available" : "unknown";
    }
  }

  let statusReason = stringValue(row.status_reason);
  if (!statusReason) {
    if (source === "official") {
      statusReason = available
        ? "Official MCP server is connected in current runtime."
        : "Official MCP server is configured but not currently connected.";
    } else if (source === "builtin") {
      statusReason = available
        ? "Builtin MCP module is importable in current runtime."
        : "Builtin MCP module is not importable in current runtime.";
    } else if (source === "mcporter") {
      statusReason = available
        ? "Mcporter command is available in current runtime."
        : "Mcporter command is missing in current runtime.";
    } else {
      statusReason = "Service metadata is incomplete.";
    }
  }

  return {
    name,
    display_name: displayName,
    description,
    source,
    available,
    status_label: statusLabel,
    status_reason: statusReason
  };
}

function normalizeMcpTask(task: unknown): McpTask | null {
  const row = recordValue(task);
  const serviceName = stringValue(row.service_name ?? row.name);
  if (!serviceName) {
    return null;
  }
  const source = stringValue(row.source, "unknown");
  return {
    task_id: stringValue(row.task_id, `${source}:${serviceName}`),
    service_name: serviceName,
    status: stringValue(row.status, "unknown"),
    source
  };
}

function normalizeSkillInventory(input: unknown): SkillInventory {
  const row = recordValue(input);
  const bundled = listValue(row.bundled_skills)
    .map((item) => {
      const next = recordValue(item);
      const name = stringValue(next.name);
      const path = stringValue(next.path);
      return name && path ? { name, path } : null;
    })
    .filter((item): item is { name: string; path: string } => Boolean(item));

  return {
    total_skills: numberValue(row.total_skills, bundled.length),
    bundled_skills: bundled
  };
}

function normalizeToolInventory(input: unknown): ToolInventory {
  const row = recordValue(input);
  return {
    total_tools: numberValue(row.total_tools),
    memory_tools: numberValue(row.memory_tools),
    native_tools: numberValue(row.native_tools),
    dynamic_tools: numberValue(row.dynamic_tools),
    tool_names: normalizeStringList(row.tool_names)
  };
}

function normalizeShellToolDefinition(input: unknown): ShellToolDefinition | null {
  const row = recordValue(input);
  const name = stringValue(row.name);
  if (!name) {
    return null;
  }
  return {
    name,
    description: stringValue(row.description),
    parameters: recordValue(row.parameters)
  };
}

function normalizeMcpFabricEnvelope(envelope: OpsEnvelope<McpFabricData>): OpsEnvelope<McpFabricData> {
  const data = recordValue(envelope.data);
  const services = listValue(data.services)
    .map((item) => normalizeMcpService(item))
    .filter((item) => item.name)
    .sort((left, right) => `${left.source}:${left.name}`.localeCompare(`${right.source}:${right.name}`));

  const rawTasks = recordValue(data.tasks);
  const tasks = listValue(rawTasks.tasks)
    .map((item) => normalizeMcpTask(item))
    .filter((item): item is McpTask => Boolean(item));
  const synthesizedTasks = tasks.length > 0
    ? tasks
    : services.map((service) => ({
        task_id: `${service.source}:${service.name}`,
        service_name: service.name,
        status: service.status_label ?? (service.available ? "online" : "unknown"),
        source: service.source
      }));

  const summary = recordValue(data.summary);
  const builtinServices = services.filter((item) => item.source === "builtin").length;
  const mcporterServices = services.filter((item) => item.source === "mcporter").length;
  const availableServices = services.filter((item) => item.available).length;

  return {
    ...envelope,
    source_reports: normalizeStringList(envelope.source_reports),
    source_endpoints: normalizeStringList(envelope.source_endpoints),
    data: {
      summary: {
        ...summary,
        total_services: numberValue(summary.total_services, services.length),
        available_services: numberValue(summary.available_services, availableServices),
        builtin_services: numberValue(summary.builtin_services, builtinServices),
        mcporter_services: numberValue(summary.mcporter_services, mcporterServices),
        isolated_worker_services: numberValue(summary.isolated_worker_services, 0),
        rejected_plugin_manifests: numberValue(summary.rejected_plugin_manifests, 0)
      },
      services,
      tasks: {
        total: numberValue(rawTasks.total, synthesizedTasks.length),
        tasks: synthesizedTasks
      },
      registry: recordValue(data.registry),
      runtime_snapshot: recordValue(data.runtime_snapshot),
      skill_inventory: normalizeSkillInventory(data.skill_inventory),
      tool_inventory: normalizeToolInventory(data.tool_inventory)
    }
  };
}

function normalizeMemoryEdge(row: unknown): MemoryGraphEdge | null {
  const item = recordValue(row);
  const subject = stringValue(item.subject ?? item.entity);
  const predicate = stringValue(item.predicate ?? item.relation);
  const object = stringValue(item.object ?? item.target);
  if (!subject && !predicate && !object) {
    return null;
  }
  return {
    subject,
    subject_type: stringValue(item.subject_type ?? item.entity_type),
    predicate,
    object,
    object_type: stringValue(item.object_type ?? item.target_type)
  };
}

function normalizeMemoryGraphEnvelope(envelope: OpsEnvelope<MemoryGraphData>): OpsEnvelope<MemoryGraphData> {
  const data = recordValue(envelope.data);
  const graphSample = listValue(data.graph_sample ?? data.graphSample)
    .map((item) => normalizeMemoryEdge(item))
    .filter((item): item is MemoryGraphEdge => Boolean(item));

  const relationHotspotsRaw = listValue(data.relation_hotspots).map((item) => {
    const row = recordValue(item);
    return { relation: stringValue(row.relation), count: numberValue(row.count) };
  }).filter((item) => item.relation);
  const entityHotspotsRaw = listValue(data.entity_hotspots).map((item) => {
    const row = recordValue(item);
    return { entity: stringValue(row.entity), count: numberValue(row.count) };
  }).filter((item) => item.entity);

  const relationCounter = new Map<string, number>();
  const entityCounter = new Map<string, number>();
  for (const edge of graphSample) {
    if (edge.subject) {
      entityCounter.set(edge.subject, (entityCounter.get(edge.subject) ?? 0) + 1);
    }
    if (edge.object) {
      entityCounter.set(edge.object, (entityCounter.get(edge.object) ?? 0) + 1);
    }
    if (edge.predicate) {
      relationCounter.set(edge.predicate, (relationCounter.get(edge.predicate) ?? 0) + 1);
    }
  }

  const relationHotspots = relationHotspotsRaw.length > 0
    ? relationHotspotsRaw
    : [...relationCounter.entries()]
        .sort((left, right) => right[1] - left[1])
        .slice(0, 12)
        .map(([relation, count]) => ({ relation, count }));
  const entityHotspots = entityHotspotsRaw.length > 0
    ? entityHotspotsRaw
    : [...entityCounter.entries()]
        .sort((left, right) => right[1] - left[1])
        .slice(0, 12)
        .map(([entity, count]) => ({ entity, count }));

  const summary = recordValue(data.summary);
  const taskManager = recordValue(data.task_manager ?? data.taskManager ?? data.tasks);
  const vectorIndex = recordValue(data.vector_index ?? data.vectorIndex);
  const pendingTasks = numberValue(taskManager.pending_tasks ?? summary.pending_tasks);
  const runningTasks = numberValue(taskManager.running_tasks ?? summary.running_tasks);
  const failedTasks = numberValue(taskManager.failed_tasks ?? summary.failed_tasks);
  const activeTasks = Math.max(numberValue(summary.active_tasks), pendingTasks + runningTasks);
  const totalQuintuples = numberValue(summary.total_quintuples, graphSample.length);
  const vectorIndexState = stringValue(summary.vector_index_state ?? vectorIndex.state ?? vectorIndex.status, "unknown");
  const vectorIndexReady = Boolean(summary.vector_index_ready ?? vectorIndex.ready);
  const enabled = summary.enabled !== undefined
    ? Boolean(summary.enabled)
    : Boolean(totalQuintuples > 0 || activeTasks > 0 || failedTasks > 0 || graphSample.length > 0 || Object.keys(vectorIndex).length > 0);

  return {
    ...envelope,
    source_reports: normalizeStringList(envelope.source_reports),
    source_endpoints: normalizeStringList(envelope.source_endpoints),
    data: {
      summary: {
        ...summary,
        enabled,
        total_quintuples: totalQuintuples,
        active_tasks: activeTasks,
        pending_tasks: pendingTasks,
        running_tasks: runningTasks,
        failed_tasks: failedTasks,
        graph_sample_size: numberValue(summary.graph_sample_size, graphSample.length),
        vector_index_state: vectorIndexState,
        vector_index_ready: vectorIndexReady
      },
      task_manager: {
        ...taskManager,
        pending_tasks: pendingTasks,
        running_tasks: runningTasks,
        failed_tasks: failedTasks
      },
      vector_index: {
        ...vectorIndex,
        state: vectorIndexState,
        ready: vectorIndexReady
      },
      relation_hotspots: relationHotspots,
      entity_hotspots: entityHotspots,
      graph_sample: graphSample
    }
  };
}

function normalizeHeartbeatSummary(input: unknown): HeartbeatSummary {
  const row = recordValue(input);
  return {
    root_session_id: stringValue(row.root_session_id),
    session_count: numberValue(row.session_count),
    sessions_with_heartbeats: numberValue(row.sessions_with_heartbeats),
    task_count: numberValue(row.task_count),
    fresh_count: numberValue(row.fresh_count),
    warning_count: numberValue(row.warning_count),
    critical_count: numberValue(row.critical_count),
    blocked_count: numberValue(row.blocked_count),
    max_stale_level: stringValue(row.max_stale_level, "fresh"),
    latest_generated_at: stringValue(row.latest_generated_at),
    latest_expires_at: stringValue(row.latest_expires_at),
    has_stale: Boolean(row.has_stale),
    has_blocked: Boolean(row.has_blocked)
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
    heartbeat_summary: normalizeHeartbeatSummary(row.heartbeat_summary)
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
    stale_level: stringValue(row.stale_level, "fresh"),
    escalation_state: stringValue(row.escalation_state),
    seconds_since_heartbeat: row.seconds_since_heartbeat === null || row.seconds_since_heartbeat === undefined
      ? null
      : numberValue(row.seconds_since_heartbeat),
    details: recordValue(row.details)
  };
}

function normalizeIncidentsEnvelope(envelope: OpsEnvelope<IncidentsData>): OpsEnvelope<IncidentsData> {
  const data = recordValue(envelope.data);
  const eventCounters = Object.fromEntries(
    Object.entries(recordValue(data.event_counters)).map(([key, value]) => [key, numberValue(value)])
  );
  const incidents = listValue(data.incidents).map((item) => {
    const row = recordValue(item);
    const severity = (toSeverity(stringValue(row.severity)) ?? "unknown") as IncidentsData["incidents"][number]["severity"];
    return {
      timestamp: stringValue(row.timestamp),
      event_type: stringValue(row.event_type),
      severity,
      source: stringValue(row.source),
      summary: stringValue(row.summary || row.event_type, "事件详情"),
      payload_excerpt: displayText(row.payload_excerpt),
      report_path: stringValue(row.report_path),
      gate_level: stringValue(row.gate_level)
    };
  }).filter((item) => item.summary);

  return {
    ...envelope,
    source_reports: normalizeStringList(envelope.source_reports),
    source_endpoints: normalizeStringList(envelope.source_endpoints),
    data: {
      summary: recordValue(data.summary),
      events_scanned: numberValue(data.events_scanned),
      event_counters: eventCounters,
      incidents
    }
  };
}

function normalizeWorkflowEventsEnvelope(envelope: OpsEnvelope<WorkflowEventData>): OpsEnvelope<WorkflowEventData> {
  const data = recordValue(envelope.data);
  const recentCriticalEvents = listValue(data.recent_critical_events).map((item) => {
    const row = recordValue(item);
    return {
      timestamp: stringValue(row.timestamp),
      event_type: stringValue(row.event_type),
      payload_excerpt: displayText(row.payload_excerpt)
    };
  }).filter((item) => item.event_type);

  const heartbeatSupervision = recordValue(data.heartbeat_supervision);
  const heartbeatSessions = listValue(heartbeatSupervision.sessions)
    .map((item) => normalizeTaskHeartbeatSession(item))
    .filter((item): item is TaskHeartbeatSession => Boolean(item));
  const heartbeats = listValue(heartbeatSupervision.heartbeats)
    .map((item) => normalizeTaskHeartbeatRecord(item))
    .filter((item): item is TaskHeartbeatRecord => Boolean(item));

  const eventCounters = Object.fromEntries(
    Object.entries(recordValue(data.event_counters)).map(([key, value]) => [key, numberValue(value)])
  );

  return {
    ...envelope,
    source_reports: normalizeStringList(envelope.source_reports),
    source_endpoints: normalizeStringList(envelope.source_endpoints),
    data: {
      summary: recordValue(data.summary),
      queue_depth: recordValue(data.queue_depth),
      lock_status: recordValue(data.lock_status),
      runtime_lease: recordValue(data.runtime_lease),
      event_counters: eventCounters,
      recent_critical_events: recentCriticalEvents,
      heartbeat_supervision: {
        summary: normalizeHeartbeatSummary(heartbeatSupervision.summary),
        sessions: heartbeatSessions,
        heartbeats
      },
      log_context_statistics: recordValue(data.log_context_statistics),
      tool_status: {
        message: stringValue(recordValue(data.tool_status).message),
        visible: Boolean(recordValue(data.tool_status).visible)
      }
    }
  };
}

function buildMemoryEnvelopeFromRaw(
  statsResponse: { status?: string; memory_stats?: Record<string, unknown> },
  quintuplesResponse: { status?: string; quintuples?: Array<Record<string, unknown>>; count?: number }
): OpsEnvelope<MemoryGraphData> {
  const memoryStats = recordValue(statsResponse.memory_stats);
  const taskManager = recordValue(memoryStats.task_manager ?? memoryStats.taskManager ?? memoryStats.tasks);
  const vectorIndex = recordValue(memoryStats.vector_index ?? memoryStats.vectorIndex);
  const rawQuintuples = listValue<Record<string, unknown>>(quintuplesResponse.quintuples);
  const quintuples = rawQuintuples
    .map((row) => normalizeMemoryEdge(row))
    .filter((row): row is MemoryGraphEdge => Boolean(row));
  const entityCounter = new Map<string, number>();
  const relationCounter = new Map<string, number>();

  for (const row of quintuples.slice(0, 240)) {
    if (row.subject) {
      entityCounter.set(row.subject, (entityCounter.get(row.subject) ?? 0) + 1);
    }
    if (row.object) {
      entityCounter.set(row.object, (entityCounter.get(row.object) ?? 0) + 1);
    }
    if (row.predicate) {
      relationCounter.set(row.predicate, (relationCounter.get(row.predicate) ?? 0) + 1);
    }
  }

  const pendingTasks = numberValue(taskManager.pending_tasks ?? memoryStats.pending_tasks);
  const runningTasks = numberValue(taskManager.running_tasks ?? memoryStats.running_tasks);
  const failedTasks = numberValue(taskManager.failed_tasks ?? memoryStats.failed_tasks);
  const activeTasks = Math.max(numberValue(memoryStats.active_tasks), pendingTasks + runningTasks);
  const totalQuintuples = numberValue(memoryStats.total_quintuples, numberValue(quintuplesResponse.count, quintuples.length));
  const vectorIndexState = stringValue(vectorIndex.state ?? vectorIndex.status, "unknown");
  const vectorIndexReady = Boolean(vectorIndex.ready);
  const enabled = memoryStats.enabled !== undefined
    ? Boolean(memoryStats.enabled)
    : Boolean(totalQuintuples > 0 || activeTasks > 0 || failedTasks > 0 || quintuples.length > 0 || Object.keys(taskManager).length > 0 || Object.keys(vectorIndex).length > 0);
  const severity = !enabled
    ? "unknown"
    : failedTasks > 0
      ? "warning"
      : totalQuintuples > 0
        ? "ok"
        : "unknown";

  return normalizeMemoryGraphEnvelope({
    status: statsResponse.status ?? "success",
    generated_at: new Date().toISOString(),
    severity,
    source_reports: [],
    source_endpoints: ["/memory/stats", "/memory/quintuples"],
    reason_code: "RAW_MEMORY_FALLBACK",
    reason_text: "聚合接口不可用，当前回退到原始 Memory 接口。",
    meta: {
      mode: "degraded",
      note: "raw memory endpoints"
    },
    data: {
      summary: {
        enabled,
        total_quintuples: totalQuintuples,
        active_tasks: activeTasks,
        pending_tasks: pendingTasks,
        running_tasks: runningTasks,
        failed_tasks: failedTasks,
        graph_sample_size: Math.min(quintuples.length, 80),
        vector_index_state: vectorIndexState,
        vector_index_ready: vectorIndexReady
      },
      task_manager: taskManager,
      vector_index: vectorIndex,
      relation_hotspots: [...relationCounter.entries()]
        .sort((a, b) => b[1] - a[1])
        .slice(0, 12)
        .map(([relation, count]) => ({ relation, count })),
      entity_hotspots: [...entityCounter.entries()]
        .sort((a, b) => b[1] - a[1])
        .slice(0, 12)
        .map(([entity, count]) => ({ entity, count })),
      graph_sample: quintuples.slice(0, 40)
    }
  });
}

export async function getRuntimePosture() {
  try {
    const data = await fetchJson<OpsEnvelope<RuntimePostureData>>("/v1/ops/runtime/posture");
    return envelopeWithMeta(data, { mode: "live" });
  } catch {
    return envelopeWithMeta(mockRuntimePosture, { mode: "mock", note: "runtime mock fallback" });
  }
}

export async function getWorkflowEvents() {
  try {
    const data = await fetchJson<OpsEnvelope<WorkflowEventData>>("/v1/ops/workflow/events");
    return normalizeWorkflowEventsEnvelope(envelopeWithMeta(data, { mode: "live" }));
  } catch {
    return normalizeWorkflowEventsEnvelope(envelopeWithMeta(mockWorkflowEvents, { mode: "mock", note: "workflow mock fallback" }));
  }
}

export async function getIncidents() {
  try {
    const data = await fetchJson<OpsEnvelope<IncidentsData>>("/v1/ops/incidents/latest");
    return normalizeIncidentsEnvelope(envelopeWithMeta(data, { mode: "live" }));
  } catch {
    return normalizeIncidentsEnvelope(envelopeWithMeta(mockIncidents, { mode: "mock", note: "incident mock fallback" }));
  }
}

export async function getEvidence() {
  try {
    const data = await fetchJson<OpsEnvelope<EvidenceData>>("/v1/ops/evidence/index");
    return envelopeWithMeta(data, { mode: "live" });
  } catch {
    return envelopeWithMeta(mockEvidence, { mode: "mock", note: "evidence mock fallback" });
  }
}

export async function getMemoryGraph() {
  try {
    const data = await fetchJson<OpsEnvelope<MemoryGraphData>>("/v1/ops/memory/graph");
    return normalizeMemoryGraphEnvelope(envelopeWithMeta(data, { mode: "live" }));
  } catch {
    try {
      const [stats, quintuples] = await Promise.all([
        fetchJson<{ status?: string; memory_stats?: Record<string, unknown> }>("/memory/stats"),
        fetchJson<{ status?: string; quintuples?: Array<Record<string, unknown>>; count?: number }>("/memory/quintuples")
      ]);
      return normalizeMemoryGraphEnvelope(buildMemoryEnvelopeFromRaw(stats, quintuples));
    } catch {
      return normalizeMemoryGraphEnvelope(envelopeWithMeta(mockMemoryGraph, { mode: "mock", note: "memory mock fallback" }));
    }
  }
}

export async function getMcpFabric() {
  try {
    const data = await fetchJson<OpsEnvelope<McpFabricData>>("/v1/ops/mcp/fabric");
    return normalizeMcpFabricEnvelope(envelopeWithMeta(data, { mode: "live" }));
  } catch {
    try {
      return normalizeMcpFabricEnvelope(await buildLocalMcpFabricSnapshot());
    } catch {
      return normalizeMcpFabricEnvelope(envelopeWithMeta(mockMcpFabric, { mode: "mock", note: "mcp mock fallback" }));
    }
  }
}


function normalizePromptTemplateMeta(input: unknown): PromptTemplateMeta | null {
  const row = recordValue(input);
  const name = stringValue(row.name ?? row.filename);
  if (!name) {
    return null;
  }
  return {
    name,
    filename: stringValue(row.filename),
    relative_path: stringValue(row.relative_path),
    source: stringValue(row.source),
    size_bytes: numberValue(row.size_bytes),
    updated_at: stringValue(row.updated_at)
  };
}

function normalizeAgentProfile(input: unknown): AgentProfile | null {
  const row = recordValue(input);
  const agentType = stringValue(row.agent_type ?? row.name);
  if (!agentType) {
    return null;
  }
  return {
    agent_type: agentType,
    role: stringValue(row.role, "dev"),
    label: stringValue(row.label, agentType),
    description: stringValue(row.description),
    prompt_blocks: normalizeStringList(row.prompt_blocks),
    tool_profile: stringValue(row.tool_profile),
    tool_subset: normalizeStringList(row.tool_subset),
    enabled: row.enabled === undefined ? true : Boolean(row.enabled),
    default_for_role: Boolean(row.default_for_role),
    builtin: Boolean(row.builtin),
    prompts_root: stringValue(row.prompts_root, "system/prompts"),
    created_at: stringValue(row.created_at),
    updated_at: stringValue(row.updated_at)
  };
}

function normalizeAgentProfilePromptPreview(input: unknown): AgentProfilePromptPreview | null {
  const row = recordValue(input);
  const relativePath = stringValue(row.relative_path);
  if (!relativePath) {
    return null;
  }
  return {
    relative_path: relativePath,
    exists: Boolean(row.exists),
    size_bytes: numberValue(row.size_bytes),
    updated_at: stringValue(row.updated_at),
    content_preview: stringValue(row.content_preview)
  };
}

function normalizeAgentProfileRegistry(input: unknown): AgentProfileRegistryData {
  const row = recordValue(input);
  return {
    status: stringValue(row.status, "success"),
    schema_version: stringValue(row.schema_version),
    registry_path: stringValue(row.registry_path),
    exists_on_disk: Boolean(row.exists_on_disk),
    allowed_roles: normalizeStringList(row.allowed_roles),
    summary: recordValue(row.summary),
    profiles: listValue(row.profiles)
      .map((item) => normalizeAgentProfile(item))
      .filter((item): item is AgentProfile => Boolean(item)),
    tool_profile_presets: recordValue(row.tool_profile_presets) as Record<string, string[]>,
    prompt_templates: listValue(row.prompt_templates)
      .map((item) => normalizePromptTemplateMeta(item))
      .filter((item): item is PromptTemplateMeta => Boolean(item))
  };
}

function normalizeAgentProfileDetail(input: unknown): AgentProfileDetail | null {
  const row = recordValue(input);
  const profile = normalizeAgentProfile(row.profile);
  if (!profile) {
    return null;
  }
  return {
    status: stringValue(row.status, "success"),
    profile,
    prompt_block_previews: listValue(row.prompt_block_previews)
      .map((item) => normalizeAgentProfilePromptPreview(item))
      .filter((item): item is AgentProfilePromptPreview => Boolean(item))
  };
}

function normalizeChatSessionSummary(input: unknown): ChatSessionSummary | null {
  const row = recordValue(input);
  const sessionId = stringValue(row.session_id);
  if (!sessionId) {
    return null;
  }
  return {
    session_id: sessionId,
    created_at: stringValue(row.created_at),
    last_active_at: stringValue(row.last_active_at),
    message_count: numberValue(row.message_count),
    conversation_rounds: numberValue(row.conversation_rounds),
    agent_type: stringValue(row.agent_type),
    max_history_rounds: numberValue(row.max_history_rounds),
    temporary: Boolean(row.temporary),
    last_message: stringValue(row.last_message)
  };
}

function normalizeChatSessionMessage(input: unknown): ChatSessionMessage | null {
  const row = recordValue(input);
  const role = stringValue(row.role);
  const content = displayText(row.content);
  if (!role && !content) {
    return null;
  }
  return { role: role || "assistant", content };
}

export async function getChatSessions(): Promise<ChatSessionSummary[]> {
  try {
    const data = await fetchJson<{ status?: string; sessions?: unknown[] }>("/sessions");
    return listValue(data.sessions)
      .map((item) => normalizeChatSessionSummary(item))
      .filter((item): item is ChatSessionSummary => Boolean(item))
      .sort((left, right) => {
        const leftTime = Date.parse(left.last_active_at || left.created_at || "") || 0;
        const rightTime = Date.parse(right.last_active_at || right.created_at || "") || 0;
        return rightTime - leftTime;
      });
  } catch {
    return [];
  }
}

export async function getChatSessionDetail(sessionId: string): Promise<ChatSessionDetail | null> {
  const normalized = stringValue(sessionId);
  if (!normalized) {
    return null;
  }

  try {
    const data = await fetchJson<ChatSessionDetail>(`/sessions/${encodeURIComponent(normalized)}`);
    return {
      ...data,
      session_id: stringValue(data.session_id, normalized),
      session_info: normalizeChatSessionSummary(data.session_info) ?? { session_id: normalized },
      conversation_rounds: numberValue(data.conversation_rounds),
      messages: listValue(data.messages)
        .map((item) => normalizeChatSessionMessage(item))
        .filter((item): item is ChatSessionMessage => Boolean(item))
    };
  } catch {
    return null;
  }
}

export async function getChatRouteSessionState(sessionId: string): Promise<ChatRouteSessionStateData | null> {
  const normalized = stringValue(sessionId);
  if (!normalized) {
    return null;
  }

  try {
    const data = await fetchJson<ChatRouteSessionStateData>(`/v1/chat/route_session_state/${encodeURIComponent(normalized)}`);
    return {
      ...data,
      child_heartbeat_summary: normalizeHeartbeatSummary(data.child_heartbeat_summary),
      child_heartbeat_sessions: listValue(data.child_heartbeat_sessions)
        .map((item) => normalizeTaskHeartbeatSession(item))
        .filter((item): item is TaskHeartbeatSession => Boolean(item)),
      child_heartbeats: listValue(data.child_heartbeats)
        .map((item) => normalizeTaskHeartbeatRecord(item))
        .filter((item): item is TaskHeartbeatRecord => Boolean(item)),
      state: recordValue(data.state),
      recent_route_events: listValue(data.recent_route_events).map((item) => recordValue(item))
    };
  } catch {
    return null;
  }
}

export async function getShellToolCatalog(): Promise<ShellToolCatalog> {
  try {
    const data = await fetchJson<ShellToolCatalog>("/v1/shell/tools");
    return {
      status: stringValue(data.status, "success"),
      agent: stringValue(data.agent, "shell"),
      scope: stringValue(data.scope, "entry"),
      session_id: stringValue(data.session_id),
      count: numberValue(data.count),
      tool_names: normalizeStringList(data.tool_names),
      tools: listValue(data.tools)
        .map((item) => normalizeShellToolDefinition(item))
        .filter((item): item is ShellToolDefinition => Boolean(item))
    };
  } catch {
    return {
      status: "error",
      agent: "shell",
      scope: "entry",
      session_id: "",
      count: 0,
      tool_names: [],
      tools: []
    };
  }
}

export function getMetric<T extends RuntimePostureData | WorkflowEventData>(
  collection: Record<string, unknown> | undefined,
  key: string
): MetricValue {
  const value = collection?.[key];
  if (!value || typeof value !== "object") {
    return { status: "unknown" };
  }
  return {
    ...(value as MetricValue),
    status: toSeverity((value as MetricValue).status)
  };
}

export async function postMcpImport(body: { name: string; config: Record<string, unknown> }) {
  return fetchJson<{ status: string; message: string }>("/mcp/import", {
    method: "POST",
    body: JSON.stringify(body)
  });
}

export async function getSystemInfo(): Promise<SystemInfoData> {
  try {
    return await fetchJson<SystemInfoData>("/v1/system/info");
  } catch {
    return { status: "unknown", version: "", available_services: [], api_key_configured: false };
  }
}

export async function getSystemConfig(): Promise<SystemConfigData> {
  try {
    return await fetchJson<SystemConfigData>("/system/config");
  } catch {
    return { status: "error", config: {} };
  }
}

export async function getPromptTemplates(): Promise<PromptTemplateMeta[]> {
  try {
    const data = await fetchJson<{ status?: string; prompts?: unknown[] }>("/v1/system/prompts");
    return listValue(data.prompts)
      .map((item) => normalizePromptTemplateMeta(item))
      .filter((item): item is PromptTemplateMeta => Boolean(item));
  } catch {
    return [];
  }
}

export async function getAgentProfiles(): Promise<AgentProfileRegistryData> {
  try {
    const data = await fetchJson<AgentProfileRegistryData>("/v1/system/agent-profiles");
    return normalizeAgentProfileRegistry(data);
  } catch {
    return {
      status: "error",
      schema_version: "",
      registry_path: "",
      exists_on_disk: false,
      allowed_roles: ["expert", "dev", "review"],
      summary: {},
      profiles: [],
      tool_profile_presets: {},
      prompt_templates: []
    };
  }
}

export async function getAgentProfileDetail(agentType: string): Promise<AgentProfileDetail | null> {
  const normalized = stringValue(agentType);
  if (!normalized) {
    return null;
  }
  try {
    const data = await fetchJson<AgentProfileDetail>(`/v1/system/agent-profiles/${encodeURIComponent(normalized)}`);
    return normalizeAgentProfileDetail(data);
  } catch {
    return null;
  }
}

export async function postSkillImport(body: { name: string; content: string }) {
  return fetchJson<{ status: string; message: string }>("/skills/import", {
    method: "POST",
    body: JSON.stringify(body)
  });
}
