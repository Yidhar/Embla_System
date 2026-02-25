export type OpsSeverity = "ok" | "warning" | "critical" | "unknown";

export interface OpsEnvelope<TData> {
  status: "success" | "error";
  generated_at: string;
  data: TData;
  severity: OpsSeverity;
  source_reports: string[];
  source_endpoints: string[];
  reason_code?: string;
  reason_text?: string;
}

export interface RuntimePostureMetrics {
  runtime_rollout?: Record<string, unknown>;
  runtime_fail_open?: Record<string, unknown>;
  runtime_lease?: Record<string, unknown>;
  queue_depth?: Record<string, unknown>;
  lock_status?: Record<string, unknown>;
  disk_watermark_ratio?: Record<string, unknown>;
  error_rate?: Record<string, unknown>;
  latency_p95_ms?: Record<string, unknown>;
}

export interface RuntimePostureData {
  summary: Record<string, unknown>;
  metrics: RuntimePostureMetrics;
}

export interface McpFabricSummary {
  total_services: number;
  available_services: number;
  builtin_services: number;
  mcporter_services: number;
  isolated_worker_services: number;
  rejected_plugin_manifests: number;
}

export interface McpFabricData {
  summary: McpFabricSummary;
  runtime_snapshot: Record<string, unknown>;
  registry: Record<string, unknown>;
  tasks: Record<string, unknown>;
  services: Array<Record<string, unknown>>;
}

export interface MemoryGraphSummary {
  enabled: boolean;
  total_quintuples: number;
  active_tasks: number;
  pending_tasks: number;
  running_tasks: number;
  failed_tasks: number;
  graph_sample_size: number;
}

export interface MemoryHotspot {
  relation?: string;
  entity?: string;
  count: number;
}

export interface MemoryGraphRow {
  subject: string;
  subject_type: string;
  predicate: string;
  object: string;
  object_type: string;
}

export interface MemoryGraphData {
  summary: MemoryGraphSummary;
  task_manager: Record<string, unknown>;
  relation_hotspots: MemoryHotspot[];
  entity_hotspots: MemoryHotspot[];
  graph_sample: MemoryGraphRow[];
}

export interface WorkflowEventCounter {
  [eventType: string]: number;
}

export interface WorkflowRecentEvent {
  timestamp: string;
  event_type: string;
  payload_excerpt: Record<string, unknown>;
}

export interface WorkflowSummary {
  overall_status: string;
  events_scanned: number;
  outbox_pending: number | null;
  oldest_pending_age_seconds: number | null;
  critical_events_total: number;
}

export interface WorkflowEventsData {
  summary: WorkflowSummary;
  queue_depth: Record<string, unknown>;
  lock_status: Record<string, unknown>;
  runtime_lease: Record<string, unknown>;
  event_counters: WorkflowEventCounter;
  recent_critical_events: WorkflowRecentEvent[];
  log_context_statistics: Record<string, unknown>;
  tool_status: Record<string, unknown>;
}
