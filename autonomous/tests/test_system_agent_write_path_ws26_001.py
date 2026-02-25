from __future__ import annotations

import asyncio
import shutil
import uuid
from pathlib import Path

from autonomous.dispatcher import DispatchResult
from autonomous.system_agent import SystemAgent
from autonomous.tools.cli_adapter import CliTaskResult
from autonomous.types import EvaluationReport, OptimizationTask


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


def _build_dispatch_result(task_id: str) -> DispatchResult:
    return DispatchResult(
        selected_cli="codex",
        result=CliTaskResult(
            task_id=task_id,
            cli_name="codex",
            exit_code=0,
            stdout="ok",
            stderr="",
            files_changed=[],
            duration_seconds=0.1,
            success=True,
            execution_snapshots=[],
        ),
    )


def test_write_task_forced_legacy_is_overridden_to_subagent_when_enforced() -> None:
    case_root = _make_case_root("test_system_agent_write_path_ws26_001")
    try:
        repo = case_root / "repo"
        repo.mkdir(parents=True, exist_ok=True)
        _write_policy(repo / "policy" / "gate_policy.yaml")
        target = repo / "service.txt"
        target.write_text("BASE", encoding="utf-8")

        agent = SystemAgent(
            config={
                "enabled": False,
                "cli_tools": {"max_retries": 0},
                "subagent_runtime": {
                    "enabled": True,
                    "rollout_percent": 0,
                    "fail_open": False,
                    "enforce_scaffold_txn_for_write": True,
                },
                "release": {"enabled": True, "gate_policy_path": "policy/gate_policy.yaml"},
            },
            repo_dir=str(repo),
        )

        events: list[tuple[str, dict, dict]] = []
        agent._emit = lambda event_type, payload, **kwargs: events.append((event_type, dict(payload), dict(kwargs)))  # type: ignore[method-assign]

        task = OptimizationTask(
            task_id="task-ws26-forced-legacy-overridden",
            instruction="write via scaffold",
            metadata={
                "runtime_mode": "legacy",
                "subtasks": [
                    {
                        "subtask_id": "backend",
                        "role": "backend",
                        "instruction": "patch file",
                        "contract_schema": {"request": {"id": "string"}},
                        "patches": [{"path": "service.txt", "content": "PATCHED"}],
                    }
                ],
            },
        )
        asyncio.run(agent._run_task(task, fencing_epoch=1))

        assert target.read_text(encoding="utf-8") == "PATCHED"
        approved = [payload for event_type, payload, _ in events if event_type == "TaskApproved"]
        assert len(approved) == 1
        assert approved[0].get("runtime_mode") == "subagent"
        decisions = [payload for event_type, payload, _ in events if event_type == "SubAgentRuntimeRolloutDecision"]
        assert decisions
        assert decisions[-1].get("decision_reason") == "write_path_enforced"
    finally:
        _cleanup_case_root(case_root)


def test_write_task_is_rejected_when_subagent_disabled_under_write_path_enforcement() -> None:
    case_root = _make_case_root("test_system_agent_write_path_ws26_001")
    try:
        repo = case_root / "repo"
        repo.mkdir(parents=True, exist_ok=True)
        _write_policy(repo / "policy" / "gate_policy.yaml")

        agent = SystemAgent(
            config={
                "enabled": False,
                "cli_tools": {"max_retries": 0},
                "subagent_runtime": {
                    "enabled": False,
                    "enforce_scaffold_txn_for_write": True,
                },
                "release": {"enabled": True, "gate_policy_path": "policy/gate_policy.yaml"},
            },
            repo_dir=str(repo),
        )

        dispatch_called = {"count": 0}

        async def _dispatch_should_not_run(task: OptimizationTask) -> DispatchResult:
            dispatch_called["count"] += 1
            return _build_dispatch_result(task.task_id)

        agent.dispatcher.dispatch = _dispatch_should_not_run  # type: ignore[method-assign]
        agent.evaluator.evaluate = lambda task, result: EvaluationReport(approved=True)  # type: ignore[method-assign]

        events: list[tuple[str, dict, dict]] = []
        agent._emit = lambda event_type, payload, **kwargs: events.append((event_type, dict(payload), dict(kwargs)))  # type: ignore[method-assign]

        task = OptimizationTask(
            task_id="task-ws26-write-subagent-disabled",
            instruction="write task should be gated",
            target_files=["service.txt"],
            metadata={"write_intent": True},
        )
        asyncio.run(agent._run_task(task, fencing_epoch=1))

        assert dispatch_called["count"] == 0
        assert any(event_type == "TaskRejected" for event_type, _, _ in events)
        write_gate_events = [
            payload for event_type, payload, _ in events if event_type == "ReleaseGateRejected" and payload.get("gate") == "write_path"
        ]
        assert write_gate_events
        assert any("write_path:write_path_subagent_disabled" in " ".join(payload.get("reasons", [])) for payload in write_gate_events)
        assert not any(event_type == "TaskApproved" for event_type, _, _ in events)
    finally:
        _cleanup_case_root(case_root)


