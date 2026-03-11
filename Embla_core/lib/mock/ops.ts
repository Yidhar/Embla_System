import {
  EvidenceData,
  IncidentsData,
  McpFabricData,
  MemoryGraphData,
  OpsEnvelope,
  RuntimePostureData,
  WorkflowEventData
} from "@/lib/types";

const now = new Date().toISOString();

export const mockRuntimePosture: OpsEnvelope<RuntimePostureData> = {
  status: "success",
  generated_at: now,
  severity: "warning",
  reason_code: "MOCK_RUNTIME_SNAPSHOT",
  reason_text: "当前使用前端内置示例数据，用于页面施工与联调预览。",
  source_reports: ["scratch/reports/ws26_runtime_snapshot_ws26_002.json"],
  source_endpoints: ["/v1/ops/runtime/posture"],
  meta: { mode: "mock", note: "runtime mock" },
  data: {
    summary: {
      overall_status: "warning",
      control_plane_mode: "single_control_plane",
      single_control_plane: true
    },
    metrics: {
      runtime_rollout: { value: 0.92, unit: "ratio", status: "ok", configured_rollout_percent: 100 },
      runtime_fail_open: {
        value: 0.08,
        unit: "ratio",
        status: "warning",
        fail_open_count: 2,
        fail_open_blocked_ratio: 0.02,
        budget_remaining_ratio: 0.61,
        budget_exhausted: false
      },
      runtime_lease: {
        value: 14,
        unit: "seconds_to_expiry",
        status: "ok",
        state: "healthy",
        fencing_epoch: 21,
        lease_lost_churn_ratio: 0.01
      },
      queue_depth: {
        value: 7,
        unit: "events",
        status: "warning",
        oldest_pending_age_seconds: 92
      },
      lock_status: {
        value: 4,
        unit: "seconds_to_expiry",
        status: "warning",
        state: "held",
        fencing_epoch: 21
      },
      disk_watermark_ratio: {
        value: 0.42,
        unit: "ratio",
        status: "ok",
        filesystem_free_gb: 228
      },
      error_rate: { value: 0.034, unit: "ratio", status: "warning" },
      latency_p95_ms: { value: 188, unit: "ms", status: "ok" }
    },
    core_child_spawn_deferred: {
      deferred_count: 9,
      core_execution_session_count: 5,
      latest_role: "review",
      role_counts: {
        dev: 4,
        review: 3,
        expert: 2
      }
    },
    agentic_loop_completion: {
      submitted_count: 32,
      not_submitted_count: 1,
      status: "warning"
    },
    execution_bridge_governance: {
      status: "ok",
      reason_text: "role guard 正常"
    },
    vision_multimodal: {
      status: "unknown",
      reason_text: "暂未观测到图像问答信号"
    }
  }
};

export const mockMemoryGraph: OpsEnvelope<MemoryGraphData> = {
  status: "success",
  generated_at: now,
  severity: "ok",
  reason_code: "MOCK_MEMORY_GRAPH",
  reason_text: "当前使用前端内置记忆图谱示例数据。",
  source_reports: ["logs/knowledge_graph/quintuples.json"],
  source_endpoints: ["/memory/stats", "/memory/quintuples"],
  meta: { mode: "mock", note: "memory mock" },
  data: {
    summary: {
      enabled: true,
      total_quintuples: 1842,
      active_tasks: 3,
      pending_tasks: 12,
      running_tasks: 2,
      failed_tasks: 1,
      graph_sample_size: 8,
      vector_index_state: "ready",
      vector_index_ready: true
    },
    task_manager: {
      pending_tasks: 12,
      running_tasks: 2,
      failed_tasks: 1
    },
    vector_index: {
      ready: true,
      state: "ready"
    },
    relation_hotspots: [
      { relation: "depends_on", count: 44 },
      { relation: "owns", count: 29 },
      { relation: "uses", count: 25 },
      { relation: "fixes", count: 18 }
    ],
    entity_hotspots: [
      { entity: "Embla_core", count: 58 },
      { entity: "MemoryManager", count: 33 },
      { entity: "MCPManager", count: 24 },
      { entity: "AgentSession", count: 18 }
    ],
    graph_sample: [
      { subject: "Embla_core", subject_type: "frontend", predicate: "visualizes", object: "Runtime Posture", object_type: "dashboard" },
      { subject: "Embla_core", subject_type: "frontend", predicate: "manages", object: "MCP Fabric", object_type: "service_fabric" },
      { subject: "MemoryManager", subject_type: "service", predicate: "stores", object: "quintuples", object_type: "memory" },
      { subject: "AgentSession", subject_type: "runtime", predicate: "tracks", object: "role_counts", object_type: "agent_state" },
      { subject: "Workflow Queue", subject_type: "runtime", predicate: "contains", object: "pending tasks", object_type: "task" },
      { subject: "Skill", subject_type: "capability", predicate: "extends", object: "Embla agent", object_type: "agent" },
      { subject: "MCP Fabric", subject_type: "service_fabric", predicate: "routes", object: "tool calls", object_type: "tool" },
      { subject: "Runtime Lease", subject_type: "runtime", predicate: "guards", object: "single control plane", object_type: "policy" }
    ]
  }
};

