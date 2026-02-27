"""System Agent skeleton implementation."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import uuid
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

from autonomous.dispatcher import DispatchResult, Dispatcher
from autonomous.event_log import AlertEventProducer, CronEventProducer, EventStore
from autonomous.evaluator import Evaluator
from autonomous.planner import Planner
from autonomous.release import CanaryThresholds, ReleaseController
from autonomous.sensor import Sensor
from autonomous.state import WorkflowStore
from autonomous.tools.codex_mcp_adapter import CodexMcpVerifier
from autonomous.tools.execution_bridge import NativeExecutionBridge
from autonomous.tools.subagent_runtime import (
    RuntimeSubTaskResult,
    RuntimeSubTaskSpec,
    SubAgentRuntime,
    SubAgentRuntimeConfig,
    SubAgentRuntimeResult,
)
from autonomous.types import OptimizationTask
from system.brainstem_event_bridge import BRIDGED_EVENT_TYPE, build_brainstem_bridge_payload
from system.watchdog_daemon import WatchdogAction, WatchdogDaemon, WatchdogThresholds


class LeaseLostError(RuntimeError):
    """Raised when the instance loses current lease ownership."""


@dataclass
class VerificationFallbackConfig:
    enable_codex_mcp: bool = True
    mcp_service_name: str = "codex-cli"
    mcp_tool_name: str = "ask-codex"
    sandbox_mode: str = "read-only"
    approval_policy: str = "on-failure"


@dataclass
class LeaseConfig:
    enabled: bool = True
    lease_name: str = "global_orchestrator"
    owner_id: str = ""
    renew_interval_seconds: int = 2
    ttl_seconds: int = 10
    standby_poll_interval_seconds: int = 2


@dataclass
class OutboxDispatchConfig:
    enabled: bool = True
    consumer_name: str = "release-controller"
    poll_interval_seconds: int = 2
    batch_size: int = 50


@dataclass
class ReleaseAutomationConfig:
    enabled: bool = True
    gate_policy_path: str = "policy/gate_policy.yaml"
    max_error_rate: float = 0.02
    max_latency_p95_ms: float = 1500.0
    min_kpi_ratio: float = 0.95
    auto_rollback_enabled: bool = True
    rollback_command: str = ""


@dataclass
class WatchdogRuntimeConfig:
    enabled: bool = False
    warn_only: bool = True
    cpu_percent: float = 85.0
    memory_percent: float = 85.0
    disk_percent: float = 90.0
    io_read_bps: float = 50 * 1024 * 1024
    io_write_bps: float = 50 * 1024 * 1024
    cost_per_hour: float = 5.0
    prefer_daemon_state: bool = True
    daemon_state_file: str = "scratch/runtime/watchdog_daemon_state_ws28_025.json"
    daemon_state_stale_warning_seconds: float = 120.0
    daemon_state_stale_critical_seconds: float = 300.0
    fail_closed_on_daemon_state_stale: bool = False


@dataclass
class SystemAgentConfig:
    enabled: bool = False
    cycle_interval_seconds: int = 3600
    preferred_cli: str = "codex"
    fallback_order: tuple[str, ...] = ("claude", "gemini")
    max_retries: int = 2
    run_quality_checks: bool = False
    default_timeout_seconds: int = 3600
    verification_fallback: VerificationFallbackConfig = field(default_factory=VerificationFallbackConfig)
    lease: LeaseConfig = field(default_factory=LeaseConfig)
    outbox_dispatch: OutboxDispatchConfig = field(default_factory=OutboxDispatchConfig)
    release: ReleaseAutomationConfig = field(default_factory=ReleaseAutomationConfig)
    watchdog: WatchdogRuntimeConfig = field(default_factory=WatchdogRuntimeConfig)
    subagent_runtime: SubAgentRuntimeConfig = field(default_factory=SubAgentRuntimeConfig)

    @classmethod
    def from_source(cls, source: Any) -> "SystemAgentConfig":
        if source is None:
            return cls()

        def pick(container: Any, key: str, default: Any) -> Any:
            if isinstance(container, dict):
                return container.get(key, default)
            return getattr(container, key, default)

        cli_tools = pick(source, "cli_tools", {})
        verification = pick(source, "verification_fallback", {})
        lease = pick(source, "lease", {})
        outbox_dispatch = pick(source, "outbox_dispatch", {})
        release = pick(source, "release", {})
        watchdog = pick(source, "watchdog", {})
        subagent_runtime = pick(source, "subagent_runtime", {})

        fallback_cfg = VerificationFallbackConfig(
            enable_codex_mcp=pick(verification, "enable_codex_mcp", True),
            mcp_service_name=pick(verification, "mcp_server_name", pick(verification, "mcp_service_name", "codex-cli")),
            mcp_tool_name=pick(verification, "tool_name", "ask-codex"),
            sandbox_mode=pick(verification, "sandbox_mode", "read-only"),
            approval_policy=pick(verification, "approval_policy", "on-failure"),
        )
        lease_cfg = LeaseConfig(
            enabled=bool(pick(lease, "enabled", True)),
            lease_name=str(pick(lease, "lease_name", "global_orchestrator")),
            owner_id=str(pick(lease, "owner_id", "")),
            renew_interval_seconds=max(1, int(pick(lease, "renew_interval_seconds", 2))),
            ttl_seconds=max(1, int(pick(lease, "ttl_seconds", 10))),
            standby_poll_interval_seconds=max(1, int(pick(lease, "standby_poll_interval_seconds", 2))),
        )
        outbox_cfg = OutboxDispatchConfig(
            enabled=bool(pick(outbox_dispatch, "enabled", True)),
            consumer_name=str(pick(outbox_dispatch, "consumer_name", "release-controller")),
            poll_interval_seconds=max(1, int(pick(outbox_dispatch, "poll_interval_seconds", 2))),
            batch_size=max(1, int(pick(outbox_dispatch, "batch_size", 50))),
        )
        release_cfg = ReleaseAutomationConfig(
            enabled=bool(pick(release, "enabled", True)),
            gate_policy_path=str(pick(release, "gate_policy_path", "policy/gate_policy.yaml")),
            max_error_rate=max(0.0, float(pick(release, "max_error_rate", 0.02))),
            max_latency_p95_ms=max(1.0, float(pick(release, "max_latency_p95_ms", 1500.0))),
            min_kpi_ratio=max(0.0, min(1.0, float(pick(release, "min_kpi_ratio", 0.95)))),
            auto_rollback_enabled=bool(pick(release, "auto_rollback_enabled", True)),
            rollback_command=str(pick(release, "rollback_command", "")),
        )
        watchdog_cfg = WatchdogRuntimeConfig(
            enabled=bool(pick(watchdog, "enabled", False)),
            warn_only=bool(pick(watchdog, "warn_only", True)),
            cpu_percent=max(1.0, min(100.0, float(pick(watchdog, "cpu_percent", 85.0)))),
            memory_percent=max(1.0, min(100.0, float(pick(watchdog, "memory_percent", 85.0)))),
            disk_percent=max(1.0, min(100.0, float(pick(watchdog, "disk_percent", 90.0)))),
            io_read_bps=max(1.0, float(pick(watchdog, "io_read_bps", 50 * 1024 * 1024))),
            io_write_bps=max(1.0, float(pick(watchdog, "io_write_bps", 50 * 1024 * 1024))),
            cost_per_hour=max(0.0, float(pick(watchdog, "cost_per_hour", 5.0))),
            prefer_daemon_state=bool(pick(watchdog, "prefer_daemon_state", True)),
            daemon_state_file=str(
                pick(watchdog, "daemon_state_file", "scratch/runtime/watchdog_daemon_state_ws28_025.json")
            ),
            daemon_state_stale_warning_seconds=max(
                1.0,
                float(pick(watchdog, "daemon_state_stale_warning_seconds", 120.0)),
            ),
            daemon_state_stale_critical_seconds=max(
                1.0,
                float(pick(watchdog, "daemon_state_stale_critical_seconds", 300.0)),
            ),
            fail_closed_on_daemon_state_stale=bool(pick(watchdog, "fail_closed_on_daemon_state_stale", False)),
        )
        subagent_cfg = SubAgentRuntimeConfig(
            enabled=bool(pick(subagent_runtime, "enabled", False)),
            max_subtasks=max(1, int(pick(subagent_runtime, "max_subtasks", 16))),
            rollout_percent=max(0, min(100, int(pick(subagent_runtime, "rollout_percent", 100)))),
            fail_open=bool(pick(subagent_runtime, "fail_open", True)),
            fail_open_budget_ratio=max(0.0, min(1.0, float(pick(subagent_runtime, "fail_open_budget_ratio", 0.15)))),
            enforce_scaffold_txn_for_write=bool(pick(subagent_runtime, "enforce_scaffold_txn_for_write", True)),
            allow_legacy_fail_open_for_write=bool(pick(subagent_runtime, "allow_legacy_fail_open_for_write", False)),
            disable_legacy_cli_fallback=bool(pick(subagent_runtime, "disable_legacy_cli_fallback", False)),
            require_contract_negotiation=bool(pick(subagent_runtime, "require_contract_negotiation", True)),
            require_scaffold_patch=bool(pick(subagent_runtime, "require_scaffold_patch", True)),
            fail_fast_on_subtask_error=bool(pick(subagent_runtime, "fail_fast_on_subtask_error", True)),
        )

        return cls(
            enabled=pick(source, "enabled", False),
            cycle_interval_seconds=max(60, int(pick(source, "cycle_interval_seconds", 3600))),
            preferred_cli=pick(cli_tools, "preferred", "codex"),
            fallback_order=tuple(pick(cli_tools, "fallback_order", ["claude", "gemini"])),
            max_retries=max(0, int(pick(cli_tools, "max_retries", 2))),
            run_quality_checks=bool(pick(source, "run_quality_checks", False)),
            default_timeout_seconds=max(60, int(pick(source, "fixed_timeout_seconds", 3600))),
            verification_fallback=fallback_cfg,
            lease=lease_cfg,
            outbox_dispatch=outbox_cfg,
            release=release_cfg,
            watchdog=watchdog_cfg,
            subagent_runtime=subagent_cfg,
        )


@dataclass
class TaskAttemptOutcome:
    approved: bool
    reasons: List[str] = field(default_factory=list)
    dispatch_result: DispatchResult | None = None
    subagent_runtime_result: SubAgentRuntimeResult | None = None
    used_fail_open: bool = False


class _SystemAgentWatchdogEmitter:
    def __init__(self, agent: "SystemAgent") -> None:
        self._agent = agent

    def emit(self, event_type: str, payload: Dict[str, Any], **kwargs: Any) -> None:
        self._agent._emit(event_type, payload, **kwargs)


class SystemAgent:
    """Single-active autonomous loop with durable workflow state."""

    def __init__(self, config: Any, repo_dir: str | None = None) -> None:
        self.config = SystemAgentConfig.from_source(config)
        self.repo_dir = Path(repo_dir or Path.cwd())
        self.logger = logging.getLogger("autonomous.system_agent")

        log_dir = self.repo_dir / "logs" / "autonomous"
        event_path = log_dir / "events.jsonl"
        db_path = log_dir / "workflow.db"

        self.event_store = EventStore(event_path)
        self.cron_event_producer = CronEventProducer(
            event_store=self.event_store,
            source="autonomous.system_agent.cron",
        )
        self.alert_event_producer = AlertEventProducer(
            event_store=self.event_store,
            source="autonomous.system_agent.alert",
            dedupe_window_seconds=30.0,
        )
        self.cron_event_producer.add_schedule(
            schedule_id="system_agent_cycle_tick",
            interval_seconds=max(1, int(self.config.cycle_interval_seconds)),
            topic="cron.system_agent.cycle",
            event_type="CronScheduleTriggered",
            payload={"producer": "system_agent"},
            run_immediately=True,
        )
        self.workflow_store = WorkflowStore(db_path=db_path)

        self.sensor = Sensor(str(self.repo_dir))
        self.planner = Planner()
        self.dispatcher = Dispatcher(
            repo_dir=str(self.repo_dir),
            preferred_cli=self.config.preferred_cli,
            fallback_order=list(self.config.fallback_order),
            default_timeout_seconds=self.config.default_timeout_seconds,
        )
        self.evaluator = Evaluator(str(self.repo_dir), run_quality_checks=self.config.run_quality_checks)
        self.fallback_verifier = CodexMcpVerifier(
            service_name=self.config.verification_fallback.mcp_service_name,
            tool_name=self.config.verification_fallback.mcp_tool_name,
            sandbox_mode=self.config.verification_fallback.sandbox_mode,
            approval_policy=self.config.verification_fallback.approval_policy,
        )

        policy_path = Path(self.config.release.gate_policy_path)
        if not policy_path.is_absolute():
            policy_path = self.repo_dir / policy_path
        self.release_controller = ReleaseController(
            repo_dir=str(self.repo_dir),
            policy_path=policy_path,
            thresholds=CanaryThresholds(
                max_error_rate=self.config.release.max_error_rate,
                max_latency_p95_ms=self.config.release.max_latency_p95_ms,
                min_kpi_ratio=self.config.release.min_kpi_ratio,
            ),
        )

        self.instance_id = self._build_instance_id(self.config.lease.owner_id)
        self._stop_event = asyncio.Event()
        self._running = False
        self._is_leader = not self.config.lease.enabled
        self._fencing_epoch = 1 if not self.config.lease.enabled else 0
        self._lease_task: asyncio.Task[None] | None = None
        self._outbox_task: asyncio.Task[None] | None = None
        self.subagent_runtime = SubAgentRuntime(
            project_root=self.repo_dir,
            config=self.config.subagent_runtime,
        )
        self.execution_bridge = NativeExecutionBridge(project_root=self.repo_dir)
        self.watchdog_daemon: WatchdogDaemon | None = None
        self.watchdog_daemon_state_file = self.repo_dir / str(self.config.watchdog.daemon_state_file)
        if self.config.watchdog.enabled:
            self.watchdog_daemon = WatchdogDaemon(
                thresholds=WatchdogThresholds(
                    cpu_percent=self.config.watchdog.cpu_percent,
                    memory_percent=self.config.watchdog.memory_percent,
                    disk_percent=self.config.watchdog.disk_percent,
                    io_read_bps=self.config.watchdog.io_read_bps,
                    io_write_bps=self.config.watchdog.io_write_bps,
                    cost_per_hour=self.config.watchdog.cost_per_hour,
                ),
                event_emitter=_SystemAgentWatchdogEmitter(self),
                warn_only=self.config.watchdog.warn_only,
            )
        self._subagent_gate_metrics: Dict[str, int] = {
            "contract_failures": 0,
            "scaffold_failures": 0,
            "runtime_failures": 0,
        }
        self._subagent_fail_open_budget: Dict[str, Any] = {
            "subagent_attempt_count": 0,
            "fail_open_count": 0,
            "fail_open_ratio": 0.0,
            "budget_ratio": float(self.config.subagent_runtime.fail_open_budget_ratio),
            "degraded_to_legacy": False,
            "degrade_reason": "",
        }

    @staticmethod
    def _build_instance_id(configured_owner_id: str) -> str:
        owner = (configured_owner_id or "").strip()
        if owner:
            return owner
        host = os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME") or "localhost"
        return f"{host}-{os.getpid()}-{uuid.uuid4().hex[:8]}"

    async def start(self) -> None:
        if not self.config.enabled:
            self._emit("AutonomousDisabled", {"reason": "config.autonomous.enabled=false"})
            return

        if self._running:
            return

        self._running = True
        self._stop_event.clear()
        self._emit(
            "AgentStarted",
            {
                "cycle_interval_seconds": self.config.cycle_interval_seconds,
                "instance_id": self.instance_id,
                "lease_enabled": self.config.lease.enabled,
            },
        )
        self.logger.info("[SystemAgent] started instance_id=%s", self.instance_id)

        if not self.config.lease.enabled:
            self._emit("LeaseBypassed", {"instance_id": self.instance_id, "fencing_epoch": self._fencing_epoch})
        else:
            self._lease_task = asyncio.create_task(self._lease_heartbeat_loop())

        if self.config.outbox_dispatch.enabled:
            self._outbox_task = asyncio.create_task(self._outbox_dispatch_loop())

        try:
            while not self._stop_event.is_set():
                if self._is_leader:
                    await self.run_cycle(fencing_epoch=self._fencing_epoch if self._fencing_epoch > 0 else None)
                    await self._wait_next_cycle()
                else:
                    await self._sleep_or_stop(self.config.lease.standby_poll_interval_seconds)
        except asyncio.CancelledError:
            self.logger.info("[SystemAgent] cancelled")
            raise
        except Exception as exc:
            self._emit("AgentCrashed", {"error": str(exc)})
            self.logger.exception("[SystemAgent] crashed: %s", exc)
        finally:
            if self._lease_task is not None and not self._lease_task.done():
                self._lease_task.cancel()
                with suppress(asyncio.CancelledError):
                    await self._lease_task
            self._lease_task = None
            if self._outbox_task is not None and not self._outbox_task.done():
                self._outbox_task.cancel()
                with suppress(asyncio.CancelledError):
                    await self._outbox_task
            self._outbox_task = None
            self._running = False
            self._emit("AgentStopped", {})

    async def stop(self) -> None:
        self._stop_event.set()

    async def run_cycle(self, fencing_epoch: int | None = None) -> None:
        active_epoch = self._ensure_active_epoch(fencing_epoch)
        self.cron_event_producer.run_due()
        self._emit("CycleStarted", {"instance_id": self.instance_id}, fencing_epoch=active_epoch)

        findings = self.sensor.scan_codebase() + self.sensor.scan_logs()
        self._emit(
            "AnalysisCompleted",
            {"findings_count": len(findings), "findings": findings},
            fencing_epoch=active_epoch,
        )

        tasks = self.planner.generate_tasks(findings)
        self._emit(
            "PlanDrafted",
            {"task_count": len(tasks), "task_ids": [t.task_id for t in tasks]},
            fencing_epoch=active_epoch,
        )

        for task in tasks:
            await self._run_task(task, fencing_epoch=active_epoch)

        self._emit("CycleCompleted", {"task_count": len(tasks)}, fencing_epoch=active_epoch)

    async def _run_task(self, task: OptimizationTask, *, fencing_epoch: int) -> None:
        self._ensure_active_epoch(fencing_epoch)
        workflow_id = f"wf-{task.task_id}"
        self.workflow_store.create_workflow(
            workflow_id=workflow_id,
            task_id=task.task_id,
            initial_state="GoalAccepted",
            max_retries=self.config.max_retries,
        )
        self.workflow_store.transition(workflow_id, "PlanDrafted", reason="task_planned")
        self.workflow_store.transition(workflow_id, "Implementing", reason="dispatch_started")

        self._emit(
            "TaskDispatching",
            {
                "workflow_id": workflow_id,
                "task_id": task.task_id,
                "complexity": task.complexity,
                "instruction": task.instruction,
            },
            workflow_id=workflow_id,
            fencing_epoch=fencing_epoch,
        )

        last_dispatch: DispatchResult | None = None
        last_reasons: list[str] = []
        max_attempt = self.config.max_retries + 1

        for attempt in range(1, max_attempt + 1):
            self._ensure_active_epoch(fencing_epoch)
            runtime_mode, rollout_context = self._resolve_runtime_mode(task=task)
            using_subagent = runtime_mode == "subagent"
            self._emit(
                "SubAgentRuntimeRolloutDecision",
                {
                    "workflow_id": workflow_id,
                    "task_id": task.task_id,
                    "attempt": attempt,
                    "runtime_mode": runtime_mode,
                    "rollout_percent": rollout_context.get("rollout_percent", 100),
                    "rollout_bucket": rollout_context.get("rollout_bucket"),
                    "decision_reason": rollout_context.get("reason", "unknown"),
                    "fail_open_budget_ratio": self._subagent_fail_open_budget.get("budget_ratio"),
                    "fail_open_ratio": self._subagent_fail_open_budget.get("fail_open_ratio"),
                    "auto_degraded_to_legacy": bool(self._subagent_fail_open_budget.get("degraded_to_legacy")),
                },
                workflow_id=workflow_id,
                fencing_epoch=fencing_epoch,
            )
            command_type = "subagent_execute" if using_subagent else "legacy_execute"
            idempotency_key = f"{task.task_id}:{command_type}:{attempt}"
            command_id = self.workflow_store.create_command(
                workflow_id=workflow_id,
                step_name="implement_verify",
                command_type=command_type,
                idempotency_key=idempotency_key,
                attempt=attempt,
                max_attempt=max_attempt,
                fencing_epoch=fencing_epoch,
            )

            watchdog_block = self._evaluate_watchdog_gate(
                task=task,
                workflow_id=workflow_id,
                attempt=attempt,
                runtime_mode="subagent" if using_subagent else "legacy",
                fencing_epoch=fencing_epoch,
            )
            write_path_block = self._evaluate_write_path_gate(
                task=task,
                workflow_id=workflow_id,
                attempt=attempt,
                runtime_mode="subagent" if using_subagent else "legacy",
                rollout_context=rollout_context,
                fencing_epoch=fencing_epoch,
            )
            if write_path_block is not None:
                outcome = write_path_block
            elif watchdog_block is not None:
                outcome = watchdog_block
            elif using_subagent:
                outcome = await self._execute_subagent_attempt(
                    task=task,
                    workflow_id=workflow_id,
                    attempt=attempt,
                    fencing_epoch=fencing_epoch,
                )
            else:
                outcome = await self._execute_legacy_attempt(
                    task=task,
                    workflow_id=workflow_id,
                    attempt=attempt,
                    fencing_epoch=fencing_epoch,
                )

            self._ensure_active_epoch(fencing_epoch)
            if outcome.dispatch_result is not None:
                last_dispatch = outcome.dispatch_result

            if outcome.approved:
                self.workflow_store.update_command(command_id, status="succeeded")
                release_payload: Dict[str, Any] = {
                    "attempt": attempt,
                    "runtime_mode": "subagent" if using_subagent else "legacy",
                    "used_fail_open": outcome.used_fail_open,
                }
                if outcome.subagent_runtime_result is not None:
                    release_payload["subagent_runtime_id"] = outcome.subagent_runtime_result.runtime_id
                    release_payload["trace_id"] = outcome.subagent_runtime_result.trace_id
                self.workflow_store.transition(
                    workflow_id,
                    "ReleaseCandidate",
                    reason="checks_passed",
                    payload=release_payload,
                )

                approved_payload: Dict[str, Any] = {
                    "workflow_id": workflow_id,
                    "task_id": task.task_id,
                    "attempt": attempt,
                    "runtime_mode": "subagent" if using_subagent else "legacy",
                    "used_fail_open": outcome.used_fail_open,
                }
                if outcome.subagent_runtime_result is not None:
                    approved_payload["subagent_runtime_id"] = outcome.subagent_runtime_result.runtime_id
                    approved_payload["trace_id"] = outcome.subagent_runtime_result.trace_id
                self._emit(
                    "TaskApproved",
                    approved_payload,
                    workflow_id=workflow_id,
                    enqueue_outbox=True,
                    fencing_epoch=fencing_epoch,
                )
                return

            last_reasons = list(outcome.reasons)
            self.workflow_store.update_command(command_id, status="failed", last_error="; ".join(last_reasons))
            rejected_payload: Dict[str, Any] = {
                "workflow_id": workflow_id,
                "task_id": task.task_id,
                "attempt": attempt,
                "reasons": last_reasons,
                "runtime_mode": "subagent" if using_subagent else "legacy",
                "used_fail_open": outcome.used_fail_open,
            }
            if outcome.subagent_runtime_result is not None:
                rejected_payload["subagent_runtime_id"] = outcome.subagent_runtime_result.runtime_id
                rejected_payload["failed_subtasks"] = list(outcome.subagent_runtime_result.failed_subtasks)
            self._emit(
                "TaskRejected",
                rejected_payload,
                workflow_id=workflow_id,
                fencing_epoch=fencing_epoch,
            )

            if attempt < max_attempt:
                self.workflow_store.transition(
                    workflow_id,
                    "Reworking",
                    reason="checks_failed_retry_remaining",
                    payload={"attempt": attempt, "max_attempt": max_attempt},
                )
                self.workflow_store.transition(workflow_id, "Implementing", reason="retry_dispatch")
                continue

            self.workflow_store.transition(
                workflow_id,
                "FailedExhausted",
                reason="checks_failed_retry_exhausted",
                payload={"attempt": attempt, "max_attempt": max_attempt},
                )

        if last_dispatch is not None:
            await self._attempt_verification_fallback(
                task=task,
                workflow_id=workflow_id,
                dispatch_result=last_dispatch,
                reasons=last_reasons,
                fencing_epoch=fencing_epoch,
            )

    def _evaluate_watchdog_gate(
        self,
        *,
        task: OptimizationTask,
        workflow_id: str,
        attempt: int,
        runtime_mode: str,
        fencing_epoch: int,
    ) -> TaskAttemptOutcome | None:
        daemon = self.watchdog_daemon
        if daemon is None:
            return None

        action: WatchdogAction | None = None
        daemon_state_status = ""
        daemon_state_reason_code = ""
        daemon_state_used = False
        if self.config.watchdog.prefer_daemon_state:
            daemon_state = WatchdogDaemon.read_daemon_state(
                self.watchdog_daemon_state_file,
                stale_warning_seconds=float(self.config.watchdog.daemon_state_stale_warning_seconds),
                stale_critical_seconds=float(self.config.watchdog.daemon_state_stale_critical_seconds),
            )
            daemon_state_status = str(daemon_state.get("status") or "")
            daemon_state_reason_code = str(daemon_state.get("reason_code") or "")
            daemon_state_used = daemon_state_status in {"ok", "warning", "critical"}
            self._emit(
                "WatchdogDaemonStateConsumed",
                {
                    "workflow_id": workflow_id,
                    "task_id": task.task_id,
                    "attempt": attempt,
                    "runtime_mode": runtime_mode,
                    "state_file": str(daemon_state.get("state_file") or ""),
                    "state": str(daemon_state.get("state") or ""),
                    "status": daemon_state_status,
                    "reason_code": daemon_state_reason_code,
                    "heartbeat_age_seconds": daemon_state.get("heartbeat_age_seconds"),
                    "tick": daemon_state.get("tick"),
                },
                workflow_id=workflow_id,
                fencing_epoch=fencing_epoch,
            )
            action_payload = daemon_state.get("action")
            if isinstance(action_payload, dict):
                action = WatchdogAction(
                    level=str(action_payload.get("level") or ""),
                    action=str(action_payload.get("action") or ""),
                    reasons=[str(item) for item in list(action_payload.get("reasons") or []) if str(item).strip()],
                    snapshot=(
                        dict(action_payload.get("snapshot"))
                        if isinstance(action_payload.get("snapshot"), dict)
                        else {}
                    ),
                )
            if (
                action is None
                and bool(self.config.watchdog.fail_closed_on_daemon_state_stale)
                and daemon_state_reason_code in {"WATCHDOG_DAEMON_STALE_WARNING", "WATCHDOG_DAEMON_STALE_CRITICAL"}
            ):
                action = WatchdogAction(
                    level="critical",
                    action="pause_dispatch_and_escalate",
                    reasons=[
                        f"watchdog_daemon:{daemon_state_reason_code}",
                        str(daemon_state.get("reason_text") or "watchdog daemon state is stale"),
                    ],
                    snapshot=(
                        dict(daemon_state.get("snapshot"))
                        if isinstance(daemon_state.get("snapshot"), dict)
                        else {}
                    ),
                )

        if action is None and (not daemon_state_used or daemon_state_reason_code in {"WATCHDOG_DAEMON_STATE_MISSING", "WATCHDOG_DAEMON_STALE_WARNING", "WATCHDOG_DAEMON_STALE_CRITICAL"}):
            action = daemon.run_once()
        if action is None:
            return None

        try:
            self.alert_event_producer.emit_alert(
                alert_key="watchdog_threshold_exceeded",
                severity=str(action.level or "warn"),
                topic="alert.watchdog",
                event_type="AlertRaised",
                payload={
                    "watchdog_action": action.action,
                    "watchdog_reasons": list(action.reasons),
                    "watchdog_snapshot": dict(action.snapshot),
                    "workflow_id": workflow_id,
                    "task_id": task.task_id,
                    "attempt": attempt,
                    "runtime_mode": runtime_mode,
                },
            )
        except Exception:
            pass

        blocking_actions = {"pause_dispatch_and_escalate", "throttle_new_workloads"}
        if action.action not in blocking_actions:
            return None

        reasons = [f"watchdog:{action.action}"]
        reasons.extend([f"watchdog:{item}" for item in list(action.reasons)])
        self._emit(
            "ReleaseGateRejected",
            {
                "workflow_id": workflow_id,
                "task_id": task.task_id,
                "gate": "watchdog",
                "attempt": attempt,
                "runtime_mode": runtime_mode,
                "watchdog_level": action.level,
                "watchdog_action": action.action,
                "reasons": reasons,
                "snapshot": dict(action.snapshot),
            },
            workflow_id=workflow_id,
            fencing_epoch=fencing_epoch,
        )
        return TaskAttemptOutcome(approved=False, reasons=reasons)

    async def _execute_legacy_attempt(
        self,
        *,
        task: OptimizationTask,
        workflow_id: str,
        attempt: int,
        fencing_epoch: int,
    ) -> TaskAttemptOutcome:
        dispatch_result = await self.dispatcher.dispatch(task)
        self._ensure_active_epoch(fencing_epoch)

        self._emit_task_execution_completed(
            workflow_id=workflow_id,
            task_id=task.task_id,
            attempt=attempt,
            runtime_mode="legacy",
            success=bool(dispatch_result.result.success),
            duration_seconds=float(dispatch_result.result.duration_seconds),
            fencing_epoch=fencing_epoch,
            executor="legacy_cli",
            executor_id=str(dispatch_result.selected_cli or ""),
            exit_code=dispatch_result.result.exit_code,
        )

        self.workflow_store.transition(
            workflow_id,
            "Verifying",
            reason="verification_started",
            payload={"attempt": attempt},
        )
        report = self.evaluator.evaluate(task, dispatch_result.result)
        return TaskAttemptOutcome(
            approved=report.approved,
            reasons=list(report.reasons),
            dispatch_result=dispatch_result,
        )

    async def _execute_subagent_attempt(
        self,
        *,
        task: OptimizationTask,
        workflow_id: str,
        attempt: int,
        fencing_epoch: int,
    ) -> TaskAttemptOutcome:
        trace_id = self._build_runtime_trace_id(task.task_id, attempt)
        session_id = f"{workflow_id}:attempt:{attempt}"

        runtime_result = await self.subagent_runtime.run(
            task=task,
            workflow_id=workflow_id,
            trace_id=trace_id,
            session_id=session_id,
            worker=lambda subtask: self._materialize_subtask_worker_result(task, subtask),
            emit_event=lambda event_type, payload: self._emit(
                event_type,
                payload,
                workflow_id=workflow_id,
                fencing_epoch=fencing_epoch,
            ),
            lease_guard=lambda: self._ensure_active_epoch(fencing_epoch),
        )

        self._ensure_active_epoch(fencing_epoch)
        self._record_subagent_attempt()
        self._emit_task_execution_completed(
            workflow_id=workflow_id,
            task_id=task.task_id,
            attempt=attempt,
            runtime_mode="subagent",
            success=bool(runtime_result.success and runtime_result.approved),
            duration_seconds=self._sum_subtask_durations(runtime_result),
            fencing_epoch=fencing_epoch,
            executor="native_execution_bridge",
            executor_id=str(runtime_result.runtime_id),
            gate_failure=str(runtime_result.gate_failure or ""),
            failed_subtask_count=len(runtime_result.failed_subtasks),
            fail_open_recommended=bool(runtime_result.fail_open_recommended),
        )
        if runtime_result.success and runtime_result.approved:
            return TaskAttemptOutcome(
                approved=True,
                reasons=[],
                subagent_runtime_result=runtime_result,
            )

        if runtime_result.gate_failure:
            self._record_subagent_gate_failure(
                gate=runtime_result.gate_failure,
                workflow_id=workflow_id,
                task_id=task.task_id,
                runtime_result=runtime_result,
                fencing_epoch=fencing_epoch,
            )

        if runtime_result.fail_open_recommended and self.config.subagent_runtime.fail_open:
            if bool(self.config.subagent_runtime.disable_legacy_cli_fallback):
                reasons = list(runtime_result.reasons)
                blocked_reason = "execution_bridge:legacy_cli_layer_disabled"
                if blocked_reason not in reasons:
                    reasons.append(blocked_reason)
                self._emit(
                    "SubAgentRuntimeFailOpenBlocked",
                    {
                        "workflow_id": workflow_id,
                        "task_id": task.task_id,
                        "attempt": attempt,
                        "runtime_id": runtime_result.runtime_id,
                        "gate_failure": runtime_result.gate_failure,
                        "reasons": reasons,
                    },
                    workflow_id=workflow_id,
                    fencing_epoch=fencing_epoch,
                )
                self._emit(
                    "ReleaseGateRejected",
                    {
                        "workflow_id": workflow_id,
                        "task_id": task.task_id,
                        "gate": "execution_bridge",
                        "attempt": attempt,
                        "runtime_mode": "subagent",
                        "decision_reason": "legacy_cli_layer_disabled",
                        "reasons": reasons,
                    },
                    workflow_id=workflow_id,
                    fencing_epoch=fencing_epoch,
                )
                return TaskAttemptOutcome(
                    approved=False,
                    reasons=reasons,
                    subagent_runtime_result=runtime_result,
                )
            if self._task_requires_scaffold_txn(task=task) and not bool(
                self.config.subagent_runtime.allow_legacy_fail_open_for_write
            ):
                reasons = list(runtime_result.reasons)
                blocked_reason = "write_path:legacy_fail_open_blocked"
                if blocked_reason not in reasons:
                    reasons.append(blocked_reason)
                self._emit(
                    "SubAgentRuntimeFailOpenBlocked",
                    {
                        "workflow_id": workflow_id,
                        "task_id": task.task_id,
                        "attempt": attempt,
                        "runtime_id": runtime_result.runtime_id,
                        "gate_failure": runtime_result.gate_failure,
                        "reasons": reasons,
                    },
                    workflow_id=workflow_id,
                    fencing_epoch=fencing_epoch,
                )
                self._emit(
                    "ReleaseGateRejected",
                    {
                        "workflow_id": workflow_id,
                        "task_id": task.task_id,
                        "gate": "write_path",
                        "attempt": attempt,
                        "runtime_mode": "subagent",
                        "decision_reason": "legacy_fail_open_blocked",
                        "reasons": reasons,
                    },
                    workflow_id=workflow_id,
                    fencing_epoch=fencing_epoch,
                )
                return TaskAttemptOutcome(
                    approved=False,
                    reasons=reasons,
                    subagent_runtime_result=runtime_result,
                )
            self._record_fail_open_and_maybe_degrade(
                workflow_id=workflow_id,
                task_id=task.task_id,
                attempt=attempt,
                runtime_id=runtime_result.runtime_id,
                gate_failure=runtime_result.gate_failure,
                reasons=list(runtime_result.reasons),
                fencing_epoch=fencing_epoch,
            )
            self._emit(
                "SubAgentRuntimeFailOpen",
                {
                    "workflow_id": workflow_id,
                    "task_id": task.task_id,
                    "attempt": attempt,
                    "runtime_id": runtime_result.runtime_id,
                    "gate_failure": runtime_result.gate_failure,
                    "reasons": runtime_result.reasons,
                },
                workflow_id=workflow_id,
                fencing_epoch=fencing_epoch,
            )
            legacy_outcome = await self._execute_legacy_attempt(
                task=task,
                workflow_id=workflow_id,
                attempt=attempt,
                fencing_epoch=fencing_epoch,
            )
            legacy_outcome.used_fail_open = True
            legacy_outcome.subagent_runtime_result = runtime_result
            if not legacy_outcome.approved:
                merged_reasons = list(runtime_result.reasons)
                merged_reasons.extend([item for item in legacy_outcome.reasons if item not in merged_reasons])
                legacy_outcome.reasons = merged_reasons
            return legacy_outcome

        reasons = list(runtime_result.reasons) or ["subagent_runtime_failed"]
        return TaskAttemptOutcome(
            approved=False,
            reasons=reasons,
            subagent_runtime_result=runtime_result,
        )

    async def _materialize_subtask_worker_result(
        self,
        task: OptimizationTask,
        subtask: RuntimeSubTaskSpec,
    ) -> RuntimeSubTaskResult:
        return self.execution_bridge.execute_subtask(task=task, subtask=subtask)

    def _emit_task_execution_completed(
        self,
        *,
        workflow_id: str,
        task_id: str,
        attempt: int,
        runtime_mode: str,
        success: bool,
        duration_seconds: float | None,
        fencing_epoch: int,
        executor: str,
        executor_id: str = "",
        exit_code: int | None = None,
        gate_failure: str = "",
        failed_subtask_count: int | None = None,
        fail_open_recommended: bool | None = None,
    ) -> None:
        payload: Dict[str, Any] = {
            "workflow_id": workflow_id,
            "task_id": task_id,
            "attempt": attempt,
            "runtime_mode": runtime_mode,
            "executor": executor,
            "executor_id": executor_id,
            "success": bool(success),
            "duration_seconds": float(duration_seconds or 0.0),
        }
        if exit_code is not None:
            payload["exit_code"] = int(exit_code)
        if gate_failure:
            payload["gate_failure"] = gate_failure
        if failed_subtask_count is not None:
            payload["failed_subtask_count"] = int(failed_subtask_count)
        if fail_open_recommended is not None:
            payload["fail_open_recommended"] = bool(fail_open_recommended)
        self._emit(
            "TaskExecutionCompleted",
            payload,
            workflow_id=workflow_id,
            fencing_epoch=fencing_epoch,
        )

    @staticmethod
    def _sum_subtask_durations(runtime_result: SubAgentRuntimeResult) -> float:
        total = 0.0
        for item in list(runtime_result.subtask_results):
            try:
                value = float(item.duration_seconds)
            except (TypeError, ValueError):
                continue
            if value >= 0:
                total += value
        return float(total)

    def _record_subagent_gate_failure(
        self,
        *,
        gate: str,
        workflow_id: str,
        task_id: str,
        runtime_result: SubAgentRuntimeResult,
        fencing_epoch: int,
    ) -> None:
        gate_key = str(gate or "runtime").strip().lower()
        metric_map = {
            "contract": "contract_failures",
            "scaffold": "scaffold_failures",
        }
        metric_name = metric_map.get(gate_key, "runtime_failures")
        self._subagent_gate_metrics[metric_name] = self._subagent_gate_metrics.get(metric_name, 0) + 1

        self._emit(
            "SubAgentGateMetricUpdated",
            {
                "workflow_id": workflow_id,
                "task_id": task_id,
                "runtime_id": runtime_result.runtime_id,
                "gate": gate_key,
                "metric_name": metric_name,
                "metric_value": self._subagent_gate_metrics[metric_name],
                "metrics_snapshot": dict(self._subagent_gate_metrics),
            },
            workflow_id=workflow_id,
            fencing_epoch=fencing_epoch,
        )
        self._emit(
            "ReleaseGateRejected",
            {
                "workflow_id": workflow_id,
                "task_id": task_id,
                "runtime_id": runtime_result.runtime_id,
                "gate": gate_key,
                "reasons": list(runtime_result.reasons),
                "failed_subtasks": list(runtime_result.failed_subtasks),
            },
            workflow_id=workflow_id,
            fencing_epoch=fencing_epoch,
        )

    @staticmethod
    def _build_runtime_trace_id(task_id: str, attempt: int) -> str:
        return f"trace_{task_id}_{attempt}_{uuid.uuid4().hex[:8]}"

    def _task_requires_scaffold_txn(self, *, task: OptimizationTask) -> bool:
        if not bool(self.config.subagent_runtime.enforce_scaffold_txn_for_write):
            return False

        metadata = task.metadata if isinstance(task.metadata, dict) else {}
        explicit_write = metadata.get("write_intent")
        if isinstance(explicit_write, bool):
            return explicit_write

        explicit_read_only = metadata.get("read_only")
        if isinstance(explicit_read_only, bool) and explicit_read_only:
            return False

        if task.target_files:
            return True

        subtasks = metadata.get("subtasks")
        if isinstance(subtasks, list):
            for item in subtasks:
                if not isinstance(item, dict):
                    continue
                if "patches" in item:
                    return True
        return False

    def _record_subagent_attempt(self) -> None:
        attempts = int(self._subagent_fail_open_budget.get("subagent_attempt_count", 0)) + 1
        fails = int(self._subagent_fail_open_budget.get("fail_open_count", 0))
        ratio = (fails / attempts) if attempts > 0 else 0.0
        self._subagent_fail_open_budget["subagent_attempt_count"] = attempts
        self._subagent_fail_open_budget["fail_open_ratio"] = float(ratio)

    def _record_fail_open_and_maybe_degrade(
        self,
        *,
        workflow_id: str,
        task_id: str,
        attempt: int,
        runtime_id: str,
        gate_failure: str,
        reasons: List[str],
        fencing_epoch: int,
    ) -> None:
        fails = int(self._subagent_fail_open_budget.get("fail_open_count", 0)) + 1
        attempts = max(1, int(self._subagent_fail_open_budget.get("subagent_attempt_count", 0)))
        ratio = fails / attempts
        budget = max(0.0, min(1.0, float(self.config.subagent_runtime.fail_open_budget_ratio)))
        self._subagent_fail_open_budget["fail_open_count"] = fails
        self._subagent_fail_open_budget["fail_open_ratio"] = float(ratio)
        self._subagent_fail_open_budget["budget_ratio"] = float(budget)

        self._emit(
            "SubAgentFailOpenBudgetUpdated",
            {
                "workflow_id": workflow_id,
                "task_id": task_id,
                "attempt": attempt,
                "runtime_id": runtime_id,
                "gate_failure": gate_failure,
                "fail_open_count": fails,
                "subagent_attempt_count": attempts,
                "fail_open_ratio": ratio,
                "budget_ratio": budget,
            },
            workflow_id=workflow_id,
            fencing_epoch=fencing_epoch,
        )

        if bool(self._subagent_fail_open_budget.get("degraded_to_legacy")):
            return
        if ratio <= budget:
            return

        self._subagent_fail_open_budget["degraded_to_legacy"] = True
        self._subagent_fail_open_budget["degrade_reason"] = "fail_open_budget_exhausted"
        self._emit(
            "SubAgentRuntimeAutoDegraded",
            {
                "workflow_id": workflow_id,
                "task_id": task_id,
                "attempt": attempt,
                "runtime_id": runtime_id,
                "reason": "fail_open_budget_exhausted",
                "fail_open_count": fails,
                "subagent_attempt_count": attempts,
                "fail_open_ratio": ratio,
                "budget_ratio": budget,
            },
            workflow_id=workflow_id,
            fencing_epoch=fencing_epoch,
        )
        self._emit(
            "ReleaseGateRejected",
            {
                "workflow_id": workflow_id,
                "task_id": task_id,
                "gate": "fail_open_budget",
                "attempt": attempt,
                "runtime_mode": "subagent",
                "reasons": ["fail_open_budget_exhausted"],
                "fail_open_ratio": ratio,
                "budget_ratio": budget,
            },
            workflow_id=workflow_id,
            fencing_epoch=fencing_epoch,
        )
        try:
            self.alert_event_producer.emit_alert(
                alert_key="subagent_fail_open_budget_exhausted",
                severity="critical",
                topic="alert.runtime",
                event_type="AlertRaised",
                payload={
                    "workflow_id": workflow_id,
                    "task_id": task_id,
                    "attempt": attempt,
                    "runtime_id": runtime_id,
                    "gate_failure": gate_failure,
                    "reasons": list(reasons),
                    "fail_open_count": fails,
                    "subagent_attempt_count": attempts,
                    "fail_open_ratio": ratio,
                    "budget_ratio": budget,
                    "action": "degrade_to_legacy",
                },
            )
        except Exception:
            pass

    def _resolve_runtime_mode(self, *, task: OptimizationTask) -> tuple[str, Dict[str, Any]]:
        metadata = task.metadata if isinstance(task.metadata, dict) else {}
        enforce_write_path = self._task_requires_scaffold_txn(task=task)
        rollout_percent = max(0, min(100, int(self.config.subagent_runtime.rollout_percent)))
        if bool(self.config.subagent_runtime.disable_legacy_cli_fallback):
            return "subagent", {
                "reason": "legacy_cli_layer_disabled",
                "rollout_percent": rollout_percent,
                "write_path_enforced": enforce_write_path,
                "subagent_enabled": bool(self.config.subagent_runtime.enabled),
            }
        if bool(self._subagent_fail_open_budget.get("degraded_to_legacy")) and not enforce_write_path:
            return "legacy", {
                "reason": "fail_open_budget_exhausted_auto_degrade",
                "rollout_percent": 0,
                "fail_open_ratio": float(self._subagent_fail_open_budget.get("fail_open_ratio", 0.0)),
                "budget_ratio": float(self._subagent_fail_open_budget.get("budget_ratio", 0.0)),
            }
        forced_mode = str(
            metadata.get("runtime_mode")
            or metadata.get("force_runtime_mode")
            or metadata.get("execution_mode")
            or ""
        ).strip().lower()

        if forced_mode in {"subagent", "legacy"}:
            if forced_mode == "legacy" and enforce_write_path and bool(self.config.subagent_runtime.enabled):
                return "subagent", {
                    "reason": "write_path_enforced",
                    "requested_mode": "legacy",
                    "rollout_percent": self.config.subagent_runtime.rollout_percent,
                    "write_path_enforced": True,
                }
            return forced_mode, {
                "reason": "task_forced_mode",
                "rollout_percent": self.config.subagent_runtime.rollout_percent,
                "write_path_enforced": enforce_write_path,
            }

        if not bool(self.config.subagent_runtime.enabled):
            reason = "write_path_subagent_disabled" if enforce_write_path else "subagent_disabled"
            return "legacy", {"reason": reason, "rollout_percent": 0, "write_path_enforced": enforce_write_path}

        if enforce_write_path:
            return "subagent", {
                "reason": "write_path_enforced",
                "rollout_percent": rollout_percent,
                "write_path_enforced": True,
            }

        if rollout_percent <= 0:
            return "legacy", {"reason": "rollout_zero", "rollout_percent": rollout_percent}
        if rollout_percent >= 100:
            return "subagent", {"reason": "rollout_full", "rollout_percent": rollout_percent}

        token = f"{task.task_id}:{str(task.instruction or '').strip()}"
        bucket = int(hashlib.sha256(token.encode("utf-8")).hexdigest()[:8], 16) % 100
        if bucket < rollout_percent:
            return "subagent", {"reason": "rollout_bucket_hit", "rollout_percent": rollout_percent, "rollout_bucket": bucket}
        return "legacy", {"reason": "rollout_bucket_miss", "rollout_percent": rollout_percent, "rollout_bucket": bucket}

    def _evaluate_write_path_gate(
        self,
        *,
        task: OptimizationTask,
        workflow_id: str,
        attempt: int,
        runtime_mode: str,
        rollout_context: Dict[str, Any],
        fencing_epoch: int,
    ) -> TaskAttemptOutcome | None:
        if runtime_mode == "subagent":
            return None
        if not self._task_requires_scaffold_txn(task=task):
            return None

        reason = str(rollout_context.get("reason") or "legacy_runtime")
        reasons = ["write_path:scaffold_txn_required", f"write_path:{reason}"]
        self._emit(
            "ReleaseGateRejected",
            {
                "workflow_id": workflow_id,
                "task_id": task.task_id,
                "gate": "write_path",
                "attempt": attempt,
                "runtime_mode": runtime_mode,
                "decision_reason": reason,
                "reasons": reasons,
            },
            workflow_id=workflow_id,
            fencing_epoch=fencing_epoch,
        )
        return TaskAttemptOutcome(approved=False, reasons=reasons)

    async def _attempt_verification_fallback(
        self,
        task: OptimizationTask,
        workflow_id: str,
        dispatch_result: DispatchResult,
        reasons: list[str],
        *,
        fencing_epoch: int,
    ) -> None:
        self._ensure_active_epoch(fencing_epoch)
        if not self.config.verification_fallback.enable_codex_mcp:
            self._emit(
                "VerificationFallbackSkipped",
                {"workflow_id": workflow_id, "task_id": task.task_id, "reason": "disabled"},
                workflow_id=workflow_id,
                fencing_epoch=fencing_epoch,
            )
            return

        self._emit(
            "VerificationDegradedToCodexMCP",
            {
                "workflow_id": workflow_id,
                "task_id": task.task_id,
                "from_cli": dispatch_result.selected_cli,
                "reasons": reasons,
            },
            workflow_id=workflow_id,
            enqueue_outbox=True,
            fencing_epoch=fencing_epoch,
        )

        prompt = self._build_mcp_prompt(task, dispatch_result, reasons, workflow_id=workflow_id)
        response = await self.fallback_verifier.ask(prompt, context={"task_id": task.task_id, "workflow_id": workflow_id})

        status = str(response.get("status", "unknown"))
        if status == "error":
            self.workflow_store.transition(
                workflow_id,
                "FailedHard",
                reason="codex_mcp_fallback_failed",
                payload={"response": response},
            )
        else:
            self.workflow_store.transition(
                workflow_id,
                "Reworking",
                reason="codex_mcp_suggestion_available",
                payload={"response": response},
            )

        self._emit(
            "VerificationFallbackResult",
            {
                "workflow_id": workflow_id,
                "task_id": task.task_id,
                "service_name": self.fallback_verifier.service_name,
                "tool_name": self.fallback_verifier.tool_name,
                "status": status,
                "response": response,
            },
            workflow_id=workflow_id,
            enqueue_outbox=True,
            fencing_epoch=fencing_epoch,
        )

    async def _outbox_dispatch_loop(self) -> None:
        consumer = self.config.outbox_dispatch.consumer_name
        poll_seconds = max(1, self.config.outbox_dispatch.poll_interval_seconds)

        while not self._stop_event.is_set():
            if not self._is_leader:
                await self._sleep_or_stop(poll_seconds)
                continue

            try:
                active_epoch = self._ensure_active_epoch(self._fencing_epoch if self._fencing_epoch > 0 else None)
                pending = self.workflow_store.read_pending_outbox(limit=self.config.outbox_dispatch.batch_size)
                if not pending:
                    await self._sleep_or_stop(poll_seconds)
                    continue

                for event in pending:
                    await self._dispatch_single_outbox_event(event, consumer=consumer, fencing_epoch=active_epoch)
            except LeaseLostError:
                await self._sleep_or_stop(poll_seconds)
            except Exception as exc:
                self.logger.exception("[SystemAgent] outbox dispatch error: %s", exc)
                self._emit("OutboxDispatchLoopError", {"error": str(exc)})
                await self._sleep_or_stop(poll_seconds)

    async def _lease_heartbeat_loop(self) -> None:
        while not self._stop_event.is_set():
            lease_status = self.workflow_store.try_acquire_or_renew_lease(
                lease_name=self.config.lease.lease_name,
                owner_id=self.instance_id,
                ttl_seconds=self.config.lease.ttl_seconds,
            )

            if lease_status.is_owner:
                became_leader = not self._is_leader or self._fencing_epoch != lease_status.fencing_epoch
                self._is_leader = True
                self._fencing_epoch = lease_status.fencing_epoch
                if became_leader:
                    self._emit(
                        "LeaseAcquired",
                        {
                            "instance_id": self.instance_id,
                            "lease_name": lease_status.lease_name,
                            "fencing_epoch": lease_status.fencing_epoch,
                            "lease_expire_at": lease_status.lease_expire_at,
                        },
                        fencing_epoch=lease_status.fencing_epoch,
                    )
                await self._sleep_or_stop(self.config.lease.renew_interval_seconds)
                continue

            if self._is_leader:
                self._emit(
                    "LeaseLost",
                    {
                        "instance_id": self.instance_id,
                        "lease_name": lease_status.lease_name,
                        "current_owner": lease_status.owner_id,
                        "current_fencing_epoch": lease_status.fencing_epoch,
                    },
                    fencing_epoch=self._fencing_epoch if self._fencing_epoch > 0 else None,
                )
            self._is_leader = False
            await self._sleep_or_stop(self.config.lease.standby_poll_interval_seconds)

    async def _dispatch_single_outbox_event(
        self,
        event: Dict[str, Any],
        *,
        consumer: str,
        fencing_epoch: int,
    ) -> None:
        outbox_id = int(event.get("outbox_id", 0))
        message_id = str(outbox_id)
        workflow_id = str(event.get("workflow_id", ""))

        if outbox_id <= 0:
            return

        if self.workflow_store.is_inbox_processed(consumer, message_id):
            self.workflow_store.mark_outbox_dispatched(outbox_id)
            self._emit(
                "OutboxDedupHit",
                {
                    "outbox_id": outbox_id,
                    "consumer": consumer,
                    "event_type": event.get("event_type"),
                    "workflow_id": workflow_id,
                },
                workflow_id=workflow_id or None,
                fencing_epoch=fencing_epoch,
            )
            return

        try:
            bridged_payload = build_brainstem_bridge_payload(event, consumer=consumer)
            self._emit(
                BRIDGED_EVENT_TYPE,
                bridged_payload,
                workflow_id=workflow_id or None,
                fencing_epoch=fencing_epoch,
            )
            await self._handle_outbox_business_event(event, fencing_epoch=fencing_epoch)
            self.workflow_store.complete_outbox_for_consumer(outbox_id, consumer, message_id)
            self._emit(
                "OutboxDispatched",
                {
                    "outbox_id": outbox_id,
                    "consumer": consumer,
                    "event_type": event.get("event_type"),
                    "workflow_id": workflow_id,
                },
                workflow_id=workflow_id or None,
                fencing_epoch=fencing_epoch,
            )
            return
        except Exception as exc:
            retry_state = self.workflow_store.record_outbox_attempt_failure(outbox_id, str(exc))
            event_name = "OutboxDispatchDeadLetter" if bool(retry_state.get("exhausted")) else "OutboxDispatchRetryScheduled"
            self._emit(
                event_name,
                {
                    "outbox_id": outbox_id,
                    "consumer": consumer,
                    "event_type": event.get("event_type"),
                    "workflow_id": workflow_id,
                    "error": str(exc),
                    "attempts": retry_state.get("attempts"),
                    "max_attempts": retry_state.get("max_attempts"),
                    "next_retry_at": retry_state.get("next_retry_at"),
                },
                workflow_id=workflow_id or None,
                fencing_epoch=fencing_epoch,
            )

    async def _handle_outbox_business_event(self, event: Dict[str, Any], *, fencing_epoch: int) -> None:
        event_type = str(event.get("event_type", ""))
        if event_type == "TaskApproved":
            await self._handle_task_approved_event(event, fencing_epoch=fencing_epoch)
            return

        self._emit(
            "OutboxNoop",
            {"event_type": event_type, "outbox_id": event.get("outbox_id")},
            workflow_id=str(event.get("workflow_id") or "") or None,
            fencing_epoch=fencing_epoch,
        )

    async def _handle_task_approved_event(self, event: Dict[str, Any], *, fencing_epoch: int) -> None:
        self._ensure_active_epoch(fencing_epoch)
        payload = event.get("payload", {})
        if not isinstance(payload, dict):
            payload = {}

        workflow_id = str(event.get("workflow_id") or payload.get("workflow_id") or "")
        if not workflow_id:
            raise ValueError("TaskApproved outbox event missing workflow_id")
        task_id = str(payload.get("task_id") or "")

        self.workflow_store.transition(
            workflow_id,
            "CanaryRunning",
            reason="canary_started",
            payload={"source_outbox_id": event.get("outbox_id")},
        )
        canary_command_id = self.workflow_store.create_command(
            workflow_id=workflow_id,
            step_name="release_canary",
            command_type="deploy_canary",
            idempotency_key=f"{workflow_id}:release_canary:{event.get('outbox_id')}",
            attempt=1,
            max_attempt=1,
            fencing_epoch=fencing_epoch,
        )

        observations = payload.get("canary_observations")
        decision = self.release_controller.evaluate_canary(observations if isinstance(observations, list) else None)
        decision_payload = {
            "outcome": decision.outcome,
            "reason": decision.reason,
            "evaluated_windows": decision.evaluated_windows,
            "policy_snapshot": decision.policy_snapshot,
            "threshold_snapshot": decision.threshold_snapshot,
            "stats": decision.stats,
            "trigger_window_index": decision.trigger_window_index,
        }

        if decision.outcome == "promote":
            self.workflow_store.update_command(canary_command_id, status="succeeded")
            self.workflow_store.transition(workflow_id, "Promoted", reason="canary_pass", payload=decision_payload)
            self._emit(
                "ChangePromoted",
                {
                    "workflow_id": workflow_id,
                    "task_id": task_id,
                    "decision": decision_payload,
                },
                workflow_id=workflow_id,
                enqueue_outbox=True,
                fencing_epoch=fencing_epoch,
            )
            return

        if decision.outcome == "rollback":
            self.workflow_store.update_command(canary_command_id, status="failed", last_error=decision.reason)
            self.workflow_store.transition(workflow_id, "RolledBack", reason="canary_fail", payload=decision_payload)

            rollback_result = {"enabled": self.config.release.auto_rollback_enabled, "status": "skipped", "details": ""}
            if self.config.release.auto_rollback_enabled:
                rollback_command_id = self.workflow_store.create_command(
                    workflow_id=workflow_id,
                    step_name="rollback_release",
                    command_type="rollback_release",
                    idempotency_key=f"{workflow_id}:rollback_release:{event.get('outbox_id')}",
                    attempt=1,
                    max_attempt=1,
                    fencing_epoch=fencing_epoch,
                )
                ok, details = self.release_controller.execute_rollback(self.config.release.rollback_command)
                rollback_result["status"] = "succeeded" if ok else "failed"
                rollback_result["details"] = details
                self.workflow_store.update_command(
                    rollback_command_id,
                    status="succeeded" if ok else "failed",
                    last_error="" if ok else details,
                )
                if not ok:
                    self.workflow_store.transition(
                        workflow_id,
                        "FailedHard",
                        reason="rollback_command_failed",
                        payload={"rollback_details": details},
                    )

            self._emit(
                "ReleaseRolledBack",
                {
                    "workflow_id": workflow_id,
                    "task_id": task_id,
                    "decision": decision_payload,
                    "rollback_result": rollback_result,
                },
                workflow_id=workflow_id,
                enqueue_outbox=True,
                fencing_epoch=fencing_epoch,
            )
            self._emit(
                "IncidentOpened",
                {
                    "workflow_id": workflow_id,
                    "task_id": task_id,
                    "trigger": "automatic_canary_rollback",
                    "decision_reason": decision.reason,
                },
                workflow_id=workflow_id,
                enqueue_outbox=True,
                fencing_epoch=fencing_epoch,
            )
            return

        self.workflow_store.update_command(canary_command_id, status="succeeded")
        self._emit(
            "CanaryObserving",
            {"workflow_id": workflow_id, "task_id": task_id, "decision": decision_payload},
            workflow_id=workflow_id,
            fencing_epoch=fencing_epoch,
        )

    def _build_mcp_prompt(
        self,
        task: OptimizationTask,
        dispatch_result: DispatchResult,
        reasons: list[str],
        workflow_id: str,
    ) -> str:
        payload = {
            "workflow_id": workflow_id,
            "task_id": task.task_id,
            "instruction": task.instruction,
            "selected_cli": dispatch_result.selected_cli,
            "exit_code": dispatch_result.result.exit_code,
            "stderr": dispatch_result.result.stderr,
            "changed_files": dispatch_result.result.files_changed,
            "reasons": reasons,
        }
        return (
            "You are in verification fallback mode. "
            "Analyze the failed autonomous coding task and provide actionable fixes as JSON.\n"
            f"{json.dumps(payload, ensure_ascii=False)}"
        )

    async def _wait_next_cycle(self) -> None:
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=self.config.cycle_interval_seconds)
        except asyncio.TimeoutError:
            return

    async def _sleep_or_stop(self, seconds: float) -> None:
        timeout = max(0.0, float(seconds))
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return

    def _ensure_active_epoch(self, expected_epoch: int | None = None) -> int:
        if not self.config.lease.enabled:
            if self._fencing_epoch <= 0:
                self._fencing_epoch = 1
            return self._fencing_epoch

        if not self._is_leader and not self._running:
            # Supports direct smoke call run_cycle() without start().
            status = self.workflow_store.try_acquire_or_renew_lease(
                lease_name=self.config.lease.lease_name,
                owner_id=self.instance_id,
                ttl_seconds=self.config.lease.ttl_seconds,
            )
            if status.is_owner:
                self._is_leader = True
                self._fencing_epoch = status.fencing_epoch

        if not self._is_leader:
            raise LeaseLostError("instance is not lease owner")

        epoch = self._fencing_epoch
        if expected_epoch is not None and expected_epoch != epoch:
            raise LeaseLostError(f"fencing epoch changed: expected={expected_epoch}, current={epoch}")

        if not self.workflow_store.is_lease_owner(
            lease_name=self.config.lease.lease_name,
            owner_id=self.instance_id,
            fencing_epoch=epoch,
        ):
            self._is_leader = False
            raise LeaseLostError("lease ownership validation failed")

        return epoch

    def _emit(
        self,
        event_type: str,
        payload: Dict[str, Any],
        *,
        workflow_id: str | None = None,
        enqueue_outbox: bool = False,
        fencing_epoch: int | None = None,
    ) -> None:
        event_payload = dict(payload)
        if workflow_id and "workflow_id" not in event_payload:
            event_payload["workflow_id"] = workflow_id
        epoch = fencing_epoch or (self._fencing_epoch if self._fencing_epoch > 0 else None)
        if epoch is not None and "fencing_epoch" not in event_payload:
            event_payload["fencing_epoch"] = epoch
        self.event_store.emit(event_type, event_payload)

        if enqueue_outbox and workflow_id:
            if epoch is not None and self.config.lease.enabled:
                try:
                    self._ensure_active_epoch(epoch)
                except LeaseLostError as exc:
                    self.logger.warning("[SystemAgent] skip outbox enqueue due to lease loss: %s", exc)
                    return
            self.workflow_store.enqueue_outbox(workflow_id, event_type, event_payload)
