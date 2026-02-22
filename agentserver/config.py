#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Agent server configuration."""

from __future__ import annotations

from dataclasses import dataclass

# Server port from global config when available.
try:
    from system.config import get_server_port

    AGENT_SERVER_PORT = get_server_port("agent_server")
except ImportError:
    AGENT_SERVER_PORT = 8001


@dataclass
class TaskSchedulerConfig:
    """Task scheduler behavior settings."""

    max_steps: int = 15
    compression_threshold: int = 7
    keep_last_steps: int = 4

    key_facts_compression_limit: int = 5
    key_facts_summary_limit: int = 10
    compressed_memory_summary_limit: int = 3
    compressed_memory_global_limit: int = 2
    key_findings_display_limit: int = 3
    failed_attempts_display_limit: int = 3

    output_summary_length: int = 256
    step_output_display_length: int = 512

    enable_auto_compression: bool = True
    compression_timeout: int = 30
    max_compression_retries: int = 3


DEFAULT_TASK_SCHEDULER_CONFIG = TaskSchedulerConfig()


@dataclass
class AgentServerConfig:
    """Global config for agent server."""

    host: str = "127.0.0.1"
    port: int | None = None

    task_scheduler: TaskSchedulerConfig | None = None

    log_level: str = "INFO"
    enable_debug_logs: bool = False

    def __post_init__(self) -> None:
        if self.port is None:
            self.port = AGENT_SERVER_PORT

        if self.task_scheduler is None:
            self.task_scheduler = DEFAULT_TASK_SCHEDULER_CONFIG


config = AgentServerConfig()


def get_task_scheduler_config() -> TaskSchedulerConfig:
    """Get task scheduler config."""

    return config.task_scheduler


def update_config(**kwargs) -> None:
    """Update agent server config values."""

    for key, value in kwargs.items():
        if hasattr(config, key):
            setattr(config, key, value)
        else:
            raise ValueError(f"Unknown config key: {key}")


AGENT_SERVER_HOST = config.host
AGENT_SERVER_PORT = config.port
