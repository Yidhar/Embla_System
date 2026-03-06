"""Unit tests for agents.runtime — Phase 1.1 + 1.2 verification.

Covers: AgentSession lifecycle, AgentSessionStore persistence,
AgentMailbox messaging, parent tools, and child tools.
"""

from __future__ import annotations

import json

import pytest

from agents.runtime.agent_session import AgentSession, AgentSessionStore, AgentStatus
from agents.runtime.child_tools import get_child_tool_definitions, handle_child_tool_call
from agents.runtime.mailbox import AgentMailbox
from agents.runtime.parent_tools import get_parent_tool_definitions, handle_parent_tool_call


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


def _verification_report(summary: str = "done"):
    return {
        "tests": {"passed": 1, "failed": 0, "errors": 0, "attempts": 1, "summary": summary},
        "lint": {"status": "passed", "errors": 0, "summary": "lint clean"},
        "diff_review": {"complete": True, "summary": summary, "missing_items": []},
        "changed_files": ["sample.py"],
        "risks": [],
    }


def _review_result(summary: str = "approved"):
    return {
        "verdict": "approve",
        "requirement_alignment": [{"requirement": "done", "status": "passed", "details": summary}],
        "code_quality": {"status": "passed", "summary": summary},
        "regression_risk": {"level": "low", "summary": summary},
        "test_coverage": {"status": "passed", "summary": summary, "missing_cases": []},
        "issues": [],
        "suggestions": [],
        "summary": summary,
    }


# ── AgentSession Tests ─────────────────────────────────────────

class TestAgentSession:

    def test_session_defaults(self):
        s = AgentSession()
        assert s.session_id.startswith("agent-")
        assert s.status == AgentStatus.RUNNING
        assert s.created_at != ""
        assert s.messages == []
        assert s.interrupt_requested is False

    def test_session_to_dict(self):
        s = AgentSession(role="dev", task_description="write code")
        d = s.to_dict()
        assert d["role"] == "dev"
        assert d["status"] == "running"
        assert isinstance(d["prompt_blocks"], list)

    def test_session_status_summary(self):
        s = AgentSession(role="expert", task_description="plan tasks")
        summary = s.to_status_summary()
        assert summary["agent_id"] == s.session_id
        assert summary["role"] == "expert"
        assert summary["status"] == "running"
        assert summary["interrupt_requested"] is False


# ── AgentSessionStore Tests ────────────────────────────────────

