"""Parent-side tools for managing child agent lifecycle.

These tool definitions are registered into the parent agent's tool set
and invoked via standard LLM tool_use calls.

Design: framework provides hard lifecycle operations (spawn/terminate/destroy);
all management decisions are made by the parent agent model.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Tuple

from agents.runtime.agent_session import AgentSessionStore, AgentStatus
from agents.runtime.mailbox import AgentMailbox
from agents.runtime.tool_profiles import resolve_child_tool_capabilities
from system.agent_profile_registry import resolve_agent_profile_defaults
from system.boxlite.manager import resolve_execution_runtime_metadata
from system.git_worktree_sandbox import (
    audit_git_worktree_sandbox,
    create_git_worktree_sandbox,
    inherit_workspace_metadata,
    normalize_workspace_mode,
    promote_git_worktree_sandbox,
    teardown_git_worktree_sandbox,
)
from system.sandbox_context import inherit_execution_metadata

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
                        "description": "Lifecycle role for the child agent: expert, dev, review.",
                    },
                    "agent_type": {
                        "type": "string",
                        "description": "Optional dynamic child-agent profile name resolved from system agent profiles.",
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
                    "execution_backend": {
                        "type": "string",
                        "enum": ["native", "boxlite"],
                        "description": "Execution backend for child tools. Defaults by runtime policy and target repo.",
                    },
                    "execution_profile": {
                        "type": "string",
                        "description": "Execution resource/isolation profile name for the selected backend.",
                    },
                    "box_profile": {
                        "type": "string",
                        "description": "Optional BoxLite box profile preset when execution_backend=boxlite.",
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
            "name": "audit_child_workspace",
            "description": (
                "Inspect a child's git worktree sandbox, persist an audit report, and return approval-ready diff facts."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "The child session whose worktree should be audited. Inherited children resolve to the owner sandbox.",
                    },
                    "change_id": {
                        "type": "string",
                        "description": "Optional stable submission/change ID. Reuses the previous audit chain when provided.",
                    },
                },
                "required": ["agent_id"],
            },
        },
        {
            "name": "promote_child_workspace",
            "description": (
                "Promote an audited child git worktree into the main repo root after explicit approval. "
                "Use only when the child is no longer running."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "The child session whose owner worktree should be promoted.",
                    },
                    "approval_ticket": {
                        "type": "string",
                        "description": "Required approval/cab ticket for the promote action.",
                    },
                    "approved_by": {
                        "type": "string",
                        "description": "Human or system approver identity recorded in the audit ledger.",
                    },
                    "change_id": {
                        "type": "string",
                        "description": "Optional audited change ID. Defaults to the last recorded workspace_change_id.",
                    },
                    "notes": {
                        "type": "string",
                        "description": "Optional approval or release notes for the promote ledger entry.",
                    },
                },
                "required": ["agent_id", "approval_ticket"],
            },
        },
        {
            "name": "teardown_child_workspace",
            "description": (
                "Discard and remove a child's owner git worktree sandbox after review or promote is complete. "
                "Use only when the owner child is no longer running."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "The child session whose owner worktree should be torn down.",
                    },
                    "change_id": {
                        "type": "string",
                        "description": "Optional stable change ID to reuse in the teardown audit event.",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Reason for discarding/tearing down the sandbox.",
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
                        "description": "Optional human-readable reason for termination.",
                    },
                },
                "required": ["agent_id"],
            },
        },
        {
            "name": "destroy_child_agent",
            "description": (
                "Permanently destroy a child agent session and release its resources. "
                "This is irreversible. Use after completion or when abandoning the task."
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
                        "description": "Optional human-readable reason for destruction.",
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
        "audit_child_workspace": _handle_audit_workspace,
        "promote_child_workspace": _handle_promote_workspace,
        "teardown_child_workspace": _handle_teardown_workspace,
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
    requested_agent_type = str(args.get("agent_type") or "").strip()
    try:
        profile_defaults = resolve_agent_profile_defaults(
            role=role,
            agent_type=requested_agent_type,
            prompt_blocks=args.get("prompt_blocks") if isinstance(args.get("prompt_blocks"), list) else None,
            tool_profile=args.get("tool_profile"),
            tool_subset=args.get("tool_subset") if isinstance(args.get("tool_subset"), list) else None,
        )
    except Exception as exc:
        return {"error": str(exc), "status": "blocked"}

    resolved_prompt_blocks = list(profile_defaults.get("prompt_blocks") or [])
    resolved_tool_profile = profile_defaults.get("tool_profile")
    resolved_tool_subset = profile_defaults.get("tool_subset") if isinstance(profile_defaults.get("tool_subset"), list) else None
    resolution = resolve_child_tool_capabilities(
        role=role,
        tool_profile=resolved_tool_profile,
        tool_subset=resolved_tool_subset,
        task_description=task_description,
    )
    requested_workspace_mode = normalize_workspace_mode(args.get("workspace_mode"))
    workspace_ref = str(args.get("workspace_ref") or "HEAD").strip() or "HEAD"
    requested_execution_backend = str(args.get("execution_backend") or "").strip()
    execution_profile = str(args.get("execution_profile") or "default").strip() or "default"
    box_profile = str(args.get("box_profile") or "default").strip() or "default"
    session_id = str(args.get("session_id") or f"agent-{uuid.uuid4().hex[:12]}").strip()
    parent_session = store.get(parent_session_id)
    parent_metadata = dict(parent_session.metadata) if parent_session is not None else {}

    if requested_workspace_mode == "inherit":
        inherited = inherit_workspace_metadata(parent_metadata)
        if inherited:
            metadata.update(inherited)
            metadata.update(inherit_execution_metadata(parent_metadata))
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
            "workspace_submission_state",
            "workspace_change_id",
            "workspace_audit_report_path",
            "workspace_audit_diff_path",
            "workspace_submission_changed_files",
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

    try:
        metadata.update(
            resolve_execution_runtime_metadata(
                requested_backend=requested_execution_backend,
                workspace_mode=str(metadata.get("workspace_mode") or requested_workspace_mode),
                workspace_root=str(metadata.get("workspace_root") or ""),
                parent_metadata=parent_metadata,
                execution_profile=execution_profile,
                box_profile=box_profile,
            )
        )
    except Exception as exc:
        return {"error": str(exc), "status": "blocked"}

    resolved_agent_type = str(profile_defaults.get("agent_type") or requested_agent_type or "").strip()
    if resolved_agent_type:
        metadata["agent_type"] = resolved_agent_type
    profile_row = profile_defaults.get("profile") if isinstance(profile_defaults.get("profile"), dict) else None
    if profile_row:
        metadata["agent_profile_label"] = str(profile_row.get("label") or "")
        metadata["agent_profile_source"] = str(profile_defaults.get("source") or "")
        metadata["agent_profile_registry_path"] = str(profile_defaults.get("registry_path") or "")

    session = store.create(
        session_id=session_id,
        role=role,
        parent_id=parent_session_id,
        task_description=task_description,
        prompt_blocks=resolved_prompt_blocks,
        tool_profile=resolution.profile_name,
        tool_subset=resolution.tool_subset,
        metadata=metadata,
    )
    return {
        "agent_id": session.session_id,
        "role": session.role,
        "agent_type": str(session.metadata.get("agent_type") or ""),
        "status": session.status.value,
        "tool_profile": session.tool_profile,
        "tool_subset": list(session.tool_subset),
        "prompt_blocks": list(session.prompt_blocks),
        "workspace_mode": str(session.metadata.get("workspace_mode") or "project"),
        "execution_backend": str(session.metadata.get("execution_backend") or "native"),
        "execution_root": str(session.metadata.get("execution_root") or ""),
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
    heartbeat_snapshot = store.get_session_heartbeat_snapshot(agent_id)
    summary["heartbeat_summary"] = dict(heartbeat_snapshot.get("summary") or {})
    summary["task_heartbeats"] = list(heartbeat_snapshot.get("heartbeats") or [])
    summary["unread_messages_from_child"] = mailbox.count_unread(parent_session_id)
    return summary


def _resolve_workspace_owner_session(
    *,
    store: AgentSessionStore,
    agent_id: str,
) -> Tuple[Any, Any, Dict[str, Any]]:
    session = store.get(agent_id)
    if not session:
        raise ValueError(f"Agent {agent_id} not found.")

    session_metadata = session.metadata if isinstance(session.metadata, dict) else {}
    owner_id = str(session_metadata.get("workspace_owner_session_id") or session.session_id or "").strip() or session.session_id
    owner_session = store.get(owner_id) if owner_id != session.session_id else session
    if owner_session is None:
        raise ValueError(f"Workspace owner session {owner_id} not found.")

    owner_metadata = owner_session.metadata if isinstance(owner_session.metadata, dict) else {}
    workspace_root = str(owner_metadata.get("workspace_root") or "").strip()
    workspace_mode = str(owner_metadata.get("workspace_mode") or "").strip().lower()
    sandbox_type = str(owner_metadata.get("workspace_sandbox_type") or "").strip().lower()
    if not workspace_root or (sandbox_type != "git_worktree" and workspace_mode != "worktree"):
        raise ValueError(f"Agent {owner_session.session_id} does not own a git worktree sandbox.")

    return session, owner_session, dict(owner_metadata)


def _require_workspace_not_running(owner_session: Any) -> None:
    if owner_session.status == AgentStatus.RUNNING:
        raise ValueError(f"Agent {owner_session.session_id} is running; wait for completion before workspace lifecycle actions.")


def _handle_audit_workspace(
    args: Dict[str, Any],
    *,
    parent_session_id: str,
    store: AgentSessionStore,
    mailbox: AgentMailbox,
) -> Dict[str, Any]:
    del mailbox
    requested_agent_id = str(args.get("agent_id") or "").strip()
    if not requested_agent_id:
        return {"error": "agent_id is required"}

    requested_session, owner_session, owner_metadata = _resolve_workspace_owner_session(
        store=store,
        agent_id=requested_agent_id,
    )
    change_id = str(args.get("change_id") or owner_metadata.get("workspace_change_id") or "").strip()
    result = audit_git_worktree_sandbox(
        owner_session_id=owner_session.session_id,
        worktree_root=str(owner_metadata.get("workspace_root") or ""),
        repo_root=str(owner_metadata.get("workspace_origin_root") or "") or None,
        base_sha=str(owner_metadata.get("workspace_head_sha") or ""),
        change_id=change_id,
        requested_by=parent_session_id,
    )
    store.update_metadata(
        owner_session.session_id,
        {
            "workspace_submission_state": "audited" if not bool(result.get("clean")) else "sandboxed",
            "workspace_change_id": str(result.get("change_id") or ""),
            "workspace_audit_report_path": str(result.get("report_path") or ""),
            "workspace_audit_diff_path": str(result.get("diff_path") or ""),
            "workspace_submission_changed_files": list(result.get("changed_files") or []),
            "workspace_audited_at": str(result.get("audit_generated_at") or ""),
            "workspace_audit_ledger_hash": str(result.get("audit_ledger_hash") or ""),
        },
    )
    return {
        **result,
        "agent_id": owner_session.session_id,
        "requested_agent_id": requested_session.session_id,
    }


def _handle_promote_workspace(
    args: Dict[str, Any],
    *,
    parent_session_id: str,
    store: AgentSessionStore,
    mailbox: AgentMailbox,
) -> Dict[str, Any]:
    del mailbox
    requested_agent_id = str(args.get("agent_id") or "").strip()
    if not requested_agent_id:
        return {"error": "agent_id is required"}

    requested_session, owner_session, owner_metadata = _resolve_workspace_owner_session(
        store=store,
        agent_id=requested_agent_id,
    )
    _require_workspace_not_running(owner_session)

    change_id = str(args.get("change_id") or owner_metadata.get("workspace_change_id") or "").strip()
    approval_ticket = str(args.get("approval_ticket") or "").strip()
    approved_by = str(args.get("approved_by") or parent_session_id).strip() or parent_session_id
    notes = str(args.get("notes") or "").strip()
    result = promote_git_worktree_sandbox(
        owner_session_id=owner_session.session_id,
        worktree_root=str(owner_metadata.get("workspace_root") or ""),
        repo_root=str(owner_metadata.get("workspace_origin_root") or "") or None,
        base_sha=str(owner_metadata.get("workspace_head_sha") or ""),
        change_id=change_id,
        requested_by=parent_session_id,
        approved_by=approved_by,
        approval_ticket=approval_ticket,
        notes=notes,
    )

    next_state = str(owner_metadata.get("workspace_submission_state") or "sandboxed")
    if str(result.get("status") or "") == "success":
        next_state = "promoted"
    elif str(result.get("status") or "") == "blocked":
        next_state = "promotion_blocked"

    store.update_metadata(
        owner_session.session_id,
        {
            "workspace_submission_state": next_state,
            "workspace_change_id": str(result.get("change_id") or change_id or ""),
            "workspace_audit_report_path": str(result.get("report_path") or owner_metadata.get("workspace_audit_report_path") or ""),
            "workspace_audit_diff_path": str(result.get("diff_path") or owner_metadata.get("workspace_audit_diff_path") or ""),
            "workspace_submission_changed_files": list(result.get("changed_files") or owner_metadata.get("workspace_submission_changed_files") or []),
            "workspace_promoted_at": str(result.get("audit_generated_at") or "") if str(result.get("status") or "") == "success" else str(owner_metadata.get("workspace_promoted_at") or ""),
            "workspace_promote_approval_ticket": approval_ticket,
            "workspace_promote_approved_by": approved_by,
            "workspace_audit_ledger_hash": str(result.get("audit_ledger_hash") or owner_metadata.get("workspace_audit_ledger_hash") or ""),
        },
    )
    return {
        **result,
        "agent_id": owner_session.session_id,
        "requested_agent_id": requested_session.session_id,
    }


def _handle_teardown_workspace(
    args: Dict[str, Any],
    *,
    parent_session_id: str,
    store: AgentSessionStore,
    mailbox: AgentMailbox,
) -> Dict[str, Any]:
    del mailbox
    requested_agent_id = str(args.get("agent_id") or "").strip()
    if not requested_agent_id:
        return {"error": "agent_id is required"}

    requested_session, owner_session, owner_metadata = _resolve_workspace_owner_session(
        store=store,
        agent_id=requested_agent_id,
    )
    _require_workspace_not_running(owner_session)

    change_id = str(args.get("change_id") or owner_metadata.get("workspace_change_id") or "").strip()
    reason = str(args.get("reason") or "").strip()
    old_workspace_root = str(owner_metadata.get("workspace_root") or "")
    result = teardown_git_worktree_sandbox(
        owner_session_id=owner_session.session_id,
        worktree_root=old_workspace_root,
        repo_root=str(owner_metadata.get("workspace_origin_root") or "") or None,
        change_id=change_id,
        requested_by=parent_session_id,
        reason=reason,
    )

    updates: Dict[str, Any] = {
        "workspace_change_id": str(result.get("change_id") or change_id or ""),
        "workspace_submission_state": "teardown_complete" if str(result.get("status") or "") == "success" else "teardown_failed",
        "workspace_teardown_at": str(result.get("audit_generated_at") or ""),
        "workspace_teardown_reason": reason,
        "workspace_teardown_error": str(result.get("error") or ""),
        "workspace_cleanup_on_destroy": False if str(result.get("status") or "") == "success" else bool(owner_metadata.get("workspace_cleanup_on_destroy", False)),
        "workspace_cleanup_success": bool(str(result.get("status") or "") == "success"),
        "workspace_cleanup_error": str(result.get("error") or ""),
        "workspace_last_root": old_workspace_root,
        "workspace_audit_ledger_hash": str(result.get("audit_ledger_hash") or owner_metadata.get("workspace_audit_ledger_hash") or ""),
    }
    if str(result.get("status") or "") == "success":
        updates["workspace_root"] = ""
    store.update_metadata(owner_session.session_id, updates)

    return {
        **result,
        "agent_id": owner_session.session_id,
        "requested_agent_id": requested_session.session_id,
    }


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
    del parent_session_id, mailbox
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
    del parent_session_id, mailbox
    agent_id = args.get("agent_id", "")
    reason = args.get("reason", "")
    session = store.get(agent_id)
    if not session:
        return {"error": f"Agent {agent_id} not found."}
    cleanup = store.destroy(agent_id, reason=reason)
    return {
        "agent_id": agent_id,
        "status": "destroyed",
        "box_cleanup_attempted": bool(cleanup.get("box_cleanup_attempted", False)),
        "box_cleanup_success": bool(cleanup.get("box_cleanup_success", True)),
        "box_cleanup_error": str(cleanup.get("box_cleanup_error") or ""),
        "workspace_cleanup_attempted": bool(cleanup.get("workspace_cleanup_attempted", False)),
        "workspace_cleanup_success": bool(cleanup.get("workspace_cleanup_success", True)),
        "workspace_cleanup_error": str(cleanup.get("workspace_cleanup_error") or ""),
        "message": f"Agent {agent_id} destroyed. All resources released.",
    }


__all__ = ["get_parent_tool_definitions", "handle_parent_tool_call"]
