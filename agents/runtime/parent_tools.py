"""Parent-side tools for managing child agent lifecycle.

These tool definitions are registered into the parent agent's tool set
and invoked via standard LLM tool_use calls.

Design: framework provides hard lifecycle operations (spawn/terminate/destroy);
all management decisions are made by the parent agent model.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List

from agents.runtime.agent_session import AgentSessionStore, AgentStatus
from agents.runtime.mailbox import AgentMailbox
from agents.runtime.tool_profiles import resolve_child_tool_capabilities
from system.git_worktree_sandbox import create_git_worktree_sandbox, inherit_workspace_metadata, normalize_workspace_mode

logger = logging.getLogger(__name__)


# ── Tool Definitions (LLM schema) ─────────────────────────────

def get_parent_tool_definitions() -> List[Dict[str, Any]]:
    """Return tool definitions for parent agent to manage children."""
    return [
        {
            "name": "spawn_child_agent",
            "description": (
                "Create a new child agent with a specific role and task. "
                "The child will start running immediately with its own LLM session."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "role": {
                        "type": "string",
                        "description": "Agent role: expert, dev, review, etc.",
                    },
                    "task_description": {
                        "type": "string",
                        "description": "The task to assign to the child agent.",
                    },
                    "prompt_blocks": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Ordered list of prompt block paths to compose the child's system prompt.",
                    },
                    "tool_profile": {
                        "description": "Preset tool profile name (refactor/new_doc/bugfix/review/cleanup/custom) or explicit tool-name list.",
                    },
                    "tool_subset": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Legacy explicit list of tool names the child agent is allowed to use.",
                    },
                    "workspace_mode": {
                        "type": "string",
                        "enum": ["inherit", "project", "worktree"],
                        "description": "Workspace mode for the child: inherit parent sandbox, stay on project root, or create a new git worktree sandbox.",
                    },
                    "workspace_ref": {
                        "type": "string",
                        "description": "Git ref used when workspace_mode=worktree. Defaults to HEAD.",
                    },
                    "metadata": {
                        "type": "object",
                        "description": "Additional runtime metadata persisted on the child session.",
                        "additionalProperties": True,
                    },
                },
                "required": ["role", "task_description"],
            },
        },
        {
            "name": "poll_child_status",
            "description": (
                "Check the current status of a child agent. "
                "Returns factual data only — no automated judgments or recommendations."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "The session ID of the child agent to check.",
                    },
                },
                "required": ["agent_id"],
            },
        },
        {
            "name": "send_message_to_child",
            "description": "Send a message to a child agent's inbox.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "The session ID of the target child agent.",
                    },
                    "content": {
                        "type": "string",
                        "description": "The message content to send.",
                    },
                },
                "required": ["agent_id", "content"],
            },
        },
        {
            "name": "resume_child_agent",
            "description": (
                "Resume a child agent that is in Waiting state. "
                "Injects a new instruction and restores the agent to Running. "
                "The child retains its full conversation history."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "The session ID of the child agent to resume.",
                    },
                    "instruction": {
                        "type": "string",
                        "description": "New instruction for the child (e.g. rework request, additional task).",
                    },
                },
                "required": ["agent_id", "instruction"],
            },
        },
        {
            "name": "terminate_child_agent",
            "description": (
                "Force-stop a running child agent. "
                "The child transitions to Waiting state with its session preserved. "
                "Use this when a child appears stuck or unresponsive."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "The session ID of the child agent to terminate.",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Reason for termination.",
                    },
                },
                "required": ["agent_id", "reason"],
            },
        },
        {
            "name": "destroy_child_agent",
            "description": (
                "Permanently destroy a child agent, releasing all resources. "
                "The session history is discarded. Only use after reviewing the child's output."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "The session ID of the child agent to destroy.",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Reason for destruction.",
                    },
                },
                "required": ["agent_id"],
            },
        },
    ]


# ── Tool Handlers ──────────────────────────────────────────────

def handle_parent_tool_call(
    tool_name: str,
    arguments: Dict[str, Any],
    *,
    parent_session_id: str,
    store: AgentSessionStore,
    mailbox: AgentMailbox,
) -> Dict[str, Any]:
    """Dispatch a parent tool call to the appropriate handler.

    Returns a dict suitable for LLM consumption as tool result.
    """
    handlers = {
        "spawn_child_agent": _handle_spawn,
        "poll_child_status": _handle_poll,
        "send_message_to_child": _handle_send_message,
        "resume_child_agent": _handle_resume,
        "terminate_child_agent": _handle_terminate,
        "destroy_child_agent": _handle_destroy,
    }
    handler = handlers.get(tool_name)
    if not handler:
        return {"error": f"Unknown parent tool: {tool_name}"}
    try:
        return handler(
            arguments,
            parent_session_id=parent_session_id,
            store=store,
            mailbox=mailbox,
        )
    except Exception as exc:
        logger.exception("Parent tool %s failed", tool_name)
        return {"error": str(exc)}


def _handle_spawn(
    args: Dict[str, Any],
    *,
    parent_session_id: str,
    store: AgentSessionStore,
    mailbox: AgentMailbox,
) -> Dict[str, Any]:
    del mailbox
    raw_metadata = args.get("metadata")
    metadata = dict(raw_metadata) if isinstance(raw_metadata, dict) else {}
    role = str(args.get("role", "dev") or "dev").strip() or "dev"
    task_description = str(args.get("task_description", "") or "")
    resolution = resolve_child_tool_capabilities(
        role=role,
        tool_profile=args.get("tool_profile"),
        tool_subset=args.get("tool_subset") if isinstance(args.get("tool_subset"), list) else None,
        task_description=task_description,
    )
    requested_workspace_mode = normalize_workspace_mode(args.get("workspace_mode"))
    workspace_ref = str(args.get("workspace_ref") or "HEAD").strip() or "HEAD"
    session_id = str(args.get("session_id") or f"agent-{uuid.uuid4().hex[:12]}").strip()
    parent_session = store.get(parent_session_id)
    parent_metadata = dict(parent_session.metadata) if parent_session is not None else {}

    if requested_workspace_mode == "inherit":
        inherited = inherit_workspace_metadata(parent_metadata)
        if inherited:
            metadata.update(inherited)
            metadata["workspace_mode"] = "inherit"
        else:
            metadata.setdefault("workspace_mode", "project")
    elif requested_workspace_mode == "project":
        metadata["workspace_mode"] = "project"
        for key in (
            "workspace_sandbox_type",
            "workspace_origin_root",
            "workspace_root",
            "workspace_ref",
            "workspace_head_sha",
            "workspace_owner_session_id",
            "workspace_cleanup_on_destroy",
            "workspace_created_at",
        ):
            metadata.pop(key, None)
    elif requested_workspace_mode == "worktree":
        sandbox = create_git_worktree_sandbox(
            owner_session_id=session_id,
            ref=workspace_ref,
            repo_root=parent_metadata.get("workspace_origin_root") or None,
        )
        metadata.update(sandbox.to_metadata())
    else:
        return {"error": f"unsupported workspace_mode: {requested_workspace_mode}", "status": "blocked"}

    session = store.create(
        session_id=session_id,
        role=role,
        parent_id=parent_session_id,
        task_description=task_description,
        prompt_blocks=args.get("prompt_blocks"),
        tool_profile=resolution.profile_name,
        tool_subset=resolution.tool_subset,
        metadata=metadata,
    )
    return {
        "agent_id": session.session_id,
        "role": session.role,
        "status": session.status.value,
        "tool_profile": session.tool_profile,
        "tool_subset": list(session.tool_subset),
        "workspace_mode": str(session.metadata.get("workspace_mode") or "project"),
        "workspace_root": str(session.metadata.get("workspace_root") or ""),
        "message": f"Child agent {session.session_id} created and running.",
    }


def _handle_poll(
    args: Dict[str, Any],
    *,
    parent_session_id: str,
    store: AgentSessionStore,
    mailbox: AgentMailbox,
) -> Dict[str, Any]:
    agent_id = args.get("agent_id", "")
    session = store.get(agent_id)
    if not session:
        return {"error": f"Agent {agent_id} not found or already destroyed."}
    summary = session.to_status_summary()
    # Add unread message count from parent
    summary["unread_messages_from_child"] = mailbox.count_unread(parent_session_id)
    return summary


def _handle_send_message(
    args: Dict[str, Any],
    *,
    parent_session_id: str,
    store: AgentSessionStore,
    mailbox: AgentMailbox,
) -> Dict[str, Any]:
    agent_id = args.get("agent_id", "")
    content = args.get("content", "")
    session = store.get(agent_id)
    if not session:
        return {"error": f"Agent {agent_id} not found."}
    seq = mailbox.send(parent_session_id, agent_id, content, message_type="info")
    return {"sent": True, "seq": seq, "to": agent_id}


def _handle_resume(
    args: Dict[str, Any],
    *,
    parent_session_id: str,
    store: AgentSessionStore,
    mailbox: AgentMailbox,
) -> Dict[str, Any]:
    agent_id = args.get("agent_id", "")
    instruction = args.get("instruction", "")
    session = store.get(agent_id)
    if not session:
        return {"error": f"Agent {agent_id} not found."}
    if session.status != AgentStatus.WAITING:
        return {"error": f"Agent {agent_id} is {session.status.value}, not waiting. Cannot resume."}
    # Send the instruction as a message
    if instruction:
        mailbox.send(parent_session_id, agent_id, instruction, message_type="system")
    store.update_status(agent_id, AgentStatus.RUNNING)
    return {
        "agent_id": agent_id,
        "status": "running",
        "message": f"Agent {agent_id} resumed with new instruction.",
    }


def _handle_terminate(
    args: Dict[str, Any],
    *,
    parent_session_id: str,
    store: AgentSessionStore,
    mailbox: AgentMailbox,
) -> Dict[str, Any]:
    agent_id = args.get("agent_id", "")
    reason = args.get("reason", "")
    session = store.get(agent_id)
    if not session:
        return {"error": f"Agent {agent_id} not found."}
    if session.status != AgentStatus.RUNNING:
        return {"error": f"Agent {agent_id} is {session.status.value}, not running."}
    # Set interrupt flag (child checks this at next loop iteration)
    store.set_interrupt(agent_id)
    # Also transition to waiting immediately for hard terminate
    store.update_status(agent_id, AgentStatus.WAITING)
    store.update_metadata(agent_id, {"terminate_reason": reason})
    return {
        "agent_id": agent_id,
        "status": "waiting",
        "message": f"Agent {agent_id} terminated. Session preserved for resume or destroy.",
    }


def _handle_destroy(
    args: Dict[str, Any],
    *,
    parent_session_id: str,
    store: AgentSessionStore,
    mailbox: AgentMailbox,
) -> Dict[str, Any]:
    agent_id = args.get("agent_id", "")
    reason = args.get("reason", "")
    store.destroy(agent_id, reason=reason)
    return {
        "agent_id": agent_id,
        "status": "destroyed",
        "message": f"Agent {agent_id} destroyed. All resources released.",
    }


__all__ = ["get_parent_tool_definitions", "handle_parent_tool_call"]
