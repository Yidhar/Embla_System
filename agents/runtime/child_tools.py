"""Child-side tools for communicating with the parent agent.

These tools are registered into the child agent's tool set and invoked
via standard LLM tool_use calls during the child's mini tool-loop.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from agents.runtime.agent_session import AgentSessionStore, AgentStatus
from agents.runtime.mailbox import AgentMailbox

logger = logging.getLogger(__name__)


# ── Tool Definitions (LLM schema) ─────────────────────────────

def get_child_tool_definitions() -> List[Dict[str, Any]]:
    """Return tool definitions for child agent to communicate with parent."""
    return [
        {
            "name": "report_to_parent",
            "description": (
                "Report status to your parent agent. "
                "Use type='completed' when your task is done — you will be suspended "
                "and your parent will review your output. "
                "Use type='blocked' or 'error' when you need help. "
                "Use type='question' to ask your parent for clarification."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["completed", "blocked", "error", "question"],
                        "description": "Report type.",
                    },
                    "content": {
                        "type": "string",
                        "description": "Report content: summary of work done, error details, or question.",
                    },
                    "task_status": {
                        "type": "string",
                        "description": "Brief status of your assigned task(s).",
                    },
                },
                "required": ["type", "content"],
            },
        },
        {
            "name": "read_parent_messages",
            "description": (
                "Read messages sent to you by your parent agent. "
                "Call this periodically to check for new instructions or feedback."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "since_seq": {
                        "type": "integer",
                        "description": "Only return messages with sequence number greater than this. Use 0 for all.",
                    },
                },
                "required": [],
            },
        },
        {
            "name": "update_my_task_status",
            "description": (
                "Update the status of a task assigned to you on the TaskBoard. "
                "Call this as you make progress on your assigned tasks."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "The task ID from the TaskBoard.",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["in_progress", "blocked", "done", "failed"],
                        "description": "New status for the task.",
                    },
                    "summary": {
                        "type": "string",
                        "description": "Brief summary of progress or result.",
                    },
                    "files_changed": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of files created or modified.",
                    },
                },
                "required": ["task_id", "status"],
            },
        },
        {
            "name": "send_message_to_agent",
            "description": (
                "Send a message to a peer agent (e.g. another Dev agent). "
                "Messages are routed through your Expert agent for oversight."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "target_agent_id": {
                        "type": "string",
                        "description": "The session ID of the target peer agent.",
                    },
                    "content": {
                        "type": "string",
                        "description": "Message content.",
                    },
                },
                "required": ["target_agent_id", "content"],
            },
        },
        {
            "name": "read_agent_messages",
            "description": "Read messages sent to you by peer agents.",
            "parameters": {
                "type": "object",
                "properties": {
                    "since_seq": {
                        "type": "integer",
                        "description": "Only return messages after this sequence number.",
                    },
                },
                "required": [],
            },
        },
    ]


# ── Tool Handlers ──────────────────────────────────────────────

def handle_child_tool_call(
    tool_name: str,
    arguments: Dict[str, Any],
    *,
    child_session_id: str,
    store: AgentSessionStore,
    mailbox: AgentMailbox,
) -> Dict[str, Any]:
    """Dispatch a child tool call to the appropriate handler."""
    handlers = {
        "report_to_parent": _handle_report,
        "read_parent_messages": _handle_read_parent,
        "update_my_task_status": _handle_update_task,
        "send_message_to_agent": _handle_send_peer,
        "read_agent_messages": _handle_read_peer,
    }
    handler = handlers.get(tool_name)
    if not handler:
        return {"error": f"Unknown child tool: {tool_name}"}
    try:
        return handler(
            arguments,
            child_session_id=child_session_id,
            store=store,
            mailbox=mailbox,
        )
    except Exception as exc:
        logger.exception("Child tool %s failed", tool_name)
        return {"error": str(exc)}


def _handle_report(
    args: Dict[str, Any],
    *,
    child_session_id: str,
    store: AgentSessionStore,
    mailbox: AgentMailbox,
) -> Dict[str, Any]:
    report_type = args.get("type", "completed")
    content = args.get("content", "")
    task_status = args.get("task_status", "")

    session = store.get(child_session_id)
    if not session:
        return {"error": "Own session not found."}

    parent_id = session.parent_id
    if not parent_id:
        return {"error": "No parent agent to report to."}

    # Build report message
    report_content = f"[{report_type.upper()}] {content}"
    if task_status:
        report_content += f"\nTask status: {task_status}"

    seq = mailbox.send(child_session_id, parent_id, report_content, message_type="report")

    # If completed, transition self to Waiting
    if report_type == "completed":
        store.update_status(child_session_id, AgentStatus.WAITING)
        store.update_metadata(child_session_id, {"completion_report": content})
        return {
            "reported": True,
            "seq": seq,
            "status": "waiting",
            "message": "Report sent. You are now suspended. Your parent will review and decide next steps.",
        }

    return {"reported": True, "seq": seq, "status": session.status.value}


def _handle_read_parent(
    args: Dict[str, Any],
    *,
    child_session_id: str,
    store: AgentSessionStore,
    mailbox: AgentMailbox,
) -> Dict[str, Any]:
    since_seq = args.get("since_seq", 0)
    session = store.get(child_session_id)
    if not session:
        return {"error": "Own session not found."}

    parent_id = session.parent_id
    # Read messages from parent (filter by from_id == parent_id)
    all_msgs = mailbox.read(child_session_id, since_seq=since_seq)
    parent_msgs = [m.to_dict() for m in all_msgs if m.from_id == parent_id]

    return {
        "messages": parent_msgs,
        "count": len(parent_msgs),
    }


def _handle_update_task(
    args: Dict[str, Any],
    *,
    child_session_id: str,
    store: AgentSessionStore,
    mailbox: AgentMailbox,
) -> Dict[str, Any]:
    task_id = args.get("task_id", "")
    status = args.get("status", "")
    summary = args.get("summary", "")
    files_changed = args.get("files_changed", [])

    # Store task progress in session metadata (TaskBoard engine will integrate later)
    session = store.get(child_session_id)
    if not session:
        return {"error": "Own session not found."}

    task_updates = session.metadata.get("task_updates", {})
    task_updates[task_id] = {
        "status": status,
        "summary": summary,
        "files_changed": files_changed,
    }
    store.update_metadata(child_session_id, {"task_updates": task_updates})

    return {
        "updated": True,
        "task_id": task_id,
        "status": status,
        "message": f"Task {task_id} updated to '{status}'.",
    }


def _handle_send_peer(
    args: Dict[str, Any],
    *,
    child_session_id: str,
    store: AgentSessionStore,
    mailbox: AgentMailbox,
) -> Dict[str, Any]:
    target_id = args.get("target_agent_id", "")
    content = args.get("content", "")

    target = store.get(target_id)
    if not target:
        return {"error": f"Peer agent {target_id} not found."}

    # Peer messages go via mailbox (Expert relay enforcement is done at a higher level)
    seq = mailbox.send(child_session_id, target_id, content, message_type="info")
    return {"sent": True, "seq": seq, "to": target_id}


def _handle_read_peer(
    args: Dict[str, Any],
    *,
    child_session_id: str,
    store: AgentSessionStore,
    mailbox: AgentMailbox,
) -> Dict[str, Any]:
    since_seq = args.get("since_seq", 0)
    session = store.get(child_session_id)
    if not session:
        return {"error": "Own session not found."}

    parent_id = session.parent_id
    # Read all messages that are NOT from parent (i.e. peer messages)
    all_msgs = mailbox.read(child_session_id, since_seq=since_seq)
    peer_msgs = [m.to_dict() for m in all_msgs if m.from_id != parent_id]

    return {
        "messages": peer_msgs,
        "count": len(peer_msgs),
    }


__all__ = ["get_child_tool_definitions", "handle_child_tool_call"]
