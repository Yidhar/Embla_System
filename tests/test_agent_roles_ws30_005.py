"""Unit tests for Phase 2 — Agent Roles + Router Integration."""

from __future__ import annotations

import asyncio

import pytest

from agents.router_engine import RouterDecision
from agents.runtime.agent_session import AgentSessionStore, AgentStatus
from agents.runtime.mailbox import AgentMailbox
from agents.runtime.task_board import TaskBoardEngine, TaskItem, TaskStatus


# ── Fixtures ───────────────────────────────────────────────────

@pytest.fixture
def store():
    s = AgentSessionStore(db_path=":memory:")
    yield s
    s.close()


@pytest.fixture
def mailbox():
    m = AgentMailbox(db_path=":memory:")
    yield m
    m.close()


@pytest.fixture
def task_board_engine(tmp_path):
    e = TaskBoardEngine(
        boards_dir=str(tmp_path / "boards"),
        db_path=str(tmp_path / "tb.db"),
    )
    yield e
    e.close()


def _mock_verification_report(*, summary: str = "self verification complete", changed_files=None):
    return {
        "tests": {"passed": 1, "failed": 0, "errors": 0, "attempts": 1, "summary": summary},
        "lint": {"status": "passed", "errors": 0, "summary": "lint clean"},
        "diff_review": {"complete": True, "summary": summary, "missing_items": []},
        "changed_files": list(changed_files or ["auth.py"]),
        "risks": [],
    }


def _mock_review_result(*, verdict: str = "approve", summary: str = "review approved"):
    return {
        "verdict": verdict,
        "requirement_alignment": [
            {"requirement": "task requirements implemented", "status": "passed", "details": summary},
        ],
        "code_quality": {"status": "passed", "issues": [], "summary": summary},
        "regression_risk": {"level": "low", "summary": "no obvious regression risk"},
        "test_coverage": {"status": "passed", "summary": summary, "missing_cases": []},
        "issues": [],
        "suggestions": [],
        "summary": summary,
    }


def _mock_child_completion_response(tools, *, dev_content: str = "child work complete", review_summary: str = "review approved"):
    tool_names = {str(item.get("name") or "").strip() for item in tools if isinstance(item, dict)}
    if {"memory_read", "memory_grep", "memory_tag", "memory_deprecate"} & tool_names:
        return {
            "content": "",
            "tool_calls": [
                {
                    "id": "review_done_1",
                    "name": "report_to_parent",
                    "arguments": {
                        "type": "completed",
                        "content": review_summary,
                        "review_result": _mock_review_result(summary=review_summary),
                    },
                }
            ],
        }
    return {
        "content": "",
        "tool_calls": [
            {
                "id": "dev_done_1",
                "name": "report_to_parent",
                "arguments": {
                    "type": "completed",
                    "content": dev_content,
                    "verification_report": _mock_verification_report(summary=dev_content),
                },
            }
        ],
    }


def _patch_parent_tool_runtime(monkeypatch, *, execution_backend: str = "native", execution_root: str = "/workspace") -> None:
    monkeypatch.setattr(
        "agents.runtime.parent_tools.resolve_execution_runtime_metadata",
        lambda **kwargs: {
            "execution_backend_requested": execution_backend,
            "execution_backend": execution_backend,
            "execution_root": execution_root,
            "execution_profile": "default",
            "box_profile": "",
            "box_provider": "",
            "box_mount_mode": "rw",
            "box_fallback_reason": "",
        },
    )


@pytest.fixture(autouse=True)
def _default_native_parent_tool_runtime(monkeypatch):
    _patch_parent_tool_runtime(monkeypatch)


# ── Shell Agent Tests (Router Integration) ─────────────────────

class TestShellAgent:

    def test_shell_defaults(self):
        from agents.shell_agent import ShellAgent
        shell = ShellAgent()
        assert "dispatch_to_core" in shell.tool_names
        assert "memory_read" in shell.tool_names
        assert "memory_search" in shell.tool_names

    def test_shell_tool_definitions(self):
        from agents.shell_agent import ShellAgent
        shell = ShellAgent()
        defs = shell.get_tool_definitions()
        assert any(d["name"] == "dispatch_to_core" for d in defs)

    def test_shell_route_produces_router_decision(self):
        from agents.shell_agent import ShellAgent
        shell = ShellAgent()
        decision = shell.route("Fix the bug in file_ast.py", session_id="s1")
        assert isinstance(decision, RouterDecision)
        assert decision.task_type in {"development", "ops", "research", "general"}
        assert decision.delegation_intent != ""

    def test_shell_dispatch_includes_router_context(self):
        from agents.shell_agent import ShellAgent
        shell = ShellAgent()
        result = shell.dispatch_to_core(
            {"goal": "Implement REST API endpoint"},
            session_id="s1",
            risk_level="write_repo",
        )
        assert result["dispatched"] is True
        assert "router_decision" in result
        assert "tool_profile" in result
        assert "prompt_profile" in result
        assert "model_tier" in result
        assert isinstance(result["tool_profile"], list)

    def test_shell_should_dispatch(self):
        from agents.shell_agent import ShellAgent
        shell = ShellAgent()
        # Coding request → needs Core dispatch
        decision = shell.route("Fix the bug in parser.py", risk_level="write_repo")
        assert shell.should_dispatch(decision) is True

        # Read-only → Shell handles directly
        decision = shell.route("What is this project about?", risk_level="read_only")
        assert shell.should_dispatch(decision) is False

    def test_shell_system_prompt(self):
        from agents.shell_agent import ShellAgent
        shell = ShellAgent()
        prompt = shell.build_system_prompt()
        assert "dispatch_to_core" in prompt
        assert "绝对不能" in prompt
        assert "如何组织回答" in prompt

    def test_shell_loads_persona(self, tmp_path):
        from agents.shell_agent import ShellAgent, ShellAgentConfig
        persona_path = tmp_path / "persona.md"
        persona_path.write_text("I am Embla, a helpful AI assistant.", encoding="utf-8")
        config = ShellAgentConfig(persona_dna_path=str(persona_path))
        shell = ShellAgent(config=config)
        assert "Embla" in shell.persona_prompt


# ── Core Agent Tests (RouterDecision Integration) ──────────────

