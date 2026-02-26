from __future__ import annotations

import asyncio
import shutil
import uuid
from pathlib import Path

from autonomous.system_agent import SystemAgent
from autonomous.tools.subagent_runtime import SubAgentRuntimeResult
from autonomous.types import OptimizationTask


def _write_policy(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """
gates:
  deploy:
    canary_window_min: 15
    min_sample_count: 200
    healthy_windows_for_promotion: 3
    bad_windows_for_rollback: 2
""".strip(),
        encoding="utf-8",
    )


def _make_case_root(prefix: str) -> Path:
    root = Path("scratch") / prefix / uuid.uuid4().hex[:12]
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_case_root(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


def test_resolve_runtime_mode_forced_legacy_is_overridden_when_cli_layer_disabled() -> None:
    case_root = _make_case_root("test_system_agent_execution_bridge_cutover")
    try:
        repo = case_root / "repo"
        repo.mkdir(parents=True, exist_ok=True)
        _write_policy(repo / "policy" / "gate_policy.yaml")

        agent = SystemAgent(
            config={
                "enabled": False,
                "subagent_runtime": {
                    "enabled": True,
                    "rollout_percent": 0,
                    "disable_legacy_cli_fallback": True,
                },
                "release": {
                    "enabled": True,
                    "gate_policy_path": "policy/gate_policy.yaml",
                    "auto_rollback_enabled": False,
                },
            },
            repo_dir=str(repo),
        )

        mode, context = agent._resolve_runtime_mode(
            task=OptimizationTask(
                task_id="task-bridge-runtime-mode",
                instruction="force legacy",
                metadata={"runtime_mode": "legacy"},
            )
        )

        assert mode == "subagent"
        assert context["reason"] == "legacy_cli_layer_disabled"
    finally:
        _cleanup_case_root(case_root)


def test_fail_open_does_not_fallback_to_cli_when_cli_layer_disabled() -> None:
    case_root = _make_case_root("test_system_agent_execution_bridge_cutover")
    try:
        repo = case_root / "repo"
        repo.mkdir(parents=True, exist_ok=True)
        _write_policy(repo / "policy" / "gate_policy.yaml")

        agent = SystemAgent(
            config={
                "enabled": False,
                "cli_tools": {"max_retries": 0},
                "subagent_runtime": {
                    "enabled": True,
                    "fail_open": True,
                    "disable_legacy_cli_fallback": True,
                    "allow_legacy_fail_open_for_write": True,
                },
                "release": {
                    "enabled": True,
                    "gate_policy_path": "policy/gate_policy.yaml",
                    "auto_rollback_enabled": False,
                },
            },
            repo_dir=str(repo),
        )

        events: list[tuple[str, dict, dict]] = []

        def _capture(event_type: str, payload: dict, **kwargs) -> None:
            events.append((event_type, dict(payload), dict(kwargs)))

        agent._emit = _capture  # type: ignore[method-assign]

        async def _runtime_fail_open(**kwargs):  # type: ignore[no-untyped-def]
            return SubAgentRuntimeResult(
                runtime_id="sar-fail-open",
                workflow_id=str(kwargs.get("workflow_id") or "wf"),
                task_id=str(kwargs.get("task").task_id),
                trace_id=str(kwargs.get("trace_id") or "trace"),
                session_id=str(kwargs.get("session_id") or "sess"),
                success=False,
                approved=False,
                gate_failure="scaffold",
                reasons=["scaffold_apply_failed"],
                fail_open_recommended=True,
            )

        async def _dispatch_should_not_run(_task):  # type: ignore[no-untyped-def]
            raise AssertionError("legacy cli dispatch should not be called when cli layer disabled")

        agent.subagent_runtime.run = _runtime_fail_open  # type: ignore[method-assign]
        agent.dispatcher.dispatch = _dispatch_should_not_run  # type: ignore[method-assign]

        task = OptimizationTask(
            task_id="task-bridge-no-cli-fallback",
            instruction="runtime should fail closed",
            metadata={
                "runtime_mode": "legacy",
                "write_intent": True,
            },
        )

        asyncio.run(agent._run_task(task, fencing_epoch=1))

        event_types = [event_type for event_type, _, _ in events]
        assert "SubAgentRuntimeFailOpenBlocked" in event_types
        assert "ReleaseGateRejected" in event_types
        assert any(
            event_type == "TaskExecutionCompleted" and str(payload.get("runtime_mode") or "") == "subagent"
            for event_type, payload, _ in events
        )
        assert all(
            not (
                event_type == "TaskExecutionCompleted"
                and str(payload.get("runtime_mode") or "") == "legacy"
            )
            for event_type, payload, _ in events
        )
        assert "TaskApproved" not in event_types
    finally:
        _cleanup_case_root(case_root)
