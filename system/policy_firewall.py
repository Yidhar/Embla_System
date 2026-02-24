"""
Policy firewall for native tool calls.

WS14-001:
- capability allowlist
- basic argv schema checks for run_cmd
- reject+audit suspicious command obfuscation patterns
"""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Set


@dataclass(frozen=True)
class FirewallDecision:
    allowed: bool
    reason: str = ""
    rule_id: str = ""
    audit_id: str = ""


class PolicyFirewall:
    PROJECT_ROOT = Path(r"E:\Programs\NagaAgent").resolve()

    _ALLOWED_NATIVE_TOOLS: Set[str] = {
        "read_file",
        "write_file",
        "get_cwd",
        "run_cmd",
        "search_keyword",
        "query_docs",
        "list_files",
        "git_status",
        "git_diff",
        "git_log",
        "git_show",
        "git_blame",
        "git_grep",
        "git_changed_files",
        "git_checkout_file",
        "python_repl",
        "artifact_reader",
        "file_ast_skeleton",
        "file_ast_chunk_read",
        "workspace_txn_apply",
        "sleep_and_watch",
        "killswitch_plan",
    }

    # Only enforce strict argument schema for high-risk tools.
    _TOOL_ALLOWED_ARGS: Dict[str, Set[str]] = {
        "run_cmd": {
            "tool_name",
            "command",
            "cmd",
            "cwd",
            "timeout_seconds",
            "max_output_chars",
            "artifact_priority",
            "approvalPolicy",
            "approval_policy",
            "approval_granted",
            "approved",
        },
        "write_file": {
            "tool_name",
            "path",
            "file_path",
            "content",
            "mode",
            "encoding",
            "requester",
            "approvalPolicy",
            "approval_policy",
            "approval_granted",
            "approved",
        },
        "workspace_txn_apply": {
            "tool_name",
            "changes",
            "contract_id",
            "contract_checksum",
            "verify_after_apply",
            "requester",
            "approvalPolicy",
            "approval_policy",
            "approval_granted",
            "approved",
        },
        "sleep_and_watch": {
            "tool_name",
            "log_file",
            "pattern",
            "regex",
            "timeout_seconds",
            "poll_interval_seconds",
            "from_end",
            "max_line_chars",
        },
        "killswitch_plan": {
            "tool_name",
            "mode",
            "oob_allowlist",
            "dns_allow",
        },
    }

    _RUN_CMD_BLOCKED_PROGRAMS = {
        "rm",
        "del",
        "erase",
        "rmdir",
        "rd",
        "diskpart",
        "format",
    }
    _RUN_CMD_ALLOWED_PROGRAMS = {
        "git",
        "rg",
        "findstr",
        "dir",
        "type",
        "echo",
        "where",
        "python",
        "python3",
        "uv",
        "pytest",
        "pip",
        "npm",
        "node",
        "powershell",
        "pwsh",
        "cmd",
        "curl",
        "kubectl",
        "docker",
    }

    _OBFUSCATION_PATTERNS = (
        # x="r"; y="m"; $x$y -rf /
        (
            r"(?is)\b[A-Za-z_]\w*\s*=\s*['\"][^'\"]+['\"]\s*;\s*\b[A-Za-z_]\w*\s*=\s*['\"][^'\"]+['\"]\s*;\s*\$[A-Za-z_]\w+\$[A-Za-z_]\w+",
            "OBFUSCATION_VAR_CONCAT",
        ),
        # set x=r & set y=m & %x%%y% /...
        (
            r"(?is)\bset\s+[A-Za-z_]\w*=.+?&\s*set\s+[A-Za-z_]\w*=.+?&\s*%[A-Za-z_]\w+%%[A-Za-z_]\w+%",
            "OBFUSCATION_ENV_CONCAT",
        ),
        # echo base64 | base64 -d | sh
        (
            r"(?is)base64\s+-d\s*\|\s*(?:bash|sh|cmd|powershell|pwsh)\b",
            "OBFUSCATION_BASE64_PIPE",
        ),
    )

    def __init__(self, audit_file: Optional[Path] = None) -> None:
        self.audit_file = audit_file or (self.PROJECT_ROOT / "logs" / "security" / "policy_firewall_audit.jsonl")
        self.audit_file.parent.mkdir(parents=True, exist_ok=True)

    def validate_native_call(self, tool_name: str, call: Dict[str, Any]) -> FirewallDecision:
        normalized_tool = (tool_name or "").strip().lower()
        if not normalized_tool:
            return self._deny("MISSING_TOOL_NAME", "tool_name is empty", normalized_tool, call)

        if normalized_tool not in self._ALLOWED_NATIVE_TOOLS:
            return self._deny(
                "CAPABILITY_NOT_ALLOWLISTED",
                f"Capability not allowlisted: {normalized_tool}",
                normalized_tool,
                call,
            )

        allowed_args = self._TOOL_ALLOWED_ARGS.get(normalized_tool)
        if allowed_args is not None:
            unknown = [
                k
                for k in call.keys()
                if not str(k).startswith("_")
                and str(k) not in {"agentType", "service_name"}
                and str(k) not in allowed_args
            ]
            if unknown:
                return self._deny(
                    "INVALID_ARGV_SCHEMA",
                    f"Unsupported argument(s) for {normalized_tool}: {', '.join(sorted(unknown))}",
                    normalized_tool,
                    call,
                )

        if normalized_tool == "run_cmd":
            return self._validate_run_cmd(call)

        return FirewallDecision(allowed=True)

    @staticmethod
    def _extract_program(command: str) -> str:
        cmd = (command or "").strip()
        if not cmd:
            return ""

        if cmd[0] in {"'", '"'}:
            quote = cmd[0]
            end = cmd.find(quote, 1)
            token = cmd[1:end] if end > 0 else cmd[1:]
        else:
            token = re.split(r"\s+", cmd, maxsplit=1)[0]

        token = Path(token).name.lower()
        if token.endswith((".exe", ".cmd", ".bat", ".com")):
            token = Path(token).stem.lower()
        return token

    def _validate_run_cmd(self, call: Dict[str, Any]) -> FirewallDecision:
        command = str(call.get("command") or call.get("cmd") or "").strip()
        if not command:
            return self._deny("MISSING_COMMAND", "run_cmd requires command/cmd", "run_cmd", call)

        for pattern, rule_id in self._OBFUSCATION_PATTERNS:
            if re.search(pattern, command):
                return self._deny(
                    rule_id,
                    f"Suspicious command obfuscation blocked: {rule_id}",
                    "run_cmd",
                    call,
                )

        program = self._extract_program(command)
        if program in self._RUN_CMD_BLOCKED_PROGRAMS:
            return self._deny(
                "BLOCKED_PROGRAM",
                f"Blocked program in run_cmd: {program}",
                "run_cmd",
                call,
            )

        if program and program not in self._RUN_CMD_ALLOWED_PROGRAMS:
            return self._deny(
                "PROGRAM_NOT_ALLOWLISTED",
                f"Program not allowlisted in run_cmd: {program}",
                "run_cmd",
                call,
            )

        return FirewallDecision(allowed=True)

    def _deny(self, rule_id: str, reason: str, tool_name: str, call: Dict[str, Any]) -> FirewallDecision:
        audit_id = f"pfw_{uuid.uuid4().hex[:12]}"
        record = {
            "ts": time.time(),
            "audit_id": audit_id,
            "rule_id": rule_id,
            "tool_name": tool_name,
            "reason": reason,
            "call": self._safe_call_snapshot(call),
        }
        try:
            with self.audit_file.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            pass
        return FirewallDecision(allowed=False, reason=reason, rule_id=rule_id, audit_id=audit_id)

    @staticmethod
    def _safe_call_snapshot(call: Dict[str, Any]) -> Dict[str, Any]:
        snapshot: Dict[str, Any] = {}
        for key, value in call.items():
            k = str(key)
            if k in {"content", "code"}:
                txt = str(value)
                snapshot[k] = txt[:500] + ("...(truncated)" if len(txt) > 500 else "")
            elif isinstance(value, (str, int, float, bool)) or value is None:
                snapshot[k] = value
            elif isinstance(value, list):
                snapshot[k] = f"<list:{len(value)}>"
            elif isinstance(value, dict):
                snapshot[k] = f"<dict:{len(value)}>"
            else:
                snapshot[k] = f"<{type(value).__name__}>"
        return snapshot


_policy_firewall: Optional[PolicyFirewall] = None


def get_policy_firewall() -> PolicyFirewall:
    global _policy_firewall
    if _policy_firewall is None:
        _policy_firewall = PolicyFirewall()
    return _policy_firewall


__all__ = ["FirewallDecision", "PolicyFirewall", "get_policy_firewall"]
