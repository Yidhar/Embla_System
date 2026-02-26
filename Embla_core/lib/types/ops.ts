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
  prompt_slice_count_by_layer?: Record<string, unknown>;
  outer_readonly_hit_rate?: Record<string, unknown>;
  readonly_write_tool_exposure_rate?: Record<string, unknown>;
  chat_route_path_distribution?: Record<string, unknown>;
  path_b_budget_escalation_rate?: Record<string, unknown>;
  core_session_creation_rate?: Record<string, unknown>;
}

export interface RuntimePostureData {
  summary: Record<string, unknown>;
  metrics: RuntimePostureMetrics;
  threshold_profile?: Record<string, unknown>;
  sources?: Record<string, unknown>;
  ws26_runtime_snapshot_report?: Record<string, unknown>;
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

export interface OpsIncidentSummary {
  total_incidents: number;
  critical_incidents: number;
  warning_incidents: number;
  latest_incident_at: string;
  runtime_prompt_safety?: {
    outer_readonly_hit_rate?: Record<string, unknown>;
    readonly_write_tool_exposure_rate?: Record<string, unknown>;
    chat_route_path_distribution?: Record<string, unknown>;
    path_b_budget_escalation_rate?: Record<string, unknown>;
    core_session_creation_rate?: Record<string, unknown>;
    route_quality?: Record<string, unknown>;
  };
}

export interface OpsIncidentItem {
  source: string;
  severity: OpsSeverity;
  timestamp: string;
  event_type: string;
  summary: string;
  payload_excerpt: Record<string, unknown>;
  report_path: string;
  gate_level: string;
}

export interface IncidentsLatestData {
  summary: OpsIncidentSummary;
  event_counters: Record<string, number>;
  events_scanned: number;
  incidents: OpsIncidentItem[];
}

export interface EvidenceSummary {
  required_total: number;
  required_present: number;
  required_passed: number;
  required_missing: number;
  required_failed: number;
  hard_missing: number;
  hard_failed: number;
  soft_missing: number;
  soft_failed: number;
}

export interface EvidenceRequiredReport {
  id: string;
  label: string;
  gate_level: string;
  path: string;
  exists: boolean;
  status: "passed" | "failed" | "missing" | "unknown";
  passed: boolean | null;
  generated_at: string;
  modified_at: string;
  scenario: string;
  failed_checks: string[];
}

export interface EvidenceRecentReport {
  name: string;
  path: string;
  size_bytes: number;
  modified_at: string;
}

export interface EvidenceIndexData {
  summary: EvidenceSummary;
  required_reports: EvidenceRequiredReport[];
  recent_reports: EvidenceRecentReport[];
}
