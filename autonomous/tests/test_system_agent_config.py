from autonomous.system_agent import SystemAgentConfig


def test_system_agent_config_from_source_defaults():
    cfg = SystemAgentConfig.from_source(None)
    assert cfg.enabled is False
    assert cfg.verification_fallback.enable_codex_mcp is True
    assert cfg.verification_fallback.mcp_service_name == "codex-cli"
    assert cfg.lease.enabled is True
    assert cfg.outbox_dispatch.enabled is True
    assert cfg.release.enabled is True


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
