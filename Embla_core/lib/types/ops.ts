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
