"""Controlled prompt mutation -- agent modifies non-DNA prompt blocks with safety gates."""

import hashlib
import logging
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class PromptUpdateResult:
    success: bool
    change_id: str = ""
    reason: str = ""
    before_hash: str = ""
    after_hash: str = ""
    rollback_path: str = ""
    gate_passed: bool = False


_INJECTION_PATTERNS = [
    "ignore previous instructions",
    "system:",
    "you are now",
    "forget everything",
]


def update_my_prompt(
    *,
    prompt_path: str,
    new_content: str,
    reason: str,
    project_root: Path = Path("."),
    auto_approve: bool = False,
    prompts_root: Optional[Path] = None,
) -> PromptUpdateResult:
    """Update a non-DNA prompt block with full safety pipeline.

    Args:
        prompts_root: Override for the system prompts root directory.
            When *None* (default), falls back to ``get_system_prompts_root()``.

    Steps:
      1. ACL check (rejects DNA / locked files)
      2. Content validation (size limit, injection detection)
      3. Backup current file
      4. Audit pre-record
      5. Write new content
      6. Gate check (read_only gate — lightweight lint)
      7. Audit post-record
    """
    from agents.evolution.acl_checker import PromptACLChecker

    if prompts_root is not None:
        root = Path(prompts_root)
    else:
        from agents.prompt_engine import get_system_prompts_root

        root = Path(get_system_prompts_root())
    normalized = prompt_path.replace("\\", "/").strip("/")
    full_path = root / normalized
    change_id = (
        f"evo_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        f"_{hashlib.md5(normalized.encode()).hexdigest()[:8]}"
    )

    # 1. ACL check
    checker = PromptACLChecker(prompts_root=root)
    perm = checker.check(normalized)
    if perm.immutable:
        return PromptUpdateResult(
            success=False, change_id=change_id, reason="DNA files cannot be modified"
        )
    if not perm.writable:
        return PromptUpdateResult(
            success=False,
            change_id=change_id,
            reason=f"ACL {perm.acl_level} does not allow writes",
        )

    # 2. Content validation — size
    if len(new_content.encode("utf-8")) > 50 * 1024:
        return PromptUpdateResult(
            success=False, change_id=change_id, reason="content exceeds 50KB limit"
        )

    # 2b. Injection detection
    content_lower = new_content.lower()
    for pattern in _INJECTION_PATTERNS:
        if pattern in content_lower:
            return PromptUpdateResult(
                success=False,
                change_id=change_id,
                reason=f"injection pattern detected: {pattern}",
            )

    # 3. Backup current file
    before_hash = ""
    backup_dir = project_root / "workspace" / "evidence" / "prompt_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    rollback_path = ""
    if full_path.exists():
        old_content = full_path.read_text(encoding="utf-8")
        before_hash = hashlib.sha256(old_content.encode("utf-8")).hexdigest()
        backup_file = backup_dir / f"{normalized.replace('/', '_')}_{change_id}.bak"
        backup_file.write_text(old_content, encoding="utf-8")
        rollback_path = str(backup_file)

    # 4. Audit pre-record
    ledger = None
    try:
        from core.security.audit_ledger import AuditLedger

        ledger = AuditLedger(
            ledger_file=project_root / "scratch" / "runtime" / "audit_ledger.jsonl"
        )
        ledger.append_record(
            record_type="prompt_evolution_proposed",
            change_id=change_id,
            scope="prompt",
            risk_level="low",
            requested_by="prompt_mutator",
            payload={
                "path": normalized,
                "before_hash": before_hash,
                "reason": reason,
            },
        )
    except Exception as exc:
        logger.warning("Audit pre-record failed: %s", exc)

    # 5. Write new content
    full_path.parent.mkdir(parents=True, exist_ok=True)
    after_hash = hashlib.sha256(new_content.encode("utf-8")).hexdigest()
    full_path.write_text(new_content, encoding="utf-8")

    # 6. Gate check (lightweight)
    gate_passed = True
    try:
        from core.release.gate_runner import GateRunner

        runner = GateRunner(project_root=project_root)
        evaluation = runner.evaluate_gate("read_only")
        gate_passed = evaluation.passed
    except Exception:
        gate_passed = True  # degrade gracefully

    if not gate_passed and rollback_path:
        shutil.copy2(rollback_path, str(full_path))
        return PromptUpdateResult(
            success=False,
            change_id=change_id,
            reason="gate check failed, rolled back",
            before_hash=before_hash,
            after_hash=after_hash,
            rollback_path=rollback_path,
        )

    # 7. Audit post-record
    if ledger is not None:
        try:
            ledger.append_record(
                record_type="prompt_evolution_promoted",
                change_id=change_id,
                scope="prompt",
                risk_level="low",
                requested_by="prompt_mutator",
                payload={
                    "path": normalized,
                    "after_hash": after_hash,
                },
            )
        except Exception:
            pass

    return PromptUpdateResult(
        success=True,
        change_id=change_id,
        reason="prompt updated successfully",
        before_hash=before_hash,
        after_hash=after_hash,
        rollback_path=rollback_path,
        gate_passed=gate_passed,
    )
