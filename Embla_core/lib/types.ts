export type Severity = "ok" | "warning" | "critical" | "unknown";
export type DataMode = "live" | "degraded" | "local-fallback" | "mock";

export interface OpsEnvelope<T> {
  status: string;
  generated_at: string;
  severity: Severity;
  data: T;
  source_reports: string[];
  source_endpoints: string[];
  reason_code?: string | null;
  reason_text?: string | null;
  meta?: {
    mode: DataMode;
    note?: string;
  };
}

export interface MetricValue {
  value?: number | null;
  unit?: string;
  status?: Severity;
  thresholds?: Record<string, number>;
  [key: string]: unknown;
}

export interface RuntimePostureData {
  summary: Record<string, unknown>;
  metrics: Record<string, MetricValue>;
  control_plane_mode?: Record<string, unknown>;
  brainstem_control_plane?: Record<string, unknown>;
  watchdog_daemon?: Record<string, unknown>;
  process_guard?: Record<string, unknown>;
  killswitch_guard?: Record<string, unknown>;
  budget_guard?: Record<string, unknown>;
  immutable_dna?: Record<string, unknown>;
  audit_ledger?: Record<string, unknown>;
  core_child_spawn_deferred?: Record<string, unknown>;
  agentic_loop_completion?: Record<string, unknown>;
  execution_bridge_governance?: Record<string, unknown>;
  vision_multimodal?: Record<string, unknown>;
  threshold_profile?: Record<string, unknown>;
  sources?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface McpService {
  name: string;
  display_name?: string;
  description?: string;
  source: string;
  available?: boolean;
  status_label?: string;
  status_reason?: string;
}

export interface McpTask {
  task_id: string;
  service_name: string;
  status: string;
  source: string;
}

export interface SkillInventory {
  total_skills: number;
  bundled_skills: Array<{ name: string; path: string }>;
}

export interface ToolInventory {
  total_tools: number;
  memory_tools?: number;
  native_tools?: number;
  dynamic_tools?: number;
  tool_names?: string[];
}

export interface McpFabricData {
  summary: Record<string, unknown>;
  services: McpService[];
  tasks: {
    tasks: McpTask[];
    total?: number;
  };
  registry?: Record<string, unknown>;
  runtime_snapshot?: Record<string, unknown>;
  skill_inventory?: SkillInventory;
  tool_inventory?: ToolInventory;
}

export interface MemoryGraphEdge {
  subject: string;
  subject_type?: string;
  predicate: string;
  object: string;
  object_type?: string;
}

export interface MemoryGraphData {
  summary: Record<string, unknown>;
  task_manager?: Record<string, unknown>;
  vector_index?: Record<string, unknown>;
  relation_hotspots: Array<{ relation: string; count: number }>;
  entity_hotspots: Array<{ entity: string; count: number }>;
  graph_sample: MemoryGraphEdge[];
}

export interface HeartbeatSummary {
  root_session_id?: string;
  session_count?: number;
  sessions_with_heartbeats?: number;
  task_count?: number;
  fresh_count?: number;
  warning_count?: number;
  critical_count?: number;
  blocked_count?: number;
  max_stale_level?: string;
  latest_generated_at?: string;
  latest_expires_at?: string;
  has_stale?: boolean;
  has_blocked?: boolean;
  [key: string]: unknown;
}

export interface TaskHeartbeatSession {
  session_id: string;
  parent_id?: string;
  role?: string;
  status?: string;
  heartbeat_summary?: HeartbeatSummary;
}

export interface TaskHeartbeatRecord {
  session_id: string;
  task_id: string;
  parent_id?: string;
  role?: string;
  scope?: string;
  status?: string;
  message?: string;
  progress?: number | null;
  stage?: string;
  ttl_seconds?: number;
  sequence?: number;
  generated_at?: string;
  expires_at?: string;
  stale_level?: string;
  escalation_state?: string;
  seconds_since_heartbeat?: number | null;
  details?: Record<string, unknown>;
}

export interface WorkflowEventData {
  summary: Record<string, unknown>;
  queue_depth?: MetricValue;
  lock_status?: MetricValue;
  runtime_lease?: MetricValue;
  event_counters?: Record<string, number>;
  recent_critical_events: Array<{
    timestamp: string;
    event_type: string;
    payload_excerpt?: string;
  }>;
  heartbeat_supervision?: {
    summary?: HeartbeatSummary;
    sessions?: TaskHeartbeatSession[];
    heartbeats?: TaskHeartbeatRecord[];
  };
  log_context_statistics?: Record<string, unknown>;
  tool_status?: {
    message?: string;
    visible?: boolean;
  };
}

export interface ChatRouteSessionStateData {
  status: string;
  shell_session_id: string;
  run_context_id: string;
  core_execution_session_id?: string;
  last_run_context_id?: string;
  last_core_execution_session_id?: string;
  shell_session_exists: boolean;
  run_context_exists?: boolean;
  core_execution_session_exists?: boolean;
  core_runtime_id?: string;
  active_core_job_id?: string;
  active_core_job_ids?: string[];
  current_core_job_id?: string;
  queued_core_job_ids?: string[];
  core_worker_status?: string;
  core_queue_depth?: number;
  core_pipeline_depth?: number;
  core_mailbox_cursor_seq?: number;
  last_core_handoff_message_seq?: number;
  last_core_completion_message_seq?: number;
  core_recovery_restart_total?: number;
  core_job_watch_dedup_skipped_count?: number;
  core_last_dedup_message_seq?: number;
  latest_core_job_id?: string;
  active_core_job?: Record<string, unknown>;
  latest_core_job?: Record<string, unknown>;
  recent_core_jobs?: Array<Record<string, unknown>>;
  recent_core_updates?: ChatCoreAsyncUpdate[];
  unread_core_updates?: ChatCoreAsyncUpdate[];
  pending_core_update_count?: number;
  recent_core_reports?: Array<Record<string, unknown>>;
  core_job_heartbeat_summary?: HeartbeatSummary;
  core_job_heartbeats?: TaskHeartbeatRecord[];
  child_heartbeat_summary: HeartbeatSummary;
  child_heartbeat_sessions: TaskHeartbeatSession[];
  child_heartbeats: TaskHeartbeatRecord[];
  state: Record<string, unknown>;
  recent_route_events: Array<Record<string, unknown>>;
}

export interface ChatCoreAsyncUpdate {
  seq: number;
  from_id?: string;
  to_id?: string;
  message_type?: string;
  kind?: string;
  status?: string;
  core_job_id?: string;
  run_context_id?: string;
  core_runtime_id?: string;
  core_execution_session_id?: string;
  pipeline_id?: string;
  pending_descendant_count?: number;
  content?: string;
  created_at?: string;
  metadata?: Record<string, unknown>;
  is_terminal?: boolean;
}

export interface ChatCoreJobWatchData {
  status: string;
  shell_session_id: string;
  run_context_id: string;
  core_execution_session_id?: string;
  run_context_exists?: boolean;
  pending_core_update_count: number;
  core_outbox_cursor_seq: number;
  last_core_outbox_seq: number;
  unread_core_updates: ChatCoreAsyncUpdate[];
  recent_core_updates: ChatCoreAsyncUpdate[];
  active_core_job: Record<string, unknown>;
  latest_core_job: Record<string, unknown>;
  core_worker_status: string;
}

export type ChatCoreInboxData = ChatCoreJobWatchData;

export interface ShellToolDefinition {
  name: string;
  description?: string;
  parameters?: Record<string, unknown>;
}

export interface ShellToolCatalog {
  status: string;
  agent: string;
  scope?: string;
  session_id?: string;
  count: number;
  tool_names: string[];
  tools: ShellToolDefinition[];
}


export interface PromptTemplateMeta {
  name: string;
  filename?: string;
  relative_path?: string;
  source?: string;
  size_bytes?: number;
  updated_at?: string;
}

export interface AgentProfile {
  agent_type: string;
  role: string;
  label?: string;
  description?: string;
  prompt_blocks: string[];
  tool_profile?: string;
  tool_subset?: string[];
  enabled?: boolean;
  default_for_role?: boolean;
  builtin?: boolean;
  prompts_root?: string;
  created_at?: string;
  updated_at?: string;
}

export interface AgentProfilePromptPreview {
  relative_path: string;
  exists: boolean;
  size_bytes?: number;
  updated_at?: string;
  content_preview?: string;
}

export interface AgentProfileRegistryData {
  status: string;
  schema_version?: string;
  registry_path?: string;
  exists_on_disk?: boolean;
  allowed_roles: string[];
  summary: Record<string, unknown>;
  profiles: AgentProfile[];
  tool_profile_presets?: Record<string, string[]>;
  prompt_templates?: PromptTemplateMeta[];
}

export interface AgentProfileDetail {
  status: string;
  profile: AgentProfile;
  prompt_block_previews: AgentProfilePromptPreview[];
}

export interface SystemInfoData {
  version?: string;
  status?: string;
  available_services?: unknown[];
  api_key_configured?: boolean;
}

export interface SystemConfigData {
  status: string;
  config: Record<string, unknown>;
}


export interface ChatSessionSummary {
  session_id: string;
  created_at?: string;
  last_active_at?: string;
  message_count?: number;
  conversation_rounds?: number;
  agent_type?: string;
  max_history_rounds?: number;
  temporary?: boolean;
  last_message?: string;
}

export interface ChatSessionMessage {
  role: string;
  content: string;
}

export interface ChatSessionDetail {
  status: string;
  session_id: string;
  session_info: ChatSessionSummary;
  messages: ChatSessionMessage[];
  conversation_rounds: number;
}

export interface IncidentsData {
  summary: Record<string, unknown>;
  events_scanned?: number;
  event_counters?: Record<string, number>;
  incidents: Array<{
    timestamp: string;
    event_type: string;
    severity: Severity;
    source: string;
    summary: string;
    payload_excerpt?: string;
    report_path?: string;
    gate_level?: string;
  }>;
}

export interface EvidenceData {
  summary: Record<string, unknown>;
  required_reports: Array<{
    id: string;
    label: string;
    path: string;
    status: string;
    gate_level: string;
    passed?: boolean;
    exists?: boolean;
    generated_at?: string;
    modified_at?: string;
    failed_checks?: string[];
    scenario?: string;
  }>;
  recent_reports?: Array<Record<string, unknown>>;
}

export interface ChronosJob {
  id: string;
  name?: string;
  next_run?: string;
  interval_seconds?: number;
  status?: string;
  last_run?: string;
}

export interface ChronosJobsData {
  scheduler_running: boolean;
  job_count: number;
  jobs: ChronosJob[];
}

export interface DnaPromptEntry {
  path: string;
  immutable: boolean;
  size_bytes?: number;
  sha256?: string;
}

export interface DnaIntegrityData {
  verification_status: string;
  file_count: number;
  manifest_hash: string;
  prompts: DnaPromptEntry[];
}

export interface MemoryLayerStats {
  scope: string;
  total?: number;
  indexed?: number;
  details?: Record<string, unknown>;
}

export interface MemoryOverviewData {
  l1: MemoryLayerStats;
  l2: MemoryLayerStats;
  l3: MemoryLayerStats;
  /** @deprecated Merged into l2.total — kept for backward compat */
  grag_quintuples?: number;
}
