"""System Agent skeleton implementation."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict

from autonomous.dispatcher import DispatchResult, Dispatcher
from autonomous.event_log import EventStore
from autonomous.evaluator import Evaluator
from autonomous.planner import Planner
from autonomous.release import CanaryThresholds, ReleaseController
from autonomous.sensor import Sensor
from autonomous.state import WorkflowStore
from autonomous.tools.codex_mcp_adapter import CodexMcpVerifier
from autonomous.types import OptimizationTask


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
        )


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
            idempotency_key = f"{task.task_id}:cli_execute:{attempt}"
            command_id = self.workflow_store.create_command(
                workflow_id=workflow_id,
                step_name="implement_verify",
                command_type="cli_execute",
                idempotency_key=idempotency_key,
                attempt=attempt,
                max_attempt=max_attempt,
                fencing_epoch=fencing_epoch,
            )

            dispatch_result = await self.dispatcher.dispatch(task)
            self._ensure_active_epoch(fencing_epoch)

            last_dispatch = dispatch_result
            self._emit(
                "CliExecutionCompleted",
                {
                    "workflow_id": workflow_id,
                    "task_id": task.task_id,
                    "attempt": attempt,
                    "cli": dispatch_result.selected_cli,
                    "success": dispatch_result.result.success,
                    "exit_code": dispatch_result.result.exit_code,
                    "duration_seconds": dispatch_result.result.duration_seconds,
                },
                workflow_id=workflow_id,
                fencing_epoch=fencing_epoch,
            )

            self.workflow_store.transition(workflow_id, "Verifying", reason="verification_started", payload={"attempt": attempt})
            report = self.evaluator.evaluate(task, dispatch_result.result)

            if report.approved:
                self.workflow_store.update_command(command_id, status="succeeded")
                self.workflow_store.transition(
                    workflow_id,
                    "ReleaseCandidate",
                    reason="checks_passed",
                    payload={"attempt": attempt},
                )
                self._emit(
                    "TaskApproved",
                    {"workflow_id": workflow_id, "task_id": task.task_id, "attempt": attempt},
                    workflow_id=workflow_id,
                    enqueue_outbox=True,
                    fencing_epoch=fencing_epoch,
                )
                return

            last_reasons = list(report.reasons)
            self.workflow_store.update_command(command_id, status="failed", last_error="; ".join(last_reasons))
            self._emit(
                "TaskRejected",
                {
                    "workflow_id": workflow_id,
                    "task_id": task.task_id,
                    "attempt": attempt,
                    "reasons": last_reasons,
                },
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