export const mockMcpFabric: OpsEnvelope<McpFabricData> = {
  status: "success",
  generated_at: now,
  severity: "warning",
  reason_code: "MOCK_MCP_FABRIC",
  reason_text: "当前使用前端内置 MCP/Skill 示例数据。",
  source_reports: ["mcpserver/", "skills/"],
  source_endpoints: ["/v1/ops/mcp/fabric"],
  meta: { mode: "mock", note: "mcp mock" },
  data: {
    summary: {
      total_services: 8,
      available_services: 6,
      builtin_services: 5,
      mcporter_services: 3,
      isolated_worker_services: 1,
      rejected_plugin_manifests: 0
    },
    services: [
      { name: "weather_time", display_name: "Weather & Time", description: "天气和时间", source: "builtin", available: true, status_label: "online" },
      { name: "online_search", display_name: "Online Search", description: "联网搜索", source: "builtin", available: true, status_label: "online" },
      { name: "crawl4ai", display_name: "Crawl4AI", description: "网页抓取", source: "builtin", available: false, status_label: "offline", status_reason: "依赖未就绪" },
      { name: "playwright_master", display_name: "Playwright", description: "浏览器自动化", source: "mcporter", available: true, status_label: "configured" },
      { name: "vision", display_name: "Vision", description: "视觉识别", source: "mcporter", available: true, status_label: "configured" }
    ],
    tasks: {
      total: 8,
      tasks: [
        { task_id: "builtin:weather_time", service_name: "weather_time", status: "registered", source: "builtin" },
        { task_id: "mcporter:playwright_master", service_name: "playwright_master", status: "configured", source: "mcporter" }
      ]
    },
    registry: {
      registered_services: 8
    },
    runtime_snapshot: {
      server: "online"
    },
    tool_inventory: {
      total_tools: 18,
      memory_tools: 8,
      native_tools: 9,
      dynamic_tools: 1,
      tool_names: ["memory_read", "write_file", "workspace_txn_apply"]
    },
    skill_inventory: {
      total_skills: 10,
      bundled_skills: [
        { name: "web-search", path: "skills/web-search/SKILL.md" },
        { name: "translate", path: "skills/translate/SKILL.md" },
        { name: "code-review", path: "skills/code-review/SKILL.md" }
      ]
    }
  }
};

