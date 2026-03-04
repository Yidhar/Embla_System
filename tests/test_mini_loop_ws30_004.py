"""Unit tests for mini tool-loop — Phase 1.4 verification."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List

import pytest

from agents.runtime.agent_session import AgentSessionStore, AgentStatus
from agents.runtime.mailbox import AgentMailbox
from agents.runtime.mini_loop import MiniLoopConfig, run_mini_loop


# ── Mock LLM + Tool executor ──────────────────────────────────

class MockLLM:
    """Programmable mock LLM that returns scripted responses."""

    def __init__(self, responses: List[Dict[str, Any]]) -> None:
        self._responses = list(responses)
        self._call_count = 0

    async def __call__(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        model: str,
    ) -> Dict[str, Any]:
        if self._call_count < len(self._responses):
            resp = self._responses[self._call_count]
        else:
            resp = {"content": "Done. No more actions needed.", "tool_calls": []}
        self._call_count += 1
        return resp


class MockToolExecutor:
    """Mock tool executor that records calls and returns canned results."""

    def __init__(self, results: Dict[str, Any] | None = None) -> None:
        self._results = results or {}
        self.calls: List[Dict[str, Any]] = []

    async def __call__(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        self.calls.append({"name": tool_name, "arguments": arguments})
        return self._results.get(tool_name, {"ok": True})


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


def _collect_events(gen) -> List[Dict[str, Any]]:
    """Run async generator and collect all yielded events."""
    # Use an isolated loop per invocation to avoid cross-test loop state pollution.
    return asyncio.run(_async_collect(gen))


async def _async_collect(gen) -> List[Dict[str, Any]]:
    events = []
    async for event in gen:
        events.append(event)
    return events


# ── Tests ──────────────────────────────────────────────────────

class TestMiniLoop:

    def test_natural_stop_no_tools(self, store, mailbox):
        """LLM returns content without tool calls → loop stops naturally."""
        parent = store.create(role="expert", session_id="parent-1")
        child = store.create(role="dev", parent_id="parent-1", session_id="child-1")

        llm = MockLLM([
            {"content": "I'll analyze the code now.", "tool_calls": []},
        ])
        executor = MockToolExecutor()

        events = _collect_events(run_mini_loop(
            session_id="child-1",
            store=store,
            mailbox=mailbox,
            llm_call=llm,
            tool_executor=executor,
            tool_definitions=[],
            initial_task="Analyze file_ast.py",
        ))

        end_events = [e for e in events if e["type"] == "loop_end"]
        assert len(end_events) == 1
        assert end_events[0]["reason"] == "no_tool_calls"

    def test_tool_call_and_result(self, store, mailbox):
        """LLM returns tool calls → executor runs → results fed back."""
        store.create(role="expert", session_id="parent-1")
        store.create(role="dev", parent_id="parent-1", session_id="child-1")

        llm = MockLLM([
            {
                "content": "",
                "tool_calls": [{"id": "c1", "name": "read_file", "arguments": {"path": "test.py"}}],
            },
            {"content": "File looks good. Done.", "tool_calls": []},
        ])
        executor = MockToolExecutor({"read_file": {"content": "def hello(): pass"}})

        events = _collect_events(run_mini_loop(
            session_id="child-1",
            store=store,
            mailbox=mailbox,
            llm_call=llm,
            tool_executor=executor,
            tool_definitions=[{"name": "read_file"}],
            initial_task="Read test.py",
        ))

        tool_calls = [e for e in events if e["type"] == "tool_call"]
        assert len(tool_calls) == 1
        assert tool_calls[0]["name"] == "read_file"

        tool_results = [e for e in events if e["type"] == "tool_result"]
        assert len(tool_results) == 1
        assert tool_results[0]["result"]["content"] == "def hello(): pass"

    def test_report_completed_stops_loop(self, store, mailbox):
        """Child calling report_to_parent(completed) stops the loop."""
        store.create(role="expert", session_id="parent-1")
        store.create(role="dev", parent_id="parent-1", session_id="child-1")

        llm = MockLLM([
            {
                "content": "",
                "tool_calls": [{
                    "id": "c1",
                    "name": "report_to_parent",
                    "arguments": {"type": "completed", "content": "All done"},
                }],
            },
        ])
        executor = MockToolExecutor()

        events = _collect_events(run_mini_loop(
            session_id="child-1",
            store=store,
            mailbox=mailbox,
            llm_call=llm,
            tool_executor=executor,
            tool_definitions=[],
            initial_task="Do work",
        ))

        end_events = [e for e in events if e["type"] == "loop_end"]
        assert len(end_events) == 1
        assert end_events[0]["reason"] == "child_reported_completed"

        # Session should be Waiting
        s = store.get("child-1")
        assert s.status == AgentStatus.WAITING

    def test_parent_interrupt_stops_loop(self, store, mailbox):
        """Parent sets interrupt flag → child stops at next round."""
        store.create(role="expert", session_id="parent-1")
        child = store.create(role="dev", parent_id="parent-1", session_id="child-1")

        # Set interrupt before loop starts
        store.set_interrupt("child-1")

        llm = MockLLM([
            {"content": "Working...", "tool_calls": [{"id": "c1", "name": "read_file", "arguments": {}}]},
        ])
        executor = MockToolExecutor()

        events = _collect_events(run_mini_loop(
            session_id="child-1",
            store=store,
            mailbox=mailbox,
            llm_call=llm,
            tool_executor=executor,
            tool_definitions=[],
            initial_task="Task",
        ))

        end_events = [e for e in events if e["type"] == "loop_end"]
        assert end_events[0]["reason"] == "parent_interrupted"

    def test_session_not_found(self, store, mailbox):
        """Loop yields end event if session doesn't exist."""
        llm = MockLLM([])
        executor = MockToolExecutor()

        events = _collect_events(run_mini_loop(
            session_id="nonexistent",
            store=store,
            mailbox=mailbox,
            llm_call=llm,
            tool_executor=executor,
            tool_definitions=[],
        ))

        assert len(events) == 1
        assert events[0]["reason"] == "session_not_found"

    def test_messages_persisted_after_loop(self, store, mailbox):
        """Conversation history is saved after loop ends."""
        store.create(role="expert", session_id="parent-1")
        store.create(role="dev", parent_id="parent-1", session_id="child-1")

        llm = MockLLM([
            {"content": "Analyzing...", "tool_calls": []},
        ])
        executor = MockToolExecutor()

        _collect_events(run_mini_loop(
            session_id="child-1",
            store=store,
            mailbox=mailbox,
            llm_call=llm,
            tool_executor=executor,
            tool_definitions=[],
            system_prompt="You are a dev agent.",
            initial_task="Analyze code.",
        ))

        s = store.get("child-1")
        assert len(s.messages) >= 2  # system + user + assistant at minimum

    def test_child_tool_routing(self, store, mailbox):
        """Child tools (update_my_task_status) are routed to child handler, not executor."""
        store.create(role="expert", session_id="parent-1")
        store.create(role="dev", parent_id="parent-1", session_id="child-1")

        llm = MockLLM([
            {
                "content": "",
                "tool_calls": [{
                    "id": "c1",
                    "name": "update_my_task_status",
                    "arguments": {"task_id": "t-001", "status": "done"},
                }],
            },
            {"content": "Done.", "tool_calls": []},
        ])
        executor = MockToolExecutor()

        events = _collect_events(run_mini_loop(
            session_id="child-1",
            store=store,
            mailbox=mailbox,
            llm_call=llm,
            tool_executor=executor,
            tool_definitions=[],
            initial_task="Complete t-001",
        ))

        # Executor should NOT have been called (child tool routed internally)
        assert len(executor.calls) == 0

        # But task status should be updated in session metadata
        s = store.get("child-1")
        assert s.metadata.get("task_updates", {}).get("t-001", {}).get("status") == "done"

    def test_max_rounds(self, store, mailbox):
        """Loop stops at max_rounds if child never reports completion."""
        store.create(role="expert", session_id="parent-1")
        store.create(role="dev", parent_id="parent-1", session_id="child-1")

        # LLM always returns tool calls, never stops
        responses = [
            {"content": "", "tool_calls": [{"id": f"c{i}", "name": "read_file", "arguments": {}}]}
            for i in range(10)
        ]
        llm = MockLLM(responses)
        executor = MockToolExecutor()

        events = _collect_events(run_mini_loop(
            session_id="child-1",
            store=store,
            mailbox=mailbox,
            llm_call=llm,
            tool_executor=executor,
            tool_definitions=[{"name": "read_file"}],
            initial_task="Keep working",
            config=MiniLoopConfig(max_rounds=3),
        ))

        end_events = [e for e in events if e["type"] == "loop_end"]
        assert end_events[0]["reason"] == "max_rounds_reached"
        assert end_events[0]["state"]["rounds"] == 3

    def test_event_stream_completeness(self, store, mailbox):
        """Verify event stream contains round_start, tool_call, tool_result, loop_end."""
        store.create(role="expert", session_id="parent-1")
        store.create(role="dev", parent_id="parent-1", session_id="child-1")

        llm = MockLLM([
            {"content": "", "tool_calls": [{"id": "c1", "name": "test_tool", "arguments": {}}]},
            {"content": "Done.", "tool_calls": []},
        ])
        executor = MockToolExecutor({"test_tool": {"result": "ok"}})

        events = _collect_events(run_mini_loop(
            session_id="child-1",
            store=store,
            mailbox=mailbox,
            llm_call=llm,
            tool_executor=executor,
            tool_definitions=[{"name": "test_tool"}],
            initial_task="Test",
        ))

        types = [e["type"] for e in events]
        assert "round_start" in types
        assert "tool_call" in types
        assert "tool_result" in types
        assert "loop_end" in types