class TestCoreAgent:

    def test_core_decompose_with_router_decision(self, store, mailbox):
        from agents.shell_agent import ShellAgent
        from agents.core_agent import CoreAgent
        shell = ShellAgent()
        dispatch = shell.dispatch_to_core(
            {"goal": "Add REST API endpoint and write tests"},
            session_id="s1",
        )
        core = CoreAgent(store=store, mailbox=mailbox)
        result = core.decompose_goal(dispatch)
        assert "expert_assignments" in result
        assert "router_decision" in result
        assert "model_tier" in result
        assert len(result["expert_assignments"]) > 0
        # Verify router context propagated to assignments
        for assignment in result["expert_assignments"]:
            assert "model_tier" in assignment
            assert "tool_subset" in assignment

    def test_core_spawn_experts_with_router_tools(self, store, mailbox):
        from agents.shell_agent import ShellAgent
        from agents.core_agent import CoreAgent
        shell = ShellAgent()
        dispatch = shell.dispatch_to_core(
            {"goal": "Implement user auth backend and write API tests"},
        )
        core = CoreAgent(store=store, mailbox=mailbox)
        decomp = core.decompose_goal(dispatch)
        results = core.spawn_experts(decomp, core_execution_session_id="core")
        assert len(results) > 0
        assert all("agent_id" in r for r in results)
        assert all("model_tier" in r for r in results)

    def test_core_build_contract_input(self, store, mailbox):
        from agents.core_agent import CoreAgent
        core = CoreAgent(store=store, mailbox=mailbox)
        contract = core.build_contract_input(
            {"goal": "Fix bug", "context_summary": "AST parser issue"},
            session_id="s1",
        )
        assert contract.goal == "Fix bug"
        assert contract.session_id == "s1"
        assert contract.contract_stage == "seed"

    def test_core_system_prompt_with_profile(self, store, mailbox):
        from agents.core_agent import CoreAgent
        core = CoreAgent(store=store, mailbox=mailbox)
        prompt = core.build_system_prompt(prompt_profile="core_exec_dev")
        assert "能力域" in prompt
        assert "当前可用 MCP 工具摘要" in prompt

    def test_core_loads_values(self, store, mailbox, tmp_path):
        from agents.core_agent import CoreAgent, CoreAgentConfig
        values_path = tmp_path / "values.md"
        values_path.write_text("Mission: continuous self-improvement", encoding="utf-8")
        config = CoreAgentConfig(values_dna_path=str(values_path))
        core = CoreAgent(config=config, store=store, mailbox=mailbox)
        assert "self-improvement" in core.values_prompt

    def test_core_plan_execution_route_accepts_fast_track_for_trivial_single_file(self, store, mailbox):
        from agents.core_agent import CoreAgent

        core = CoreAgent(store=store, mailbox=mailbox)
        plan = core.plan_execution_route(
            {
                "goal": "修复 parser.py 的一个拼写错误",
                "complexity_hint": "trivial",
                "risk_level": "write_repo",
                "target_files": ["parser.py"],
                "estimated_changed_lines": 3,
                "tool_profile": ["read_file", "write_file"],
            }
        )

        assert plan["route"] == "fast_track"
        assert plan["fast_track_eligible"] is True
        assert plan["reason_codes"] == []
        assert "write_file" in plan["tool_subset"]

    def test_core_plan_execution_route_rejects_fast_track_for_protected_config(self, store, mailbox):
        from agents.core_agent import CoreAgent

        core = CoreAgent(store=store, mailbox=mailbox)
        plan = core.plan_execution_route(
            {
                "goal": "快速修改 config.json 并重写配置",
                "complexity_hint": "trivial",
                "risk_level": "write_repo",
                "target_files": ["config.json"],
                "estimated_changed_lines": 2,
                "tool_profile": ["read_file", "write_file"],
            }
        )

        assert plan["route"] == "standard"
        assert plan["fast_track_eligible"] is False
        assert "FAST_TRACK_PROTECTED_PATH" in plan["reason_codes"]

    def test_core_plan_execution_route_rejects_fast_track_for_prompt_dna(self, store, mailbox):
        from agents.core_agent import CoreAgent
        from agents.prompt_engine import get_immutable_prompt_protected_prefixes

        core = CoreAgent(store=store, mailbox=mailbox)
        protected_path = f"{get_immutable_prompt_protected_prefixes()[0]}shell_persona.md"
        plan = core.plan_execution_route(
            {
                "goal": "快速修改 shell persona DNA",
                "complexity_hint": "trivial",
                "risk_level": "write_repo",
                "target_files": [protected_path],
                "estimated_changed_lines": 2,
                "tool_profile": ["read_file", "write_file"],
            }
        )

        assert plan["route"] == "standard"
        assert plan["fast_track_eligible"] is False
        assert "FAST_TRACK_PROTECTED_PATH" in plan["reason_codes"]


# ── Expert Agent Tests ─────────────────────────────────────────

class TestExpertAgent:

    def test_expert_plan_tasks(self, store, mailbox, task_board_engine):
        from agents.expert_agent import ExpertAgent, ExpertAgentConfig
        expert = ExpertAgent(
            config=ExpertAgentConfig(expert_type="backend"),
            session_id="expert-1",
            store=store,
            mailbox=mailbox,
            task_board_engine=task_board_engine,
        )
        tasks = expert.plan_tasks("Implement AST parser\nAdd optimistic locking\nBuild conflict engine")
        assert len(tasks) == 3
        assert expert.board_id != ""

    def test_expert_spawn_devs(self, store, mailbox, task_board_engine):
        from agents.expert_agent import ExpertAgent, ExpertAgentConfig
        expert = ExpertAgent(
            config=ExpertAgentConfig(expert_type="backend"),
            session_id="expert-1",
            store=store,
            mailbox=mailbox,
            task_board_engine=task_board_engine,
        )
        tasks = expert.plan_tasks("Task A\nTask B")
        results = expert.spawn_devs(tasks)
        assert len(results) >= 1
        assert results[0]["task_id"] == "t-001"

    def test_expert_config_has_router_fields(self):
        from agents.expert_agent import ExpertAgentConfig
        config = ExpertAgentConfig(
            expert_type="ops",
            tool_subset=["os_bash", "read_file"],
            model_tier="secondary",
            prompt_profile="core_exec_ops",
        )
        assert config.model_tier == "secondary"
        assert config.prompt_profile == "core_exec_ops"

    def test_expert_spawn_review(self, store, mailbox, task_board_engine):
        from agents.expert_agent import ExpertAgent, ExpertAgentConfig
        expert = ExpertAgent(
            config=ExpertAgentConfig(expert_type="backend"),
            session_id="expert-1",
            store=store,
            mailbox=mailbox,
            task_board_engine=task_board_engine,
        )
        expert.plan_tasks("Something")
        result = expert.spawn_review()
        assert result.get("agent_id")
        review_child = store.get(result["agent_id"])
        assert review_child.role == "review"
        assert review_child.tool_profile == "review"


# ── Dev Agent Tests ────────────────────────────────────────────

class TestDevAgent:

    def test_dev_default_prompts_root_matches_system_prompts(self):
        from agents.dev_agent import DevAgentConfig
        from agents.prompt_engine import get_system_prompts_root

        assert DevAgentConfig().prompts_root == str(get_system_prompts_root())

    def test_dev_system_prompt(self, tmp_path):
        from agents.dev_agent import DevAgent, DevAgentConfig
        block_path = tmp_path / "prompts" / "roles" / "backend.md"
        block_path.parent.mkdir(parents=True, exist_ok=True)
        block_path.write_text("You are a backend developer.", encoding="utf-8")
        config = DevAgentConfig(
            prompt_blocks=["roles/backend.md"],
            memory_hints=["exp_20260303_001.md"],
            prompts_root=str(tmp_path / "prompts"),
        )
        dev = DevAgent(config=config)
        prompt = dev.build_system_prompt()
        assert "backend developer" in prompt
        assert "exp_20260303_001.md" in prompt
        assert "report_to_parent" in prompt
        assert "verification_report" in prompt
        assert "当前可用 MCP 工具摘要" in prompt

    def test_dev_experience_md(self):
        from agents.dev_agent import DevAgent
        dev = DevAgent()
        md = dev.build_experience_md(
            task_id="t-001",
            task_title="AST 解析器",
            outcome="success",
            problem="parse_function 无法处理装饰器",
            solution="添加 decorator 检测逻辑",
            files_changed=["file_ast.py"],
            tags=["ast", "parser"],
        )
        assert "AST 解析器" in md
        assert "#ast" in md
        assert "`file_ast.py`" in md


# ── Review Agent Tests ─────────────────────────────────────────

class TestReviewAgent:

    def test_review_completeness_pass(self, task_board_engine):
        from agents.review_agent import ReviewAgent
        task_board_engine.create_board(
            expert_type="be",
            tasks=[
                TaskItem(task_id="t-1", title="A", status=TaskStatus.DONE),
                TaskItem(task_id="t-2", title="B", status=TaskStatus.DONE),
            ],
            board_id="tb-rev-1",
        )
        review = ReviewAgent(task_board_engine=task_board_engine)
        result = review.check_completeness("tb-rev-1")
        assert result["ok"] is True

    def test_review_completeness_fail(self, task_board_engine):
        from agents.review_agent import ReviewAgent
        task_board_engine.create_board(
            expert_type="be",
            tasks=[
                TaskItem(task_id="t-1", title="A", status=TaskStatus.DONE),
                TaskItem(task_id="t-2", title="B", status=TaskStatus.PENDING),
            ],
            board_id="tb-rev-2",
        )
        review = ReviewAgent(task_board_engine=task_board_engine)
        result = review.check_completeness("tb-rev-2")
        assert result["ok"] is False
        assert "t-2" in result["incomplete_tasks"]

    def test_review_consistency(self, task_board_engine):
        from agents.review_agent import ReviewAgent
        task_board_engine.create_board(
            expert_type="be",
            tasks=[
                TaskItem(task_id="t-1", title="A", files=["a.py", "b.py"], status=TaskStatus.DONE),
            ],
            board_id="tb-rev-3",
        )
        review = ReviewAgent(task_board_engine=task_board_engine)
        r1 = review.check_consistency("tb-rev-3", ["a.py", "b.py"])
        assert r1["ok"] is True
        r2 = review.check_consistency("tb-rev-3", ["a.py", "b.py", "c.py"])
        assert r2["ok"] is False
        assert "c.py" in r2["undeclared_modifications"]

    def test_review_correctness(self, task_board_engine):
        from agents.review_agent import ReviewAgent
        review = ReviewAgent(task_board_engine=task_board_engine)
        r1 = review.check_correctness({"passed": 10, "failed": 0, "errors": 0})
        assert r1["ok"] is True
        r2 = review.check_correctness({"passed": 8, "failed": 2, "errors": 0})
        assert r2["ok"] is False

    def test_review_full(self, task_board_engine):
        from agents.review_agent import ReviewAgent
        task_board_engine.create_board(
            expert_type="be",
            tasks=[TaskItem(task_id="t-1", title="A", files=["a.py"], status=TaskStatus.DONE)],
            board_id="tb-rev-4",
        )
        review = ReviewAgent(task_board_engine=task_board_engine)
        result = review.run_full_review(
            "tb-rev-4",
            actual_changed_files=["a.py"],
            test_results={"passed": 5, "failed": 0, "errors": 0},
        )
        assert result.verdict == "approve"
        assert "✅" in result.summary

    def test_review_system_prompt_includes_tool_contract(self, task_board_engine):
        from agents.review_agent import ReviewAgent

        review = ReviewAgent(task_board_engine=task_board_engine)
        prompt = review.build_system_prompt()
        assert "当前可用 MCP 工具摘要" in prompt
        assert "review_result" in prompt