def test_write_task_fail_open_is_blocked_by_default() -> None:
    case_root = _make_case_root("test_system_agent_write_path_ws26_001")
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
                    "enforce_scaffold_txn_for_write": True,
                    "allow_legacy_fail_open_for_write": False,
                },
                "release": {"enabled": True, "gate_policy_path": "policy/gate_policy.yaml"},
            },
            repo_dir=str(repo),
        )

        dispatch_called = {"count": 0}

        async def _dispatch_should_not_run(task: OptimizationTask) -> DispatchResult:
            dispatch_called["count"] += 1
            return _build_dispatch_result(task.task_id)

        agent.dispatcher.dispatch = _dispatch_should_not_run  # type: ignore[method-assign]
        agent.evaluator.evaluate = lambda task, result: EvaluationReport(approved=True)  # type: ignore[method-assign]

        events: list[tuple[str, dict, dict]] = []
        agent._emit = lambda event_type, payload, **kwargs: events.append((event_type, dict(payload), dict(kwargs)))  # type: ignore[method-assign]

        task = OptimizationTask(
            task_id="task-ws26-fail-open-blocked",
            instruction="missing patch intent",
            metadata={
                "subtasks": [
                    {
                        "subtask_id": "backend",
                        "role": "backend",
                        "instruction": "no patch",
                        "contract_schema": {"request": {"id": "string"}},
                        "patches": [],
                    }
                ]
            },
        )
        asyncio.run(agent._run_task(task, fencing_epoch=1))

        assert dispatch_called["count"] == 0
        assert any(event_type == "SubAgentRuntimeFailOpenBlocked" for event_type, _, _ in events)
        assert not any(event_type == "SubAgentRuntimeFailOpen" for event_type, _, _ in events)
        assert any(event_type == "TaskRejected" for event_type, _, _ in events)
        assert not any(event_type == "TaskApproved" for event_type, _, _ in events)
    finally:
        _cleanup_case_root(case_root)


def test_write_task_fail_open_can_fallback_when_explicitly_enabled() -> None:
    case_root = _make_case_root("test_system_agent_write_path_ws26_001")
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
                    "enforce_scaffold_txn_for_write": True,
                    "allow_legacy_fail_open_for_write": True,
                },
                "release": {"enabled": True, "gate_policy_path": "policy/gate_policy.yaml"},
            },
            repo_dir=str(repo),
        )

        dispatch_called = {"count": 0}

        async def _dispatch_ok(task: OptimizationTask) -> DispatchResult:
            dispatch_called["count"] += 1
            return _build_dispatch_result(task.task_id)

        agent.dispatcher.dispatch = _dispatch_ok  # type: ignore[method-assign]
        agent.evaluator.evaluate = lambda task, result: EvaluationReport(approved=True)  # type: ignore[method-assign]

        events: list[tuple[str, dict, dict]] = []
        agent._emit = lambda event_type, payload, **kwargs: events.append((event_type, dict(payload), dict(kwargs)))  # type: ignore[method-assign]

        task = OptimizationTask(
            task_id="task-ws26-fail-open-allowed",
            instruction="missing patch intent",
            metadata={
                "subtasks": [
                    {
                        "subtask_id": "backend",
                        "role": "backend",
                        "instruction": "no patch",
                        "contract_schema": {"request": {"id": "string"}},
                        "patches": [],
                    }
                ]
            },
        )
        asyncio.run(agent._run_task(task, fencing_epoch=1))

        assert dispatch_called["count"] == 1
        assert any(event_type == "SubAgentRuntimeFailOpen" for event_type, _, _ in events)
        assert not any(event_type == "SubAgentRuntimeFailOpenBlocked" for event_type, _, _ in events)
        assert any(event_type == "TaskApproved" for event_type, _, _ in events)
    finally:
        _cleanup_case_root(case_root)