class TestAgentSessionStore:

    def test_create_and_get(self, store):
        session = store.create(role="dev", parent_id="parent-1", task_description="implement file_ast")
        assert session.role == "dev"
        assert session.parent_id == "parent-1"
        assert session.status == AgentStatus.RUNNING

        fetched = store.get(session.session_id)
        assert fetched is not None
        assert fetched.session_id == session.session_id
        assert fetched.task_description == "implement file_ast"

    def test_status_transitions(self, store):
        session = store.create(role="dev")
        assert session.status == AgentStatus.RUNNING

        # Running → Waiting
        store.update_status(session.session_id, AgentStatus.WAITING)
        s = store.get(session.session_id)
        assert s.status == AgentStatus.WAITING

        # Waiting → Running (resume)
        store.update_status(session.session_id, AgentStatus.RUNNING)
        s = store.get(session.session_id)
        assert s.status == AgentStatus.RUNNING
        assert s.interrupt_requested is False  # cleared on resume

    def test_list_children(self, store):
        parent_id = "parent-root"
        store.create(role="dev", parent_id=parent_id)
        store.create(role="dev", parent_id=parent_id)
        store.create(role="review", parent_id="other-parent")

        children = store.list_children(parent_id)
        assert len(children) == 2
        assert all(c.parent_id == parent_id for c in children)

    def test_destroy_makes_get_return_none(self, store):
        session = store.create(role="dev")
        store.destroy(session.session_id, reason="task complete")
        assert store.get(session.session_id) is None

    def test_destroy_excludes_from_list_children(self, store):
        session = store.create(role="dev", parent_id="parent-1")
        store.destroy(session.session_id)
        assert len(store.list_children("parent-1")) == 0

    def test_sqlite_persistence(self):
        """Create sessions, close store, reopen, verify sessions persist."""
        import tempfile, os
        db_path = os.path.join(tempfile.mkdtemp(), "test_sessions.db")

        store1 = AgentSessionStore(db_path=db_path)
        s = store1.create(role="expert", task_description="persist test")
        sid = s.session_id
        store1.close()

        store2 = AgentSessionStore(db_path=db_path)
        recovered = store2.get(sid)
        assert recovered is not None
        assert recovered.role == "expert"
        assert recovered.task_description == "persist test"
        store2.close()

    def test_interrupt_flag(self, store):
        session = store.create(role="dev")
        assert session.interrupt_requested is False

        store.set_interrupt(session.session_id)
        s = store.get(session.session_id)
        assert s.interrupt_requested is True

    def test_save_and_recover_messages(self, store):
        session = store.create(role="dev")
        messages = [
            {"role": "system", "content": "You are a dev agent."},
            {"role": "user", "content": "Implement file_ast."},
            {"role": "assistant", "content": "I'll start with the parser."},
        ]
        store.save_messages(session.session_id, messages)

        recovered = store.get(session.session_id)
        assert len(recovered.messages) == 3
        assert recovered.messages[0]["role"] == "system"
        assert recovered.messages[2]["content"] == "I'll start with the parser."

    def test_update_metadata(self, store):
        session = store.create(role="dev")
        store.update_metadata(session.session_id, {"progress": "50%", "files": ["a.py"]})
        s = store.get(session.session_id)
        assert s.metadata["progress"] == "50%"

    def test_cannot_update_destroyed_session(self, store):
        session = store.create(role="dev")
        store.destroy(session.session_id)
        with pytest.raises(ValueError, match="Cannot update destroyed"):
            store.update_status(session.session_id, AgentStatus.RUNNING)

    def test_duplicate_session_id_raises(self, store):
        store.create(role="dev", session_id="fixed-id")
        with pytest.raises(ValueError, match="already exists"):
            store.create(role="dev", session_id="fixed-id")


# ── Mailbox Tests ──────────────────────────────────────────────

class TestAgentMailbox:

    def test_send_and_read(self, mailbox):
        seq = mailbox.send("parent-1", "child-1", "Start working")
        assert seq > 0

        msgs = mailbox.read("child-1")
        assert len(msgs) == 1
        assert msgs[0].from_id == "parent-1"
        assert msgs[0].content == "Start working"
        assert msgs[0].seq == seq

    def test_read_since_seq(self, mailbox):
        s1 = mailbox.send("a", "b", "msg 1")
        s2 = mailbox.send("a", "b", "msg 2")
        s3 = mailbox.send("a", "b", "msg 3")

        msgs = mailbox.read("b", since_seq=s1)
        assert len(msgs) == 2
        assert msgs[0].content == "msg 2"
        assert msgs[1].content == "msg 3"

    def test_read_empty_inbox(self, mailbox):
        msgs = mailbox.read("nonexistent-agent")
        assert msgs == []

    def test_read_latest(self, mailbox):
        mailbox.send("a", "b", "first")
        mailbox.send("a", "b", "second")
        mailbox.send("a", "b", "third")

        latest = mailbox.read_latest("b")
        assert latest is not None
        assert latest.content == "third"

    def test_count_unread(self, mailbox):
        mailbox.send("a", "b", "msg 1")
        s2 = mailbox.send("a", "b", "msg 2")
        mailbox.send("a", "b", "msg 3")

        assert mailbox.count_unread("b") == 3
        assert mailbox.count_unread("b", since_seq=s2) == 1

    def test_message_type_filter(self, mailbox):
        mailbox.send("a", "b", "hello", message_type="info")
        mailbox.send("a", "b", "done!", message_type="report")
        mailbox.send("a", "b", "hey", message_type="info")

        reports = mailbox.read("b", message_type="report")
        assert len(reports) == 1
        assert reports[0].content == "done!"

    def test_purge_agent_messages(self, mailbox):
        mailbox.send("parent-1", "agent-a", "to a")
        mailbox.send("agent-a", "parent-1", "from a")
        mailbox.send("parent-1", "agent-b", "to b")
        mailbox.send("agent-b", "parent-1", "from b")

        purged = mailbox.purge_agent_messages(["agent-a"])
        assert purged == 2
        assert len(mailbox.read("agent-a")) == 0

        parent_msgs = mailbox.read("parent-1")
        assert len(parent_msgs) == 1
        assert parent_msgs[0].from_id == "agent-b"


