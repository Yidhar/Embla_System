"""Meta-cognition tools — give Core real-time awareness and agency over framework quality.

Two tools:
  1. report_framework_friction  — record perceived friction for evolution
  2. trigger_self_improvement   — immediately invoke evolution orchestrator on a target

These run inside the async tool-loop context (called from native_tools executor).
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)

# ── Persistence ──────────────────────────────────────────────────
_FRICTION_LOG_PATH = Path("scratch/runtime/framework_friction.jsonl")
_IMMEDIATE_TRIGGER_COOLDOWN_SECONDS = 300  # 5 min between trigger_self_improvement calls
_last_trigger_ts: float = 0.0


def report_framework_friction(
    *,
    friction_type: str,
    description: str,
    affected_component: str = "",
    severity: str = "medium",
    suggested_fix: str = "",
    session_id: str = "",
) -> Dict[str, Any]:
    """Record a framework friction observation from the running agent.

    This is a lightweight synchronous write — no LLM call, no blocking.
    The evolution system will pick up accumulated friction reports on its
    next cycle (or immediately if threshold is reached).
    """
    valid_types = {"prompt_gap", "tool_deficiency", "config_issue", "routing_problem"}
    valid_severities = {"low", "medium", "high"}

    if friction_type not in valid_types:
        return {
            "status": "error",
            "message": f"Invalid friction_type: {friction_type}. Must be one of: {', '.join(sorted(valid_types))}",
        }

    severity = severity.lower().strip() if severity else "medium"
    if severity not in valid_severities:
        severity = "medium"

    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "friction_type": friction_type,
        "description": description.strip()[:2000],
        "affected_component": affected_component.strip()[:500],
        "severity": severity,
        "suggested_fix": suggested_fix.strip()[:2000],
        "session_id": session_id,
        "source": "agent_metacognition",
    }

    try:
        _FRICTION_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _FRICTION_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.warning("Failed to write friction report: %s", exc)
        return {"status": "error", "message": f"Write failed: {exc}"}

    # Check if we should trigger immediate evolution
    immediate = _check_immediate_trigger(friction_type, severity)

    logger.info(
        "[MetaCognition] Friction reported: type=%s severity=%s component=%s immediate=%s",
        friction_type,
        severity,
        affected_component,
        immediate,
    )

    return {
        "status": "recorded",
        "message": f"Friction recorded: {friction_type} ({severity}). "
        + ("Immediate evolution cycle will be triggered." if immediate else "Will be processed in next evolution cycle."),
        "immediate_trigger": immediate,
    }


def trigger_self_improvement(
    *,
    target_prompt: str,
    improvement_type: str = "refine",
    rationale: str,
    draft_content: str = "",
    session_id: str = "",
) -> Dict[str, Any]:
    """Trigger an immediate self-improvement cycle on a specific prompt.

    This bypasses the Chronos hourly schedule and runs the evolution
    orchestrator's propose→execute pipeline directly.

    Safety: respects ACL (DNA immutable), cooldown, and audit trail.
    """
    global _last_trigger_ts

    valid_types = {"rewrite", "append", "refine"}
    if improvement_type not in valid_types:
        return {
            "status": "error",
            "message": f"Invalid improvement_type: {improvement_type}. Must be one of: {', '.join(sorted(valid_types))}",
        }

    if not target_prompt or not rationale:
        return {"status": "error", "message": "target_prompt and rationale are required"}

    # Cooldown enforcement
    now = time.monotonic()
    elapsed = now - _last_trigger_ts
    if _last_trigger_ts > 0 and elapsed < _IMMEDIATE_TRIGGER_COOLDOWN_SECONDS:
        remaining = int(_IMMEDIATE_TRIGGER_COOLDOWN_SECONDS - elapsed)
        return {
            "status": "cooldown",
            "message": f"Self-improvement cooldown active. Try again in {remaining}s.",
            "cooldown_remaining_seconds": remaining,
        }

    # ACL check — DNA files are immutable
    target_normalized = target_prompt.strip().replace("\\", "/").strip("/")
    if target_normalized.startswith("dna/") or "/dna/" in target_normalized:
        return {
            "status": "denied",
            "message": "DNA files are immutable and cannot be modified by self-improvement.",
        }

    # Allowed scopes
    allowed_prefixes = ("roles/", "skills/", "styles/", "rules/")
    if not any(target_normalized.startswith(p) for p in allowed_prefixes):
        return {
            "status": "denied",
            "message": f"Target must be in one of: {', '.join(allowed_prefixes)}. Got: {target_normalized}",
        }

    # Execute improvement via prompt_mutator
    try:
        from agents.evolution.prompt_mutator import PromptMutator
        from system.config import get_system_prompts_root

        prompts_root = Path(get_system_prompts_root())
        mutator = PromptMutator(prompts_root=prompts_root)

        full_path = prompts_root / target_normalized
        if not full_path.exists():
            return {"status": "error", "message": f"Target prompt not found: {target_normalized}"}

        current_content = full_path.read_text(encoding="utf-8")

        if draft_content.strip():
            new_content = draft_content.strip()
        else:
            # No draft provided — use LLM to generate improvement
            new_content = _llm_refine_prompt(
                current_content=current_content,
                target_path=target_normalized,
                improvement_type=improvement_type,
                rationale=rationale,
            )
            if not new_content:
                return {"status": "error", "message": "LLM failed to generate improvement draft"}

        # Apply mutation via safe mutator
        result = mutator.update_my_prompt(
            prompt_path=target_normalized,
            new_content=new_content,
            reason=f"[metacognition:{improvement_type}] {rationale[:200]}",
        )

        if result.get("status") == "success":
            _last_trigger_ts = now
            _log_improvement(
                target=target_normalized,
                improvement_type=improvement_type,
                rationale=rationale,
                session_id=session_id,
            )
            logger.info(
                "[MetaCognition] Self-improvement applied: target=%s type=%s",
                target_normalized,
                improvement_type,
            )
            return {
                "status": "applied",
                "message": f"Improvement applied to {target_normalized}.",
                "target": target_normalized,
                "backup_created": bool(result.get("backup_path")),
            }
        else:
            return {
                "status": "error",
                "message": f"Mutation failed: {result.get('message', 'unknown error')}",
            }

    except Exception as exc:
        logger.error("[MetaCognition] Self-improvement failed: %s", exc, exc_info=True)
        return {"status": "error", "message": f"Self-improvement failed: {exc}"}


def _llm_refine_prompt(
    *,
    current_content: str,
    target_path: str,
    improvement_type: str,
    rationale: str,
) -> str:
    """Use LLM to generate improved prompt content."""
    try:
        import litellm
        from system.config import get_config

        cfg = get_config()
        model = cfg.api.model

        system_msg = (
            "你是 Embla 系统的 prompt 工程师。根据提供的理由，改进指定的 prompt 文件内容。\n"
            "要求：\n"
            "1. 保持 prompt 的核心职责不变\n"
            "2. 只修改与问题相关的部分\n"
            "3. 直接输出完整的新 prompt 内容，不要包含解释\n"
            "4. 保持原有格式（Markdown）"
        )
        user_msg = (
            f"## 目标文件\n{target_path}\n\n"
            f"## 改进类型\n{improvement_type}\n\n"
            f"## 改进理由\n{rationale}\n\n"
            f"## 当前内容\n```markdown\n{current_content[:4000]}\n```\n\n"
            "请直接输出改进后的完整 prompt 内容："
        )

        response = litellm.completion(
            model=model,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=4000,
            temperature=0.3,
        )
        content = response.choices[0].message.content or ""
        # Strip markdown code fences if present
        if content.startswith("```"):
            lines = content.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            content = "\n".join(lines)
        return content.strip()
    except Exception as exc:
        logger.error("[MetaCognition] LLM refine failed: %s", exc)
        return ""


def _check_immediate_trigger(friction_type: str, severity: str) -> bool:
    """Check if accumulated friction should trigger an immediate evolution cycle.

    Returns True if there are 3+ high-severity or 5+ any-severity frictions
    of the same type in the last hour.
    """
    try:
        if not _FRICTION_LOG_PATH.exists():
            return False

        cutoff = time.time() - 3600  # last hour
        type_count = 0
        high_count = 0

        for line in _FRICTION_LOG_PATH.read_text(encoding="utf-8").strip().split("\n"):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                ts = datetime.fromisoformat(record.get("timestamp", "")).timestamp()
                if ts < cutoff:
                    continue
                if record.get("friction_type") == friction_type:
                    type_count += 1
                    if record.get("severity") == "high":
                        high_count += 1
            except Exception:
                continue

        return high_count >= 3 or type_count >= 5
    except Exception:
        return False


def _log_improvement(
    *,
    target: str,
    improvement_type: str,
    rationale: str,
    session_id: str,
) -> None:
    """Append improvement record to friction log."""
    try:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": "self_improvement_applied",
            "target": target,
            "improvement_type": improvement_type,
            "rationale": rationale[:500],
            "session_id": session_id,
        }
        with _FRICTION_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def get_friction_summary(*, hours: int = 24) -> Dict[str, Any]:
    """Get summary of recent friction reports for dashboard/L1.5 injection."""
    if not _FRICTION_LOG_PATH.exists():
        return {"total": 0, "by_type": {}, "by_severity": {}, "recent": []}

    cutoff = time.time() - (hours * 3600)
    by_type: Dict[str, int] = {}
    by_severity: Dict[str, int] = {}
    recent: list = []
    total = 0

    try:
        for line in _FRICTION_LOG_PATH.read_text(encoding="utf-8").strip().split("\n"):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                if record.get("event") == "self_improvement_applied":
                    continue  # skip improvement records
                ts = datetime.fromisoformat(record.get("timestamp", "")).timestamp()
                if ts < cutoff:
                    continue
                total += 1
                ft = record.get("friction_type", "unknown")
                sev = record.get("severity", "unknown")
                by_type[ft] = by_type.get(ft, 0) + 1
                by_severity[sev] = by_severity.get(sev, 0) + 1
                if len(recent) < 5:
                    recent.append({
                        "type": ft,
                        "severity": sev,
                        "description": record.get("description", "")[:100],
                        "component": record.get("affected_component", ""),
                    })
            except Exception:
                continue
    except Exception:
        pass

    return {"total": total, "by_type": by_type, "by_severity": by_severity, "recent": recent}
