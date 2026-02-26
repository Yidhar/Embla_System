from autonomous.system_agent import SystemAgentConfig


def test_system_agent_config_from_source_defaults():
    cfg = SystemAgentConfig.from_source(None)
    assert cfg.enabled is False
    assert cfg.preferred_cli == "codex"
    assert cfg.fallback_order == ("claude", "gemini")
    assert cfg.verification_fallback.enable_codex_mcp is True
    assert cfg.verification_fallback.mcp_service_name == "codex-cli"
    assert cfg.lease.enabled is True
    assert cfg.outbox_dispatch.enabled is True
    assert cfg.release.enabled is True
    assert cfg.watchdog.enabled is False
    assert cfg.watchdog.warn_only is True
    assert cfg.subagent_runtime.enabled is False
    assert cfg.subagent_runtime.fail_open is True
    assert cfg.subagent_runtime.fail_open_budget_ratio == 0.15
    assert cfg.subagent_runtime.max_subtasks == 16
    assert cfg.subagent_runtime.rollout_percent == 100
    assert cfg.subagent_runtime.enforce_scaffold_txn_for_write is True
    assert cfg.subagent_runtime.allow_legacy_fail_open_for_write is False
    assert cfg.subagent_runtime.disable_legacy_cli_fallback is False


def test_system_agent_config_from_dict():
    source = {
        "enabled": True,
        "cycle_interval_seconds": 600,
        "cli_tools": {
            "preferred": "codex",
            "fallback_order": ["gemini"],
            "max_retries": 3,
        },
        "verification_fallback": {
            "enable_codex_mcp": True,
            "mcp_server_name": "codex-cli",
            "tool_name": "ask-codex",
            "sandbox_mode": "read-only",
            "approval_policy": "on-failure",
        },
        "lease": {
            "enabled": True,
            "lease_name": "global_orchestrator",
            "owner_id": "agent-a",
            "renew_interval_seconds": 3,
            "ttl_seconds": 12,
            "standby_poll_interval_seconds": 4,
        },
        "outbox_dispatch": {
            "enabled": True,
            "consumer_name": "release-controller",
            "poll_interval_seconds": 5,
            "batch_size": 25,
        },
        "release": {
            "enabled": True,
            "gate_policy_path": "policy/gate_policy.yaml",
            "max_error_rate": 0.03,
            "max_latency_p95_ms": 2000.0,
            "min_kpi_ratio": 0.9,
            "auto_rollback_enabled": True,
            "rollback_command": "",
        },
        "watchdog": {
            "enabled": True,
            "warn_only": False,
            "cpu_percent": 70.0,
            "memory_percent": 75.0,
            "disk_percent": 80.0,
            "io_read_bps": 2048.0,
            "io_write_bps": 4096.0,
            "cost_per_hour": 1.5,
        },
        "subagent_runtime": {
            "enabled": True,
            "max_subtasks": 9,
            "rollout_percent": 25,
            "fail_open": False,
            "fail_open_budget_ratio": 0.45,
            "enforce_scaffold_txn_for_write": False,
            "allow_legacy_fail_open_for_write": True,
            "disable_legacy_cli_fallback": True,
            "require_contract_negotiation": False,
            "require_scaffold_patch": False,
            "fail_fast_on_subtask_error": False,
        },
    }
    cfg = SystemAgentConfig.from_source(source)
    assert cfg.enabled is True
    assert cfg.cycle_interval_seconds == 600
    assert cfg.preferred_cli == "codex"
    assert cfg.fallback_order == ("gemini",)
    assert cfg.max_retries == 3
    assert cfg.lease.owner_id == "agent-a"
    assert cfg.outbox_dispatch.batch_size == 25
    assert cfg.release.max_error_rate == 0.03
    assert cfg.watchdog.enabled is True
    assert cfg.watchdog.warn_only is False
    assert cfg.watchdog.cpu_percent == 70.0
    assert cfg.subagent_runtime.enabled is True
    assert cfg.subagent_runtime.max_subtasks == 9
    assert cfg.subagent_runtime.rollout_percent == 25
    assert cfg.subagent_runtime.fail_open is False
    assert cfg.subagent_runtime.fail_open_budget_ratio == 0.45
    assert cfg.subagent_runtime.enforce_scaffold_txn_for_write is False
    assert cfg.subagent_runtime.allow_legacy_fail_open_for_write is True
    assert cfg.subagent_runtime.disable_legacy_cli_fallback is True
    assert cfg.subagent_runtime.require_contract_negotiation is False