# ── Parent Tools Tests ─────────────────────────────────────────

class TestParentTools:

    def test_tool_definitions_complete(self):
        defs = get_parent_tool_definitions()
        names = {d["name"] for d in defs}
        assert names == {
            "spawn_child_agent",
            "poll_child_status",
            "send_message_to_child",
            "resume_child_agent",
            "terminate_child_agent",
            "destroy_child_agent",
        }

    def test_spawn_and_poll(self, store, mailbox):
        result = handle_parent_tool_call(
            "spawn_child_agent",
            {"role": "dev", "task_description": "write code"},
            parent_session_id="parent-1",
            store=store,
            mailbox=mailbox,
        )
        assert "agent_id" in result
        assert result["status"] == "running"

        poll = handle_parent_tool_call(
            "poll_child_status",
            {"agent_id": result["agent_id"]},
            parent_session_id="parent-1",
            store=store,
            mailbox=mailbox,
        )
        assert poll["status"] == "running"
        assert poll["role"] == "dev"

    def test_spawn_child_agent_passes_metadata(self, store, mailbox):
        result = handle_parent_tool_call(
            "spawn_child_agent",
            {
                "role": "dev",
                "task_description": "write code",
                "metadata": {"pipeline_id": "pipe_001", "trace_id": "trace_001"},
            },
            parent_session_id="parent-1",
            store=store,
            mailbox=mailbox,
        )
        session = store.get(result["agent_id"])
        assert session is not None
        assert session.metadata["pipeline_id"] == "pipe_001"
        assert session.metadata["trace_id"] == "trace_001"

    def test_terminate_and_resume(self, store, mailbox):
        spawn = handle_parent_tool_call(
            "spawn_child_agent",
            {"role": "dev", "task_description": "task"},
            parent_session_id="parent-1",
            store=store,
            mailbox=mailbox,
        )
        aid = spawn["agent_id"]

        # Terminate
        term = handle_parent_tool_call(
            "terminate_child_agent",
            {"agent_id": aid, "reason": "stuck"},
            parent_session_id="parent-1",
            store=store,
            mailbox=mailbox,
        )
        assert term["status"] == "waiting"

        # Resume
        res = handle_parent_tool_call(
            "resume_child_agent",
            {"agent_id": aid, "instruction": "try a different approach"},
            parent_session_id="parent-1",
            store=store,
            mailbox=mailbox,
        )
        assert res["status"] == "running"

    def test_destroy(self, store, mailbox):
        spawn = handle_parent_tool_call(
            "spawn_child_agent",
            {"role": "dev", "task_description": "temp"},
            parent_session_id="parent-1",
            store=store,
            mailbox=mailbox,
        )
        aid = spawn["agent_id"]

        dest = handle_parent_tool_call(
            "destroy_child_agent",
            {"agent_id": aid, "reason": "done"},
            parent_session_id="parent-1",
            store=store,
            mailbox=mailbox,
        )
        assert dest["status"] == "destroyed"

        poll = handle_parent_tool_call(
            "poll_child_status",
            {"agent_id": aid},
            parent_session_id="parent-1",
            store=store,
            mailbox=mailbox,
        )
        assert "error" in poll

    def test_send_message(self, store, mailbox):
        spawn = handle_parent_tool_call(
            "spawn_child_agent",
            {"role": "dev", "task_description": "task"},
            parent_session_id="parent-1",
            store=store,
            mailbox=mailbox,
        )
        aid = spawn["agent_id"]

        send = handle_parent_tool_call(
            "send_message_to_child",
            {"agent_id": aid, "content": "priority update"},
            parent_session_id="parent-1",
            store=store,
            mailbox=mailbox,
        )
        assert send["sent"] is True

        msgs = mailbox.read(aid)
        assert len(msgs) == 1
        assert msgs[0].content == "priority update"


# ── Child Tools Tests ──────────────────────────────────────────

