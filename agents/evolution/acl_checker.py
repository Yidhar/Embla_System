"""Prompt ACL checker — determines write permissions based on prompt_acl.spec."""

from __future__ import annotations

import fnmatch
import json
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_ACL_FILENAME = "specs/prompt_acl.spec"

# ACL levels and their write semantics
_IMMUTABLE_LEVELS = frozenset({"S0_LOCKED", "S1_CONTROLLED"})
_WRITABLE_LEVELS = frozenset({"S2_FLEXIBLE", "S3_OPEN"})


@dataclass(frozen=True)
class PromptPermission:
    """Result of an ACL lookup for a given prompt path."""

    path: str
    acl_level: str
    readable: bool
    immutable: bool
    writable: bool
    allow_ai_direct_write: bool


class PromptACLChecker:
    """Check prompt write permissions against the prompt_acl.spec rules."""

    def __init__(self, *, prompts_root: Path) -> None:
        self._prompts_root = Path(prompts_root)
        self._rules = self._load_rules()

    def _load_rules(self) -> list[dict]:
        acl_path = self._prompts_root / _DEFAULT_ACL_FILENAME
        if not acl_path.exists():
            logger.warning("Prompt ACL spec not found: %s", acl_path)
            return []
        try:
            data = json.loads(acl_path.read_text(encoding="utf-8"))
            return list(data.get("rules", []))
        except Exception as exc:
            logger.warning("Failed to load prompt ACL spec: %s", exc)
            return []

    def check(self, normalized_path: str) -> PromptPermission:
        """Check write permission for a normalized prompt path (relative to prompts_root).

        Rules are evaluated in order; the first match wins.
        If no rule matches, the path is treated as writable (S2_FLEXIBLE).
        """
        for rule in self._rules:
            pattern = rule.get("path_pattern", "")
            if fnmatch.fnmatch(normalized_path, pattern):
                level = rule.get("level", "S2_FLEXIBLE")
                allow_ai = bool(rule.get("allow_ai_direct_write", False))
                immutable = level in _IMMUTABLE_LEVELS
                writable = not immutable and allow_ai
                return PromptPermission(
                    path=normalized_path,
                    acl_level=level,
                    readable=True,
                    immutable=immutable,
                    writable=writable,
                    allow_ai_direct_write=allow_ai,
                )

        # Default: writable
        return PromptPermission(
            path=normalized_path,
            acl_level="S2_FLEXIBLE",
            readable=True,
            immutable=False,
            writable=True,
            allow_ai_direct_write=True,
        )