# ── Pipeline Integration Tests ─────────────────────────────────

class TestPipeline:

    def _run(self, coro):
        return asyncio.run(coro)

    async def _collect_events(self, gen):
        events = []
        async for event in gen:
            events.append(event)
        return events

    def test_pipeline_coding_request(self, store, mailbox, task_board_engine):
        from agents.pipeline import run_multi_agent_pipeline
        events = self._run(self._collect_events(
            run_multi_agent_pipeline(
                message="Implement a REST API endpoint for user authentication",
                session_id="test-session",
                risk_level="write_repo",
                store=store,
                mailbox=mailbox,
                task_board_engine=task_board_engine,
            )
        ))

        types = [e["type"] for e in events]
        assert "pipeline_start" in types
        assert "route_decision" in types
        assert "core_decomposition" in types
        assert "tool_stage" in types
        assert "execution_receipt" in types
        assert "content" in types
        assert "pipeline_end" in types

        # Route should dispatch to Core
        route_event = next(e for e in events if e["type"] == "route_decision")
        assert route_event["needs_core"] is True
        assert route_event["delegation_intent"] == "core_execution"
        assert isinstance(route_event["tool_profile"], list)
        assert route_event["decision_source"] == "pipeline_router"

        # End event should reflect delegated-but-not-finished child execution.
        end_event = next(e for e in events if e["type"] == "pipeline_end")
        assert end_event["reason"] == "delegated_waiting_child_completion"

        stage_event = next(e for e in events if e["type"] == "tool_stage")
        assert stage_event["reason"] == "completion_not_submitted"
        assert stage_event["details"]["task_completed"] is False

        receipt_event = next(e for e in events if e["type"] == "execution_receipt")
        agent_state = receipt_event.get("agent_state", {})
        assert agent_state.get("task_completed") is False
        assert isinstance(agent_state.get("final_answer"), str)
        assert len(str(agent_state.get("final_answer") or "")) > 0

    def test_pipeline_readonly_bails_early(self, store, mailbox):
        from agents.pipeline import run_multi_agent_pipeline
        events = self._run(self._collect_events(
            run_multi_agent_pipeline(
                message="What is this project about?",
                session_id="test-session",
                risk_level="read_only",
                store=store,
                mailbox=mailbox,
            )
        ))

        types = [e["type"] for e in events]
        assert "pipeline_start" in types
        assert "route_decision" in types
        assert "pipeline_end" in types
        # Should NOT have core_decomposition
        assert "core_decomposition" not in types

        end_event = next(e for e in events if e["type"] == "pipeline_end")
        assert end_event["reason"] == "shell_direct_reply"

    def test_pipeline_fast_track_route_skips_expert_fanout_when_runtime_available(self, store, mailbox):
        from agents.pipeline import run_multi_agent_pipeline

        async def _mock_child_llm(messages, tools, model):
            del messages, model
            return _mock_child_completion_response(tools, dev_content="已完成单文件小修复")

        async def _mock_tool_executor(tool_name, arguments, child_session_id):
            return {
                "tool_name": tool_name,
                "arguments": arguments,
                "session_id": child_session_id,
                "status": "ok",
            }

        events = self._run(self._collect_events(
            run_multi_agent_pipeline(
                message="请修复 parser.py 的一个 typo，只改一行",
                session_id="test-session-fast-track",
                risk_level="write_repo",
                enable_child_execution=True,
                child_llm_call=_mock_child_llm,
                child_tool_executor=_mock_tool_executor,
                store=store,
                mailbox=mailbox,
            )
        ))

        event_types = [e.get("type") for e in events]
        assert "core_route_selected" in event_types
        core_route_event = next(e for e in events if e["type"] == "core_route_selected")
        assert core_route_event["core_route"] == "fast_track"

        assert "fast_track_start" in event_types
        assert "fast_track_event" in event_types
        assert "fast_track_summary" in event_types
        assert "core_decomposition" not in event_types
        assert "expert_spawned" not in event_types

        stage_event = next(e for e in events if e["type"] == "tool_stage")
        assert stage_event["reason"] == "submitted_completion"
        assert stage_event["details"]["execution_mode"] == "fast_track"

        receipt_event = next(e for e in events if e["type"] == "execution_receipt")
        assert receipt_event.get("agent_state", {}).get("execution_mode") == "fast_track"
        assert receipt_event.get("agent_state", {}).get("task_completed") is True

        end_event = next(e for e in events if e["type"] == "pipeline_end")
        assert end_event["reason"] == "completed"
        assert end_event.get("execution_mode") == "fast_track"

    def test_pipeline_experts_spawned(self, store, mailbox, task_board_engine):
        from agents.pipeline import run_multi_agent_pipeline
        events = self._run(self._collect_events(
            run_multi_agent_pipeline(
                message="Refactor the database module and add unit tests",
                session_id="test-session",
                risk_level="write_repo",
                store=store,
                mailbox=mailbox,
                task_board_engine=task_board_engine,
            )
        ))

        expert_events = [e for e in events if e["type"] == "expert_spawned"]
        assert len(expert_events) > 0
        for ee in expert_events:
            assert "agent_id" in ee
            assert "expert_type" in ee

    def test_pipeline_respects_precomputed_core_route(self, store, mailbox, task_board_engine):
        from agents.pipeline import run_multi_agent_pipeline

        forced_decision = RouterDecision(
            decision_id="route_forced_001",
            created_at="2026-03-04T00:00:00+00:00",
            task_id="chat_forced",
            trace_id="trace_forced",
            session_id="forced-sess",
            task_type="general",
            selected_role="developer",
            selected_model_tier="primary",
            tool_profile=["file_ast", "read_file"],
            prompt_profile="core_exec_general",
            injection_mode="standard_exec",
            delegation_intent="core_execution",
            risk_level="write_repo",
            budget_remaining=None,
            reasoning=["forced_by_guard"],
            replay_fingerprint="forced_fp",
            workflow_entry_state="planned",
            controlled_execution_plan={
                "entry_state": "planned",
                "states": ["planned", "delegating", "executing", "verifying", "completed", "failed"],
            },
        )

        events = self._run(self._collect_events(
            run_multi_agent_pipeline(
                message="只是读状态，但守卫已强制升 Core",
                session_id="forced-sess__core",
                risk_level="read_only",
                route_decision=forced_decision.to_dict(),
                forced_route_semantic="core_execution",
                core_execution_session_id="forced-sess__core",
                store=store,
                mailbox=mailbox,
                task_board_engine=task_board_engine,
            )
        ))

        route_event = next(e for e in events if e["type"] == "route_decision")
        assert route_event["decision_source"] == "precomputed"
        assert route_event["needs_core"] is True
        assert route_event["delegation_intent"] == "core_execution"
        assert "core_decomposition" in [e["type"] for e in events]

    def test_pipeline_executes_child_loops_when_enabled(self, store, mailbox, task_board_engine):
        from agents.pipeline import run_multi_agent_pipeline

        async def _mock_child_llm(messages, tools, model):
            del messages, model
            return _mock_child_completion_response(tools)

        async def _mock_tool_executor(tool_name, arguments, child_session_id):
            return {
                "tool_name": tool_name,
                "arguments": arguments,
                "session_id": child_session_id,
                "status": "ok",
            }

        events = self._run(self._collect_events(
            run_multi_agent_pipeline(
                message="Implement auth endpoint and tests",
                session_id="test-session-child-exec",
                risk_level="write_repo",
                enable_child_execution=True,
                child_llm_call=_mock_child_llm,
                child_tool_executor=_mock_tool_executor,
                store=store,
                mailbox=mailbox,
                task_board_engine=task_board_engine,
            )
        ))

        event_types = [e.get("type") for e in events]
        assert "dev_loop_start" in event_types
        assert "dev_loop_event" in event_types
        assert "dev_loop_end" in event_types
        assert "review_spawned" in event_types
        assert "review_loop_start" in event_types
        assert "review_loop_event" in event_types
        assert "review_loop_end" in event_types
        assert "review_result" in event_types

        receipt_event = next(e for e in events if e["type"] == "execution_receipt")
        assert receipt_event.get("stop_reason") == "submitted_completion"
        assert receipt_event.get("agent_state", {}).get("task_completed") is True
        assert receipt_event.get("agent_state", {}).get("review_count", 0) >= 1

        review_event = next(e for e in events if e["type"] == "review_result")
        assert review_event.get("result", {}).get("verdict") == "approve"

        end_event = next(e for e in events if e["type"] == "pipeline_end")
        assert end_event["reason"] == "completed"


    def test_pipeline_executes_multiple_experts_concurrently(self, monkeypatch, store, mailbox):
        from agents import pipeline as pipeline_module
        from agents.core_agent import CoreAgent

        start_times = {}

        def _fake_decompose(self, dispatch):
            goal = str(dispatch.get("goal") or "")
            return {
                "goal_id": "g-concurrent-experts",
                "subtask_count": 2,
                "model_tier": "primary",
                "target_repo": "external",
                "original_goal": goal,
                "expert_assignments": [
                    {
                        "expert_type": "backend",
                        "scope": "Implement backend endpoint",
                        "prompt_blocks": [],
                        "tool_subset": ["read_file", "grep_files", "apply_patch"],
                        "model_tier": "primary",
                        "prompt_profile": "",
                    },
                    {
                        "expert_type": "testing",
                        "scope": "Add API tests",
                        "prompt_blocks": [],
                        "tool_subset": ["read_file", "grep_files", "apply_patch"],
                        "model_tier": "primary",
                        "prompt_profile": "",
                    },
                ],
            }

        async def _fake_run_mini_loop(
            *,
            session_id,
            store,
            mailbox,
            llm_call,
            tool_executor,
            tool_definitions,
            system_prompt,
            initial_task,
            config,
        ):
            del mailbox, llm_call, tool_executor, tool_definitions, system_prompt, initial_task, config
            session = store.get(session_id)
            yield {"type": "loop_start"}
            if session is not None and session.role == "dev":
                start_times[session_id] = asyncio.get_running_loop().time()
                await asyncio.sleep(0.05)
                store.update_metadata(
                    session_id,
                    {
                        "completion_report": f"{session_id} complete",
                        "verification_report": _mock_verification_report(
                            summary=f"{session_id} complete",
                            changed_files=[f"{session_id}.py"],
                        ),
                    },
                )
                store.update_status(session_id, AgentStatus.WAITING)
                yield {"type": "loop_end", "reason": "submitted_completion", "state": {}}
                return
            yield {"type": "loop_end", "reason": "no_op", "state": {}}

        async def _mock_child_llm(messages, tools, model):
            del messages, tools, model
            return {"content": "", "tool_calls": []}

        async def _mock_tool_executor(tool_name, arguments, child_session_id):
            return {
                "tool_name": tool_name,
                "arguments": arguments,
                "session_id": child_session_id,
                "status": "ok",
            }

        monkeypatch.setattr(CoreAgent, "decompose_goal", _fake_decompose)
        monkeypatch.setattr(CoreAgent, "plan_execution_route", lambda self, dispatch: {"route": "standard", "complexity_hint": "standard", "fast_track_eligible": False, "reason_codes": ["TEST_FORCE_STANDARD"], "max_files": 1, "max_changed_lines": 10, "tool_subset": [], "risk_level": str(dispatch.get("risk_level") or "")})
        monkeypatch.setattr(pipeline_module, "run_mini_loop", _fake_run_mini_loop)

        events = self._run(self._collect_events(
            pipeline_module.run_multi_agent_pipeline(
                message="Implement auth endpoint and tests",
                session_id="test-session-expert-concurrency",
                forced_route_semantic="core_execution",
                risk_level="write_repo",
                enable_child_execution=True,
                child_llm_call=_mock_child_llm,
                child_tool_executor=_mock_tool_executor,
                store=store,
                mailbox=mailbox,
                task_board_engine=None,
            )
        ))

        dev_starts = [e for e in events if e.get("type") == "dev_loop_start"]
        assert len(dev_starts) >= 2
        assert len(start_times) >= 2

        start_gap = max(start_times.values()) - min(start_times.values())
        assert start_gap < 0.04

        receipt_event = next(e for e in events if e["type"] == "execution_receipt")
        scheduler = receipt_event.get("agent_state", {}).get("scheduler", {})
        assert scheduler.get("layer") == "expert"
        assert int(scheduler.get("parallel_limit") or 0) == 2
        assert int(scheduler.get("peak_parallelism") or 0) == 2
        dev_scheduler = (scheduler.get("layers") or {}).get("dev", {})
        assert int(dev_scheduler.get("parallel_limit") or 0) == 2
        assert int(dev_scheduler.get("peak_parallelism") or 0) == 2


    def test_pipeline_respects_core_max_experts_parallel_limit(self, monkeypatch, store, mailbox):
        from agents import pipeline as pipeline_module
        from agents.core_agent import CoreAgent

        start_times = {}
        active_devs = {"value": 0, "max": 0}

        def _fake_decompose(self, dispatch):
            goal = str(dispatch.get("goal") or "")
            return {
                "goal_id": "g-expert-parallel-limit",
                "subtask_count": 3,
                "model_tier": "primary",
                "target_repo": "external",
                "original_goal": goal,
                "expert_assignments": [
                    {
                        "expert_type": "backend",
                        "scope": "Implement backend endpoint",
                        "prompt_blocks": [],
                        "tool_subset": ["read_file", "grep_files", "apply_patch"],
                        "model_tier": "primary",
                        "prompt_profile": "",
                    },
                    {
                        "expert_type": "testing",
                        "scope": "Add API tests",
                        "prompt_blocks": [],
                        "tool_subset": ["read_file", "grep_files", "apply_patch"],
                        "model_tier": "primary",
                        "prompt_profile": "",
                    },
                    {
                        "expert_type": "docs",
                        "scope": "Document API behavior",
                        "prompt_blocks": [],
                        "tool_subset": ["read_file", "grep_files", "apply_patch"],
                        "model_tier": "primary",
                        "prompt_profile": "",
                    },
                ],
            }

        async def _fake_run_mini_loop(
            *,
            session_id,
            store,
            mailbox,
            llm_call,
            tool_executor,
            tool_definitions,
            system_prompt,
            initial_task,
            config,
        ):
            del mailbox, llm_call, tool_executor, tool_definitions, system_prompt, initial_task, config
            session = store.get(session_id)
            yield {"type": "loop_start"}
            if session is not None and session.role == "dev":
                start_times[session_id] = asyncio.get_running_loop().time()
                active_devs["value"] += 1
                active_devs["max"] = max(active_devs["max"], active_devs["value"])
                await asyncio.sleep(0.05)
                active_devs["value"] -= 1
                store.update_metadata(
                    session_id,
                    {
                        "completion_report": f"{session_id} complete",
                        "verification_report": _mock_verification_report(
                            summary=f"{session_id} complete",
                            changed_files=[f"{session_id}.py"],
                        ),
                    },
                )
                store.update_status(session_id, AgentStatus.WAITING)
                yield {"type": "loop_end", "reason": "submitted_completion", "state": {}}
                return
            yield {"type": "loop_end", "reason": "no_op", "state": {}}

        async def _mock_child_llm(messages, tools, model):
            del messages, tools, model
            return {"content": "", "tool_calls": []}

        async def _mock_tool_executor(tool_name, arguments, child_session_id):
            return {
                "tool_name": tool_name,
                "arguments": arguments,
                "session_id": child_session_id,
                "status": "ok",
            }

        monkeypatch.setattr(CoreAgent, "decompose_goal", _fake_decompose)
        monkeypatch.setattr(
            CoreAgent,
            "plan_execution_route",
            lambda self, dispatch: {
                "route": "standard",
                "complexity_hint": "standard",
                "fast_track_eligible": False,
                "reason_codes": ["TEST_FORCE_STANDARD"],
                "max_files": 1,
                "max_changed_lines": 10,
                "tool_subset": [],
                "risk_level": str(dispatch.get("risk_level") or ""),
            },
        )
        monkeypatch.setattr(CoreAgent, "max_experts", property(lambda self: 1))
        monkeypatch.setattr(pipeline_module, "run_mini_loop", _fake_run_mini_loop)

        events = self._run(self._collect_events(
            pipeline_module.run_multi_agent_pipeline(
                message="Implement auth endpoint, tests, and docs",
                session_id="test-session-expert-parallel-limit",
                forced_route_semantic="core_execution",
                risk_level="write_repo",
                enable_child_execution=True,
                child_llm_call=_mock_child_llm,
                child_tool_executor=_mock_tool_executor,
                store=store,
                mailbox=mailbox,
                task_board_engine=None,
            )
        ))

        dev_starts = [e for e in events if e.get("type") == "dev_loop_start"]
        assert len(dev_starts) >= 3
        assert len(start_times) >= 3
        assert active_devs["max"] == 1

        start_gap = max(start_times.values()) - min(start_times.values())
        assert start_gap >= 0.08

        receipt_event = next(e for e in events if e["type"] == "execution_receipt")
        scheduler = receipt_event.get("agent_state", {}).get("scheduler", {})
        assert scheduler.get("layer") == "expert"
        assert int(scheduler.get("parallel_limit") or 0) == 1
        assert int(scheduler.get("peak_parallelism") or 0) == 1
        dev_scheduler = (scheduler.get("layers") or {}).get("dev", {})
        assert int(dev_scheduler.get("parallel_limit") or 0) == 1
        assert int(dev_scheduler.get("peak_parallelism") or 0) == 1


    def test_pipeline_executes_multiple_devs_within_expert_concurrently(self, monkeypatch, store, mailbox):
        from agents import pipeline as pipeline_module
        from agents.core_agent import CoreAgent
        from agents.expert_agent import ExpertAgent

        start_times = {}

        def _fake_decompose(self, dispatch):
            goal = str(dispatch.get("goal") or "")
            return {
                "goal_id": "g-concurrent-devs",
                "subtask_count": 2,
                "model_tier": "primary",
                "target_repo": "external",
                "original_goal": goal,
                "expert_assignments": [
                    {
                        "expert_type": "backend",
                        "scope": "Implement backend endpoint and add tests",
                        "prompt_blocks": [],
                        "tool_subset": ["read_file", "grep_files", "apply_patch"],
                        "model_tier": "primary",
                        "prompt_profile": "",
                    },
                ],
            }

        def _fake_plan_tasks(self, scope):
            del self, scope
            return [
                TaskItem(task_id="t-001", title="Implement backend endpoint", status=TaskStatus.PENDING, depends_on=[]),
                TaskItem(task_id="t-002", title="Add backend tests", status=TaskStatus.PENDING, depends_on=[]),
            ]

        async def _fake_run_mini_loop(
            *,
            session_id,
            store,
            mailbox,
            llm_call,
            tool_executor,
            tool_definitions,
            system_prompt,
            initial_task,
            config,
        ):
            del mailbox, llm_call, tool_executor, tool_definitions, system_prompt, initial_task, config
            session = store.get(session_id)
            yield {"type": "loop_start"}
            if session is not None and session.role == "dev":
                start_times[session_id] = asyncio.get_running_loop().time()
                await asyncio.sleep(0.05)
                store.update_metadata(
                    session_id,
                    {
                        "completion_report": f"{session_id} complete",
                        "verification_report": _mock_verification_report(
                            summary=f"{session_id} complete",
                            changed_files=[f"{session_id}.py"],
                        ),
                    },
                )
                store.update_status(session_id, AgentStatus.WAITING)
                yield {"type": "loop_end", "reason": "submitted_completion", "state": {}}
                return
            yield {"type": "loop_end", "reason": "no_op", "state": {}}

        async def _mock_child_llm(messages, tools, model):
            del messages, tools, model
            return {"content": "", "tool_calls": []}

        async def _mock_tool_executor(tool_name, arguments, child_session_id):
            return {
                "tool_name": tool_name,
                "arguments": arguments,
                "session_id": child_session_id,
                "status": "ok",
            }

        monkeypatch.setattr(CoreAgent, "decompose_goal", _fake_decompose)
        monkeypatch.setattr(
            CoreAgent,
            "plan_execution_route",
            lambda self, dispatch: {
                "route": "standard",
                "complexity_hint": "standard",
                "fast_track_eligible": False,
                "reason_codes": ["TEST_FORCE_STANDARD"],
                "max_files": 1,
                "max_changed_lines": 10,
                "tool_subset": [],
                "risk_level": str(dispatch.get("risk_level") or ""),
            },
        )
        monkeypatch.setattr(ExpertAgent, "plan_tasks", _fake_plan_tasks)
        monkeypatch.setattr(pipeline_module, "run_mini_loop", _fake_run_mini_loop)

        events = self._run(self._collect_events(
            pipeline_module.run_multi_agent_pipeline(
                message="Implement auth endpoint and tests",
                session_id="test-session-dev-concurrency",
                forced_route_semantic="core_execution",
                risk_level="write_repo",
                enable_child_execution=True,
                child_llm_call=_mock_child_llm,
                child_tool_executor=_mock_tool_executor,
                store=store,
                mailbox=mailbox,
                task_board_engine=None,
            )
        ))

        dev_starts = [e for e in events if e.get("type") == "dev_loop_start"]
        assert len(dev_starts) >= 2
        assert len(start_times) >= 2

        start_gap = max(start_times.values()) - min(start_times.values())
        assert start_gap < 0.04

        receipt_event = next(e for e in events if e["type"] == "execution_receipt")
        scheduler = receipt_event.get("agent_state", {}).get("scheduler", {})
        dev_scheduler = (scheduler.get("layers") or {}).get("dev", {})
        assert int(dev_scheduler.get("parallel_limit") or 0) == 2
        assert int(dev_scheduler.get("peak_parallelism") or 0) == 2

    def test_pipeline_review_request_changes_resumes_dev_and_re_reviews(self, store, mailbox, task_board_engine):
        from agents.pipeline import run_multi_agent_pipeline

        review_round = {"value": 0}
        dev_round = {"value": 0}

        async def _mock_child_llm(messages, tools, model):
            del messages, model
            tool_names = {str(item.get("name") or "").strip() for item in tools if isinstance(item, dict)}
            is_review = bool({"memory_tag", "memory_deprecate"} & tool_names)
            if is_review:
                review_round["value"] += 1
                if review_round["value"] == 1:
                    return {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "review_cycle_1",
                                "name": "report_to_parent",
                                "arguments": {
                                    "type": "completed",
                                    "content": "need changes before approval",
                                    "review_result": _mock_review_result(
                                        verdict="request_changes",
                                        summary="need changes before approval",
                                    ) | {
                                        "issues": ["Add the missing edge-case handling."],
                                        "suggestions": ["Cover the new edge case in self-verification."],
                                    },
                                },
                            }
                        ],
                    }
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "review_cycle_2",
                            "name": "report_to_parent",
                            "arguments": {
                                "type": "completed",
                                "content": "review approved after remediation",
                                "review_result": _mock_review_result(summary="review approved after remediation"),
                            },
                        }
                    ],
                }

            dev_round["value"] += 1
            dev_content = "child work complete" if dev_round["value"] == 1 else "child work complete after review remediation"
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": f"dev_done_{dev_round['value']}",
                        "name": "report_to_parent",
                        "arguments": {
                            "type": "completed",
                            "content": dev_content,
                            "verification_report": _mock_verification_report(summary=dev_content),
                        },
                    }
                ],
            }

        async def _mock_tool_executor(tool_name, arguments, child_session_id):
            return {
                "tool_name": tool_name,
                "arguments": arguments,
                "session_id": child_session_id,
                "status": "ok",
            }

        events = self._run(self._collect_events(
            run_multi_agent_pipeline(
                message="Implement auth endpoint and tests",
                session_id="test-session-review-remediation",
                risk_level="write_repo",
                enable_child_execution=True,
                child_llm_call=_mock_child_llm,
                child_tool_executor=_mock_tool_executor,
                store=store,
                mailbox=mailbox,
                task_board_engine=task_board_engine,
            )
        ))

        event_types = [e.get("type") for e in events]
        assert "review_rework_requested" in event_types
        assert "dev_review_resume_start" in event_types
        assert "dev_review_resume_end" in event_types

        review_events = [e for e in events if e.get("type") == "review_result"]
        assert len(review_events) >= 2
        assert review_events[0].get("result", {}).get("verdict") == "request_changes"
        assert review_events[-1].get("result", {}).get("verdict") == "approve"

        receipt_event = next(e for e in events if e["type"] == "execution_receipt")
        assert receipt_event.get("stop_reason") == "submitted_completion"
        assert receipt_event.get("agent_state", {}).get("task_completed") is True

    def test_pipeline_review_reject_respawns_new_dev_and_re_reviews(self, store, mailbox, task_board_engine):
        from agents.pipeline import run_multi_agent_pipeline

        review_round = {"value": 0}
        dev_round = {"value": 0}

        async def _mock_child_llm(messages, tools, model):
            del messages, model
            tool_names = {str(item.get("name") or "").strip() for item in tools if isinstance(item, dict)}
            is_review = bool({"memory_tag", "memory_deprecate"} & tool_names)
            if is_review:
                review_round["value"] += 1
                if review_round["value"] == 1:
                    return {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "review_reject_1",
                                "name": "report_to_parent",
                                "arguments": {
                                    "type": "completed",
                                    "content": "reject current implementation",
                                    "review_result": _mock_review_result(
                                        verdict="reject",
                                        summary="reject current implementation",
                                    ) | {
                                        "issues": ["Architecture mismatch requires a fresh retry."],
                                        "suggestions": ["Restart the implementation with a simplified approach."],
                                    },
                                },
                            }
                        ],
                    }
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "review_approve_after_respawn",
                            "name": "report_to_parent",
                            "arguments": {
                                "type": "completed",
                                "content": "review approved after respawn",
                                "review_result": _mock_review_result(summary="review approved after respawn"),
                            },
                        }
                    ],
                }

            dev_round["value"] += 1
            dev_content = "child work complete" if dev_round["value"] == 1 else "child work complete after reject respawn"
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": f"dev_reject_respawn_{dev_round['value']}",
                        "name": "report_to_parent",
                        "arguments": {
                            "type": "completed",
                            "content": dev_content,
                            "verification_report": _mock_verification_report(summary=dev_content),
                        },
                    }
                ],
            }

        async def _mock_tool_executor(tool_name, arguments, child_session_id):
            return {
                "tool_name": tool_name,
                "arguments": arguments,
                "session_id": child_session_id,
                "status": "ok",
            }

        events = self._run(self._collect_events(
            run_multi_agent_pipeline(
                message="Implement auth endpoint and tests",
                session_id="test-session-review-reject-respawn",
                risk_level="write_repo",
                enable_child_execution=True,
                child_llm_call=_mock_child_llm,
                child_tool_executor=_mock_tool_executor,
                store=store,
                mailbox=mailbox,
                task_board_engine=task_board_engine,
            )
        ))

        event_types = [e.get("type") for e in events]
        assert "review_reject_respawn" in event_types
        review_events = [e for e in events if e.get("type") == "review_result"]
        assert len(review_events) >= 2
        assert review_events[0].get("result", {}).get("verdict") == "reject"
        assert review_events[-1].get("result", {}).get("verdict") == "approve"

        respawned_dev_starts = [
            e for e in events
            if e.get("type") == "dev_loop_start" and e.get("recovery_mode") == "reject_respawn"
        ]
        assert respawned_dev_starts

        receipt_event = next(e for e in events if e["type"] == "execution_receipt")
        assert receipt_event.get("stop_reason") == "submitted_completion"
        assert receipt_event.get("agent_state", {}).get("task_completed") is True

    def test_pipeline_review_reject_unrecoverable_escalates_blocked(self, store, mailbox, task_board_engine):
        from agents.pipeline import run_multi_agent_pipeline

        async def _mock_child_llm(messages, tools, model):
            del messages, model
            tool_names = {str(item.get("name") or "").strip() for item in tools if isinstance(item, dict)}
            is_review = bool({"memory_tag", "memory_deprecate"} & tool_names)
            if is_review:
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "review_reject_blocked_1",
                            "name": "report_to_parent",
                            "arguments": {
                                "type": "completed",
                                "content": "reject due to invalid review contract",
                                "review_result": _mock_review_result(
                                    verdict="reject",
                                    summary="reject due to invalid review contract",
                                ) | {
                                    "issues": ["Review agent did not emit a valid review_result contract."],
                                },
                            },
                        }
                    ],
                }
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "dev_done_blocked_1",
                        "name": "report_to_parent",
                        "arguments": {
                            "type": "completed",
                            "content": "child work complete",
                            "verification_report": _mock_verification_report(summary="child work complete"),
                        },
                    }
                ],
            }

        async def _mock_tool_executor(tool_name, arguments, child_session_id):
            return {
                "tool_name": tool_name,
                "arguments": arguments,
                "session_id": child_session_id,
                "status": "ok",
            }

        events = self._run(self._collect_events(
            run_multi_agent_pipeline(
                message="Implement auth endpoint and tests",
                session_id="test-session-review-reject-blocked",
                risk_level="write_repo",
                enable_child_execution=True,
                child_llm_call=_mock_child_llm,
                child_tool_executor=_mock_tool_executor,
                store=store,
                mailbox=mailbox,
                task_board_engine=task_board_engine,
            )
        ))

        event_types = [e.get("type") for e in events]
        assert "expert_blocked" in event_types
        assert "review_reject_respawn" not in event_types

        receipt_event = next(e for e in events if e["type"] == "execution_receipt")
        assert receipt_event.get("stop_reason") == "review_rejected"
        assert receipt_event.get("agent_state", {}).get("task_completed") is False

        expert_reports = [e for e in events if e.get("type") == "expert_report"]
        assert any("[BLOCKED]" in "\n".join(map(str, e.get("reports", []))) for e in expert_reports)

    def test_pipeline_heartbeat_blocked_respawns_dev_and_completes(self, store, mailbox, task_board_engine):
        from agents.pipeline import run_multi_agent_pipeline

        async def _mock_child_llm(messages, tools, model):
            del model
            tool_names = {str(item.get("name") or "").strip() for item in tools if isinstance(item, dict)}
            joined_messages = "\n".join(str(item.get("content") or "") for item in messages if isinstance(item, dict))
            is_review = bool({"memory_tag", "memory_deprecate"} & tool_names)
            if is_review:
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "review_after_heartbeat_respawn",
                            "name": "report_to_parent",
                            "arguments": {
                                "type": "completed",
                                "content": "review approved after heartbeat respawn",
                                "review_result": _mock_review_result(summary="review approved after heartbeat respawn"),
                            },
                        }
                    ],
                }
            if "Heartbeat escalation:" in joined_messages:
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "dev_done_after_heartbeat_respawn",
                            "name": "report_to_parent",
                            "arguments": {
                                "type": "completed",
                                "content": "child work complete after heartbeat respawn",
                                "verification_report": _mock_verification_report(summary="child work complete after heartbeat respawn"),
                            },
                        }
                    ],
                }
            await asyncio.sleep(0.05)
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "dev_stale_heartbeat",
                        "name": "publish_task_heartbeat",
                        "arguments": {
                            "task_id": "task-heartbeat",
                            "status": "running",
                            "message": "sandbox task still running",
                            "stage": "apply_patch",
                            "generated_at": "2026-03-10T00:00:00+00:00",
                            "ttl_seconds": 30,
                        },
                    }
                ],
            }

        async def _mock_tool_executor(tool_name, arguments, child_session_id):
            return {
                "tool_name": tool_name,
                "arguments": arguments,
                "session_id": child_session_id,
                "status": "ok",
            }

        events = self._run(self._collect_events(
            run_multi_agent_pipeline(
                message="Implement auth endpoint",
                session_id="test-session-heartbeat-respawn",
                risk_level="write_repo",
                enable_child_execution=True,
                child_llm_call=_mock_child_llm,
                child_tool_executor=_mock_tool_executor,
                store=store,
                mailbox=mailbox,
                task_board_engine=task_board_engine,
            )
        ))

        event_types = [e.get("type") for e in events]
        assert "heartbeat_respawn" in event_types
        assert "expert_blocked" not in event_types

        respawn_starts = [
            e for e in events
            if e.get("type") == "dev_loop_start" and e.get("recovery_mode") == "heartbeat_respawn"
        ]
        assert respawn_starts

        receipt_event = next(e for e in events if e["type"] == "execution_receipt")
        assert receipt_event.get("stop_reason") == "submitted_completion"
        assert receipt_event.get("agent_state", {}).get("task_completed") is True
        heartbeat_summary = receipt_event.get("agent_state", {}).get("heartbeat_summary", {})
        assert int(heartbeat_summary.get("respawn_count") or 0) >= 1
        assert int(heartbeat_summary.get("blocked_count") or 0) >= 1

    def test_pipeline_heartbeat_respawn_exhausted_escalates_blocked(self, store, mailbox, task_board_engine):
        from agents.pipeline import run_multi_agent_pipeline

        async def _mock_child_llm(messages, tools, model):
            del model
            tool_names = {str(item.get("name") or "").strip() for item in tools if isinstance(item, dict)}
            joined_messages = "\n".join(str(item.get("content") or "") for item in messages if isinstance(item, dict))
            is_review = bool({"memory_tag", "memory_deprecate"} & tool_names)
            if is_review:
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "review_should_not_run",
                            "name": "report_to_parent",
                            "arguments": {
                                "type": "completed",
                                "content": "unexpected review",
                                "review_result": _mock_review_result(summary="unexpected review"),
                            },
                        }
                    ],
                }
            await asyncio.sleep(0.05)
            heartbeat_task_id = "task-heartbeat-respawn" if "Heartbeat escalation:" in joined_messages else "task-heartbeat"
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": f"dev_stale_{heartbeat_task_id}",
                        "name": "publish_task_heartbeat",
                        "arguments": {
                            "task_id": heartbeat_task_id,
                            "status": "running",
                            "message": "still alive but stale",
                            "stage": "sandbox_exec",
                            "generated_at": "2026-03-10T00:00:00+00:00",
                            "ttl_seconds": 30,
                        },
                    }
                ],
            }

        async def _mock_tool_executor(tool_name, arguments, child_session_id):
            return {
                "tool_name": tool_name,
                "arguments": arguments,
                "session_id": child_session_id,
                "status": "ok",
            }

        events = self._run(self._collect_events(
            run_multi_agent_pipeline(
                message="Implement auth endpoint",
                session_id="test-session-heartbeat-blocked",
                risk_level="write_repo",
                enable_child_execution=True,
                child_llm_call=_mock_child_llm,
                child_tool_executor=_mock_tool_executor,
                store=store,
                mailbox=mailbox,
                task_board_engine=task_board_engine,
            )
        ))

        event_types = [e.get("type") for e in events]
        assert "heartbeat_respawn" in event_types
        assert "expert_blocked" in event_types

        receipt_event = next(e for e in events if e["type"] == "execution_receipt")
        assert receipt_event.get("stop_reason") == "task_heartbeat_blocked_respawn_exhausted"
        assert receipt_event.get("agent_state", {}).get("task_completed") is False
        assert receipt_event.get("agent_state", {}).get("experts_blocked") is True
        heartbeat_summary = receipt_event.get("agent_state", {}).get("heartbeat_summary", {})
        assert int(heartbeat_summary.get("expert_blocked_count") or 0) >= 1
        assert "task_heartbeat_blocked_respawn_exhausted" in list(heartbeat_summary.get("expert_blocked_reasons") or [])

    def test_pipeline_report_collection_is_scoped_to_current_pipeline_run(
        self,
        store,
        mailbox,
        task_board_engine,
    ):
        from agents.pipeline import run_multi_agent_pipeline

        async def _mock_child_llm(messages, tools, model):
            del messages, model
            return _mock_child_completion_response(tools)

        async def _mock_tool_executor(tool_name, arguments, child_session_id):
            return {
                "tool_name": tool_name,
                "arguments": arguments,
                "session_id": child_session_id,
                "status": "ok",
            }

        core_execution_session_id = "shell-session__core"

        first_events = self._run(self._collect_events(
            run_multi_agent_pipeline(
                message="Implement auth endpoint and tests",
                session_id=core_execution_session_id,
                core_execution_session_id=core_execution_session_id,
                risk_level="write_repo",
                enable_child_execution=True,
                child_llm_call=_mock_child_llm,
                child_tool_executor=_mock_tool_executor,
                store=store,
                mailbox=mailbox,
                task_board_engine=task_board_engine,
            )
        ))
        first_receipt = next(e for e in first_events if e["type"] == "execution_receipt")
        first_expert_count = int(first_receipt.get("agent_state", {}).get("expert_count") or 0)
        first_reports = [e for e in first_events if e.get("type") == "expert_report"]
        assert len(first_reports) == first_expert_count

        second_events = self._run(self._collect_events(
            run_multi_agent_pipeline(
                message="Implement auth endpoint and tests",
                session_id=core_execution_session_id,
                core_execution_session_id=core_execution_session_id,
                risk_level="write_repo",
                enable_child_execution=True,
                child_llm_call=_mock_child_llm,
                child_tool_executor=_mock_tool_executor,
                store=store,
                mailbox=mailbox,
                task_board_engine=task_board_engine,
            )
        ))
        second_receipt = next(e for e in second_events if e["type"] == "execution_receipt")
        second_expert_count = int(second_receipt.get("agent_state", {}).get("expert_count") or 0)
        second_reports = [e for e in second_events if e.get("type") == "expert_report"]
        assert len(second_reports) == second_expert_count

        # Runtime store keeps historical children, but report collection should
        # be scoped to the current pipeline run instead of all non-destroyed children.
        all_children = store.list_children(core_execution_session_id)
        assert len(all_children) >= first_expert_count + second_expert_count

    def test_pipeline_cleanup_destroy_mode_reaps_current_run_children(self, store, mailbox, task_board_engine):
        from agents.pipeline import run_multi_agent_pipeline

        async def _mock_child_llm(messages, tools, model):
            del messages, model
            return _mock_child_completion_response(tools)

        async def _mock_tool_executor(tool_name, arguments, child_session_id):
            return {
                "tool_name": tool_name,
                "arguments": arguments,
                "session_id": child_session_id,
                "status": "ok",
            }

        core_execution_session_id = "cleanup-destroy__core"
        events = self._run(self._collect_events(
            run_multi_agent_pipeline(
                message="Implement auth endpoint and tests",
                session_id=core_execution_session_id,
                core_execution_session_id=core_execution_session_id,
                risk_level="write_repo",
                enable_child_execution=True,
                child_llm_call=_mock_child_llm,
                child_tool_executor=_mock_tool_executor,
                child_session_cleanup_mode="destroy",
                store=store,
                mailbox=mailbox,
                task_board_engine=task_board_engine,
            )
        ))

        end_event = next(e for e in events if e["type"] == "pipeline_end")
        cleanup = end_event["child_session_cleanup"]
        assert cleanup["mode"] == "destroy"
        assert cleanup["destroyed_count"] >= 1
        assert len(store.list_children(core_execution_session_id)) == 0

    def test_pipeline_cleanup_ttl_mode_reaps_expired_history_children(self, store, mailbox, task_board_engine):
        from agents.pipeline import run_multi_agent_pipeline

        async def _mock_child_llm(messages, tools, model):
            del messages, model
            return _mock_child_completion_response(tools)

        async def _mock_tool_executor(tool_name, arguments, child_session_id):
            return {
                "tool_name": tool_name,
                "arguments": arguments,
                "session_id": child_session_id,
                "status": "ok",
            }

        core_execution_session_id = "cleanup-ttl__core"
        old_child = store.create(
            role="expert",
            parent_id=core_execution_session_id,
            task_description="historical child",
            metadata={"pipeline_id": "pipe_historical_old"},
        )
        store.update_status(old_child.session_id, AgentStatus.WAITING)
        mailbox.send(old_child.session_id, core_execution_session_id, "historical report", message_type="report")
        assert len(store.list_children(core_execution_session_id)) == 1

        events = self._run(self._collect_events(
            run_multi_agent_pipeline(
                message="Implement auth endpoint and tests",
                session_id=core_execution_session_id,
                core_execution_session_id=core_execution_session_id,
                risk_level="write_repo",
                enable_child_execution=True,
                child_llm_call=_mock_child_llm,
                child_tool_executor=_mock_tool_executor,
                child_session_cleanup_mode="ttl",
                child_session_cleanup_ttl_seconds=0,
                store=store,
                mailbox=mailbox,
                task_board_engine=task_board_engine,
            )
        ))

        end_event = next(e for e in events if e["type"] == "pipeline_end")
        cleanup = end_event["child_session_cleanup"]
        assert cleanup["mode"] == "ttl"
        assert cleanup["ttl_seconds"] == 0
        assert cleanup["destroyed_count"] >= 2
        assert len(store.list_children(core_execution_session_id)) == 0

    def test_pipeline_core_loop_exposes_parent_lifecycle_tools(self, store, mailbox, task_board_engine):
        from agents.pipeline import run_multi_agent_pipeline

        core_tool_round = {"value": 0}

        async def _mock_child_llm(messages, tools, model):
            del messages, model
            tool_names = {str(item.get("name") or "").strip() for item in tools if isinstance(item, dict)}
            if "poll_child_status" in tool_names:
                idx = int(core_tool_round["value"])
                core_tool_round["value"] = idx + 1
                if idx == 0:
                    return {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "core_spawn_1",
                                "name": "spawn_child_agent",
                                "arguments": {"role": "dev", "task_description": "run quick verify"},
                            }
                        ],
                    }
                if idx == 1:
                    return {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "core_poll_1",
                                "name": "poll_child_status",
                                "arguments": {"agent_id": "missing-child"},
                            }
                        ],
                    }
                if idx == 2:
                    return {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "core_resume_1",
                                "name": "resume_child_agent",
                                "arguments": {"agent_id": "missing-child", "instruction": "retry"},
                            }
                        ],
                    }
                if idx == 3:
                    return {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "core_destroy_1",
                                "name": "destroy_child_agent",
                                "arguments": {"agent_id": "missing-child", "reason": "cleanup"},
                            }
                        ],
                    }
                return {"content": "", "tool_calls": []}

            # Dev/review loops complete in one round.
            return _mock_child_completion_response(tools)

        async def _mock_tool_executor(tool_name, arguments, child_session_id):
            return {
                "tool_name": tool_name,
                "arguments": arguments,
                "session_id": child_session_id,
                "status": "ok",
            }

        events = self._run(
            self._collect_events(
                run_multi_agent_pipeline(
                    message="Implement auth endpoint and tests",
                    session_id="core-loop-parent-tools",
                    core_execution_session_id="core-loop-parent-tools__core",
                    risk_level="write_repo",
                    enable_child_execution=True,
                    child_llm_call=_mock_child_llm,
                    child_tool_executor=_mock_tool_executor,
                    store=store,
                    mailbox=mailbox,
                    task_board_engine=task_board_engine,
                )
            )
        )

        event_types = [str(item.get("type") or "") for item in events if isinstance(item, dict)]
        assert "core_loop_start" in event_types
        assert "core_loop_end" in event_types
        assert "dev_loop_spawn_start" in event_types
        assert "dev_loop_spawn_end" in event_types

        core_loop_events = [item for item in events if item.get("type") == "core_loop_event"]
        invoked_tools = [
            str(item.get("event", {}).get("name") or "")
            for item in core_loop_events
            if isinstance(item.get("event"), dict) and str(item["event"].get("type") or "") == "tool_call"
        ]
        assert "spawn_child_agent" in invoked_tools
        assert "poll_child_status" in invoked_tools
        assert "resume_child_agent" in invoked_tools
        assert "destroy_child_agent" in invoked_tools

        receipt = next(item for item in events if item.get("type") == "execution_receipt")
        agent_state = receipt.get("agent_state", {})
        assert int(agent_state.get("core_loop_tool_calls") or 0) >= 4
        used_tools = set(agent_state.get("core_loop_tools_used") or [])
        assert {
            "spawn_child_agent",
            "poll_child_status",
            "resume_child_agent",
            "destroy_child_agent",
        }.issubset(used_tools)
        core_loop_state = agent_state.get("core_loop", {}) if isinstance(agent_state.get("core_loop"), dict) else {}
        assert len(core_loop_state.get("spawned_child_ids") or []) >= 1

    def test_pipeline_core_loop_resume_runs_child_loop_in_band(self, store, mailbox, task_board_engine):
        from agents.pipeline import run_multi_agent_pipeline

        resumed_once = {"value": False}

        async def _mock_child_llm(messages, tools, model):
            del messages, model
            tool_names = {str(item.get("name") or "").strip() for item in tools if isinstance(item, dict)}
            if "resume_child_agent" in tool_names:
                if resumed_once["value"]:
                    return {"content": "", "tool_calls": []}
                waiting_dev_id = ""
                for expert in store.list_children("core-loop-resume__core"):
                    for child in store.list_children(expert.session_id):
                        if child.role == "dev" and child.status == AgentStatus.WAITING:
                            waiting_dev_id = child.session_id
                            break
                    if waiting_dev_id:
                        break
                if waiting_dev_id:
                    resumed_once["value"] = True
                    return {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "core_resume_real_1",
                                "name": "resume_child_agent",
                                "arguments": {"agent_id": waiting_dev_id, "instruction": "rerun verification"},
                            }
                        ],
                    }
                return {"content": "", "tool_calls": []}

            # Dev/review loop: finish quickly via structured completion report.
            return _mock_child_completion_response(tools, dev_content="dev resumed and finished")

        async def _mock_tool_executor(tool_name, arguments, child_session_id):
            return {
                "tool_name": tool_name,
                "arguments": arguments,
                "session_id": child_session_id,
                "status": "ok",
            }

        events = self._run(
            self._collect_events(
                run_multi_agent_pipeline(
                    message="Implement auth endpoint and tests",
                    session_id="core-loop-resume__core",
                    core_execution_session_id="core-loop-resume__core",
                    risk_level="write_repo",
                    enable_child_execution=True,
                    child_llm_call=_mock_child_llm,
                    child_tool_executor=_mock_tool_executor,
                    store=store,
                    mailbox=mailbox,
                    task_board_engine=task_board_engine,
                )
            )
        )

        event_types = [str(item.get("type") or "") for item in events if isinstance(item, dict)]
        assert "core_loop_start" in event_types
        assert "dev_loop_resume_start" in event_types
        assert "dev_loop_resume_end" in event_types
        assert "expert_report_refresh" in event_types

        resume_events = [item for item in events if item.get("type") == "dev_loop_resume_end"]
        assert any(str(item.get("status") or "") == "waiting" for item in resume_events)

        receipt = next(item for item in events if item.get("type") == "execution_receipt")
        agent_state = receipt.get("agent_state", {})
        core_loop_state = agent_state.get("core_loop", {}) if isinstance(agent_state.get("core_loop"), dict) else {}
        assert int(core_loop_state.get("resume_exec_dev_count") or 0) >= 1

    def test_pipeline_core_loop_spawn_review_is_deferred(self, store, mailbox, task_board_engine):
        from agents.pipeline import run_multi_agent_pipeline

        core_tool_round = {"value": 0}

        async def _mock_child_llm(messages, tools, model):
            del messages, model
            tool_names = {str(item.get("name") or "").strip() for item in tools if isinstance(item, dict)}
            if "poll_child_status" in tool_names:
                idx = int(core_tool_round["value"])
                core_tool_round["value"] = idx + 1
                if idx == 0:
                    return {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "core_spawn_review_1",
                                "name": "spawn_child_agent",
                                "arguments": {
                                    "role": "review",
                                    "task_description": "defer review to follow-up request",
                                },
                            }
                        ],
                    }
                return {"content": "", "tool_calls": []}

            # Dev/review loops complete in one round.
            return _mock_child_completion_response(tools)

        async def _mock_tool_executor(tool_name, arguments, child_session_id):
            return {
                "tool_name": tool_name,
                "arguments": arguments,
                "session_id": child_session_id,
                "status": "ok",
            }

        events = self._run(
            self._collect_events(
                run_multi_agent_pipeline(
                    message="Implement auth endpoint and tests",
                    session_id="core-loop-spawn-review",
                    core_execution_session_id="core-loop-spawn-review__core",
                    risk_level="write_repo",
                    enable_child_execution=True,
                    child_llm_call=_mock_child_llm,
                    child_tool_executor=_mock_tool_executor,
                    store=store,
                    mailbox=mailbox,
                    task_board_engine=task_board_engine,
                )
            )
        )

        deferred_events = [item for item in events if item.get("type") == "child_spawn_deferred"]
        assert deferred_events
        assert any(str(item.get("role") or "") == "review" for item in deferred_events)

        deferred_agent_id = str(deferred_events[-1].get("agent_id") or "")
        assert deferred_agent_id
        deferred_session = store.get(deferred_agent_id)
        assert deferred_session is not None
        assert deferred_session.status == AgentStatus.WAITING
        assert deferred_session.role == "review"

        receipt = next(item for item in events if item.get("type") == "execution_receipt")
        agent_state = receipt.get("agent_state", {})
        core_loop_state = agent_state.get("core_loop", {}) if isinstance(agent_state.get("core_loop"), dict) else {}
        deferred_ids = core_loop_state.get("deferred_child_ids") or []
        assert deferred_agent_id in deferred_ids