export const mockWorkflowEvents: OpsEnvelope<WorkflowEventData> = {
  status: "success",
  generated_at: now,
  severity: "warning",
  reason_code: "MOCK_WORKFLOW_EVENTS",
  reason_text: "当前使用前端内置工作流事件示例数据。",
  source_reports: ["logs/autonomous/events.jsonl"],
  source_endpoints: ["/v1/ops/workflow/events"],
  meta: { mode: "mock", note: "workflow mock" },
  data: {
    summary: {
      overall_status: "warning",
      outbox_pending: 7,
      oldest_pending_age_seconds: 92,
      critical_events_total: 3,
      events_scanned: 156
    },
    queue_depth: {
      value: 7,
      unit: "events",
      status: "warning",
      oldest_pending_age_seconds: 92
    },
    lock_status: {
      value: 4,
      unit: "seconds_to_expiry",
      status: "warning",
      state: "held"
    },
    runtime_lease: {
      value: 14,
      unit: "seconds_to_expiry",
      status: "ok",
      state: "healthy"
    },
    event_counters: {
      LeaseLost: 1,
      IncidentOpened: 1,
      VisionMultimodalQAError: 1
    },
    recent_critical_events: [
      { timestamp: now, event_type: "LeaseLost", payload_excerpt: "lease global_orchestrator expired" },
      { timestamp: now, event_type: "IncidentOpened", payload_excerpt: "queue backlog above warning threshold" },
      { timestamp: now, event_type: "TaskHeartbeatEscalatedBlocked", payload_excerpt: "dev/api-auth task patch-auth timed out and was respawned" },
      { timestamp: now, event_type: "VisionMultimodalQAError", payload_excerpt: "fallback answer used" }
    ],
    heartbeat_supervision: {
      summary: {
        root_session_id: "runtime",
        session_count: 6,
        sessions_with_heartbeats: 3,
        task_count: 4,
        fresh_count: 2,
        warning_count: 1,
        critical_count: 0,
        blocked_count: 1,
        max_stale_level: "blocked",
        latest_generated_at: now,
        has_stale: true,
        has_blocked: true
      },
      sessions: [
        {
          session_id: "dev-auth-1",
          parent_id: "expert-backend-1",
          role: "dev",
          status: "running",
          heartbeat_summary: {
            task_count: 1,
            blocked_count: 1,
            max_stale_level: "blocked"
          }
        },
        {
          session_id: "dev-ui-1",
          parent_id: "expert-frontend-1",
          role: "dev",
          status: "running",
          heartbeat_summary: {
            task_count: 2,
            warning_count: 1,
            fresh_count: 1,
            max_stale_level: "warning"
          }
        }
      ],
      heartbeats: [
        {
          session_id: "dev-auth-1",
          task_id: "patch-auth",
          role: "dev",
          status: "running",
          message: "sandbox task still running",
          stage: "sandbox_exec",
          stale_level: "blocked",
          generated_at: now
        },
        {
          session_id: "dev-ui-1",
          task_id: "wire-dashboard",
          role: "dev",
          status: "running",
          message: "waiting for dependency update",
          stage: "apply_patch",
          stale_level: "warning",
          generated_at: now
        }
      ]
    },
    log_context_statistics: {
      total_files: 4,
      total_messages: 281,
      user_messages: 101,
      assistant_messages: 180
    },
    tool_status: {
      visible: true,
      message: "review agent 正在整理最近一次修复结论"
    }
  }
};

export const mockIncidents: OpsEnvelope<IncidentsData> = {
  status: "success",
  generated_at: now,
  severity: "warning",
  reason_code: "MOCK_INCIDENTS",
  reason_text: "当前使用前端内置演练与事件示例数据。",
  source_reports: ["scratch/reports/ws27_oob_repair_drill_ws27_003.json"],
  source_endpoints: ["/v1/ops/incidents/latest"],
  meta: { mode: "mock", note: "incidents mock" },
  data: {
    summary: {
      total_incidents: 3,
      critical_incidents: 1,
      warning_incidents: 2,
      latest_incident_at: now
    },
    incidents: [
      {
        timestamp: now,
        event_type: "IncidentOpened",
        severity: "critical",
        source: "runtime_chaos",
        summary: "runtime lease 抖动导致控制平面切换风险",
        payload_excerpt: "建议检查 lease fencing 与 watchdog tick 对齐",
        report_path: "scratch/reports/ws26_m11_runtime_chaos_ws26_006.json",
        gate_level: "hard"
      },
      {
        timestamp: now,
        event_type: "RepairDrill",
        severity: "warning",
        source: "oob_drill",
        summary: "OOB 修复演练通过，但存在 1 个手工回退步骤",
        report_path: "scratch/reports/ws27_oob_repair_drill_ws27_003.json",
        gate_level: "soft"
      }
    ]
  }
};

export const mockEvidence: OpsEnvelope<EvidenceData> = {
  status: "success",
  generated_at: now,
  severity: "warning",
  source_reports: ["scratch/reports/"],
  source_endpoints: ["/v1/ops/evidence/index"],
  meta: { mode: "mock", note: "evidence mock" },
  data: {
    summary: {
      required_total: 4,
      required_present: 3,
      required_passed: 2,
      hard_missing: 0,
      soft_missing: 1
    },
    required_reports: [
      {
        id: "release-closure",
        label: "Release Closure Chain",
        path: "scratch/reports/release_closure_chain_full_m0_m12_result.json",
        status: "passed",
        gate_level: "hard",
        exists: true,
        passed: true,
        modified_at: now
      },
      {
        id: "wallclock-72h",
        label: "72h Wallclock Acceptance",
        path: "scratch/reports/ws27_72h_wallclock_acceptance_ws27_001.json",
        status: "missing",
        gate_level: "soft",
        exists: false,
        passed: false
      }
    ],
    recent_reports: []
  }
};
