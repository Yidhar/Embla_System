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

_REVIEW_VERDICTS = {"approve", "request_changes", "reject"}


# ── Tool Definitions (LLM schema) ─────────────────────────────

def get_child_tool_definitions() -> List[Dict[str, Any]]:
    """Return tool definitions for child agent to communicate with parent."""
    return [
        {
            "name": "report_to_parent",
            "description": (
                "Report status to your parent agent. "
                "Use type='completed' when your task is done and your structured verification/review payload is ready. "
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
                    "verification_report": {
                        "type": "object",
                        "description": "Required when a dev agent reports completed. Include self-verification outcomes.",
                        "properties": {
                            "tests": {
                                "type": "object",
                                "properties": {
                                    "passed": {"type": "integer"},
                                    "failed": {"type": "integer"},
                                    "errors": {"type": "integer"},
                                    "attempts": {"type": "integer"},
                                    "summary": {"type": "string"},
                                },
                            },
                            "lint": {
                                "type": "object",
                                "properties": {
                                    "status": {"type": "string"},
                                    "errors": {"type": "integer"},
                                    "summary": {"type": "string"},
                                },
                            },
                            "diff_review": {
                                "type": "object",
                                "properties": {
                                    "complete": {"type": "boolean"},
                                    "summary": {"type": "string"},
                                    "missing_items": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                },
                            },
                            "changed_files": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "risks": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "additionalProperties": True,
                    },
                    "review_result": {
                        "type": "object",
                        "description": "Required when a review agent reports completed. Include the independent review verdict.",
                        "properties": {
                            "verdict": {
                                "type": "string",
                                "enum": ["approve", "request_changes", "reject"],
                            },
                            "requirement_alignment": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "requirement": {"type": "string"},
                                        "status": {"type": "string"},
                                        "details": {"type": "string"},
                                    },
                                },
                            },
                            "code_quality": {
                                "type": "object",
                                "properties": {
                                    "status": {"type": "string"},
                                    "summary": {"type": "string"},
                                },
                                "additionalProperties": True,
                            },
                            "regression_risk": {
                                "type": "object",
                                "properties": {
                                    "level": {"type": "string"},
                                    "summary": {"type": "string"},
                                },
                                "additionalProperties": True,
                            },
                            "test_coverage": {
                                "type": "object",
                                "properties": {
                                    "status": {"type": "string"},
                                    "summary": {"type": "string"},
                                },
                                "additionalProperties": True,
                            },
                            "issues": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "suggestions": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "additionalProperties": True,
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
                        "description": "Only return messages with sequence number greater than this. Use 0 for all.",
                    },
                },
                "required": [],
            },
        },
    ]


# ── Dispatcher ────────────────────────────────────────────────

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


# ── Validation helpers ────────────────────────────────────────

def _validate_verification_report(payload: Any) -> str:
    if not isinstance(payload, dict):
        return "verification_report must be an object for dev completed reports."
    tests = payload.get("tests")
    lint = payload.get("lint")
    diff_review = payload.get("diff_review")
    changed_files = payload.get("changed_files")
    risks = payload.get("risks", [])
    if not isinstance(tests, dict):
        return "verification_report.tests must be an object."
    if not isinstance(lint, dict):
        return "verification_report.lint must be an object."
    if not isinstance(diff_review, dict):
        return "verification_report.diff_review must be an object."
    if not isinstance(changed_files, list):
        return "verification_report.changed_files must be an array."
    if not isinstance(risks, list):
        return "verification_report.risks must be an array."
    return ""



def _validate_review_result(payload: Any) -> str:
    if not isinstance(payload, dict):
        return "review_result must be an object for review completed reports."
    verdict = str(payload.get("verdict") or "").strip().lower()
    if verdict not in _REVIEW_VERDICTS:
        return "review_result.verdict must be one of approve/request_changes/reject."
    if not isinstance(payload.get("requirement_alignment"), list):
        return "review_result.requirement_alignment must be an array."
    if not isinstance(payload.get("code_quality"), dict):
        return "review_result.code_quality must be an object."
    if not isinstance(payload.get("regression_risk"), dict):
        return "review_result.regression_risk must be an object."
    if not isinstance(payload.get("test_coverage"), dict):
        return "review_result.test_coverage must be an object."
    if not isinstance(payload.get("issues"), list):
        return "review_result.issues must be an array."
    if not isinstance(payload.get("suggestions"), list):
        return "review_result.suggestions must be an array."
    return ""