class TestChildTools:

    def test_tool_definitions_complete(self):
        defs = get_child_tool_definitions()
        names = {d["name"] for d in defs}
        assert names == {
            "report_to_parent",
            "read_parent_messages",
            "update_my_task_status",
            "send_message_to_agent",
            "read_agent_messages",
        }

    def test_report_completed_transitions_to_waiting(self, store, mailbox):
        parent = store.create(role="expert", session_id="parent-1")
        child = store.create(role="dev", parent_id="parent-1", session_id="child-1")

        result = handle_child_tool_call(
            "report_to_parent",
            {"type": "completed", "content": "All tasks done", "task_status": "5/5", "verification_report": _verification_report("All tasks done")},
            child_session_id="child-1",
            store=store,
            mailbox=mailbox,
        )
        assert result["status"] == "waiting"

        s = store.get("child-1")
        assert s.status == AgentStatus.WAITING

        # Parent should have received the report
        msgs = mailbox.read("parent-1")
        assert len(msgs) == 1
        assert "[COMPLETED]" in msgs[0].content

    def test_report_error_stays_running(self, store, mailbox):
        store.create(role="expert", session_id="parent-1")
        store.create(role="dev", parent_id="parent-1", session_id="child-1")

        result = handle_child_tool_call(
            "report_to_parent",
            {"type": "error", "content": "Build failed"},
            child_session_id="child-1",
            store=store,
            mailbox=mailbox,
        )
        assert result["status"] == "running"

    def test_report_completed_requires_structured_payload(self, store, mailbox):
        store.create(role="expert", session_id="parent-1")
        store.create(role="dev", parent_id="parent-1", session_id="child-1")

        result = handle_child_tool_call(
            "report_to_parent",
            {"type": "completed", "content": "missing verification"},
            child_session_id="child-1",
            store=store,
            mailbox=mailbox,
        )
        assert result["error"].startswith("verification_report")
        assert store.get("child-1").status == AgentStatus.RUNNING

    def test_review_completed_stores_review_result(self, store, mailbox):
        store.create(role="expert", session_id="parent-1")
        store.create(role="review", parent_id="parent-1", session_id="review-1")

        result = handle_child_tool_call(
            "report_to_parent",
            {"type": "completed", "content": "review done", "review_result": _review_result("review done")},
            child_session_id="review-1",
            store=store,
            mailbox=mailbox,
        )
        assert result["status"] == "waiting"
        review_session = store.get("review-1")
        assert review_session.metadata["review_result"]["verdict"] == "approve"

    def test_read_parent_messages(self, store, mailbox):
        store.create(role="expert", session_id="parent-1")
        store.create(role="dev", parent_id="parent-1", session_id="child-1")

        mailbox.send("parent-1", "child-1", "instruction 1")
        mailbox.send("parent-1", "child-1", "instruction 2")
        mailbox.send("other-agent", "child-1", "peer msg")  # should be filtered out

        result = handle_child_tool_call(
            "read_parent_messages",
            {},
            child_session_id="child-1",
            store=store,
            mailbox=mailbox,
        )
        assert result["count"] == 2  # only parent messages

    def test_update_task_status(self, store, mailbox):
        store.create(role="dev", session_id="child-1")

        result = handle_child_tool_call(
            "update_my_task_status",
            {"task_id": "t-001", "status": "done", "summary": "AST parser complete"},
            child_session_id="child-1",
            store=store,
            mailbox=mailbox,
        )
        assert result["updated"] is True

        s = store.get("child-1")
        assert s.metadata["task_updates"]["t-001"]["status"] == "done"

    def test_peer_messaging(self, store, mailbox):
        store.create(role="expert", session_id="expert-1")
        store.create(role="dev", parent_id="expert-1", session_id="dev-a")
        store.create(role="dev", parent_id="expert-1", session_id="dev-b")

        # dev-a sends to dev-b
        result = handle_child_tool_call(
            "send_message_to_agent",
            {"target_agent_id": "dev-b", "content": "What's the API schema?"},
            child_session_id="dev-a",
            store=store,
            mailbox=mailbox,
        )
        assert result["sent"] is True

        # dev-b reads peer messages
        result = handle_child_tool_call(
            "read_agent_messages",
            {},
            child_session_id="dev-b",
            store=store,
            mailbox=mailbox,
        )
        assert result["count"] == 1
        assert "API schema" in result["messages"][0]["content"]
