"""Self-introspection tools — agent reads its own prompt blocks."""
import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from agents.evolution.acl_checker import PromptACLChecker

logger = logging.getLogger(__name__)


def list_my_prompts(*, scope: str = "all") -> List[Dict[str, Any]]:
    """List available prompt blocks with their ACL permissions."""
    from system.config import get_system_prompts_root

    root = Path(get_system_prompts_root())
    checker = PromptACLChecker(prompts_root=root)

    results = []
    for md_file in sorted(root.rglob("*.md")):
        rel = str(md_file.relative_to(root)).replace("\\", "/")
        # Skip specs directory
        if rel.startswith("specs/"):
            continue
        perm = checker.check(rel)

        if scope == "writable" and not perm.writable:
            continue
        if scope == "immutable" and not perm.immutable:
            continue
        if scope == "dna" and not perm.immutable:
            continue

        results.append({
            "path": rel,
            "acl_level": perm.acl_level,
            "writable": perm.writable,
            "immutable": perm.immutable,
            "size_bytes": md_file.stat().st_size,
        })
    return results


def read_my_prompt(*, prompt_path: str) -> Dict[str, Any]:
    """Read a prompt block's content and metadata."""
    from system.config import get_system_prompts_root

    root = Path(get_system_prompts_root())
    checker = PromptACLChecker(prompts_root=root)

    normalized = prompt_path.replace("\\", "/").strip("/")
    full_path = root / normalized

    if not full_path.exists():
        return {"error": f"prompt not found: {normalized}", "found": False}
    if not full_path.is_file():
        return {"error": f"not a file: {normalized}", "found": False}

    perm = checker.check(normalized)
    content = full_path.read_text(encoding="utf-8")
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

    return {
        "found": True,
        "path": normalized,
        "content": content,
        "acl_level": perm.acl_level,
        "writable": perm.writable,
        "immutable": perm.immutable,
        "content_sha256": content_hash,
        "size_bytes": len(content.encode("utf-8")),
        "last_modified": datetime.fromtimestamp(
            full_path.stat().st_mtime, tz=timezone.utc
        ).isoformat(),
    }