# ── Handlers ──────────────────────────────────────────────────

def _handle_report(
    args: Dict[str, Any],
    *,
    child_session_id: str,
    store: AgentSessionStore,
    mailbox: AgentMailbox,
) -> Dict[str, Any]:
    report_type = str(args.get("type", "completed") or "completed").strip().lower()
    content = str(args.get("content", "") or "")
    task_status = str(args.get("task_status", "") or "")
    verification_report = args.get("verification_report")
    review_result = args.get("review_result")

    session = store.get(child_session_id)
    if not session:
        return {"error": "Own session not found."}

    parent_id = session.parent_id
    if not parent_id:
        return {"error": "No parent agent to report to."}

    if report_type == "completed":
        role = str(session.role or "").strip().lower()
        if role == "dev":
            validation_error = _validate_verification_report(verification_report)
            if validation_error:
                return {"error": validation_error, "status": session.status.value}
        elif role == "review":
            validation_error = _validate_review_result(review_result)
            if validation_error:
                return {"error": validation_error, "status": session.status.value}

    report_content = f"[{report_type.upper()}] {content}"
    if task_status:
        report_content += f"\nTask status: {task_status}"
    if report_type == "completed":
        role = str(session.role or "").strip().lower()
        if role == "dev" and isinstance(verification_report, dict):
            tests = verification_report.get("tests") if isinstance(verification_report.get("tests"), dict) else {}
            changed_files = verification_report.get("changed_files") if isinstance(verification_report.get("changed_files"), list) else []
            report_content += (
                "\nVerification: "
                f"tests(p={int(tests.get('passed', 0) or 0)}, f={int(tests.get('failed', 0) or 0)}, e={int(tests.get('errors', 0) or 0)}), "
                f"files={len(changed_files)}"
            )
        elif role == "review" and isinstance(review_result, dict):
            verdict = str(review_result.get("verdict") or "").strip().lower()
            report_content += f"\nReview verdict: {verdict}"

    seq = mailbox.send(child_session_id, parent_id, report_content, message_type="report")

    if report_type == "completed":
        metadata: Dict[str, Any] = {"completion_report": content}
        if task_status:
            metadata["task_status"] = task_status
        role = str(session.role or "").strip().lower()
        if role == "dev" and isinstance(verification_report, dict):
            metadata["verification_report"] = verification_report
            metadata["changed_files"] = list(verification_report.get("changed_files") or [])
        elif role == "review" and isinstance(review_result, dict):
            metadata["review_result"] = review_result
            metadata["review_verdict"] = str(review_result.get("verdict") or "").strip().lower()
        store.update_metadata(child_session_id, metadata)
        store.update_status(child_session_id, AgentStatus.WAITING)
        return {
            "reported": True,
            "seq": seq,
            "status": "waiting",
            "message": "Report accepted. You are now suspended. Your parent will review and decide next steps.",
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
    del mailbox
    task_id = args.get("task_id", "")
    status = args.get("status", "")
    summary = args.get("summary", "")
    files_changed = args.get("files_changed", [])

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

    sender = store.get(child_session_id)
    if not sender:
        return {"error": "Own session not found."}

    if sender.parent_id and target.parent_id and sender.parent_id != target.parent_id:
        return {"error": "Cross-expert peer messaging is not allowed."}

    seq = mailbox.send(child_session_id, target_id, str(content or ""), message_type="peer")
    return {
        "sent": True,
        "seq": seq,
        "to": target_id,
    }



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
    all_msgs = mailbox.read(child_session_id, since_seq=since_seq)
    peer_msgs = [
        m.to_dict()
        for m in all_msgs
        if m.from_id != parent_id and m.from_id != child_session_id
    ]
    return {
        "messages": peer_msgs,
        "count": len(peer_msgs),
    }


__all__ = ["get_child_tool_definitions", "handle_child_tool_call"]
