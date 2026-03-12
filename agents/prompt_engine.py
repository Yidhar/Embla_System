"""Atomic Prompt Engine — modular prompt assembly with Immutable DNA protection.

Architecture ref: doc/14-multi-agent-architecture.md §4
Target ref: multi_agent_target_architecture §3

Assembly order:
  1. Load DNA (immutable, SHA-256 verified)
  2. Load atomic blocks (roles/ skills/ styles/ rules/)
  3. Inject memory hints (L1 experience paths)
  4. Concatenate into final system prompt
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

_SYSTEM_PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "system" / "prompts"
_DEFAULT_PROMPTS_ROOT = _SYSTEM_PROMPTS_ROOT


class DNAIntegrityError(Exception):
    """Raised when a DNA file fails SHA-256 integrity check."""


class PromptBlockNotFoundError(FileNotFoundError):
    """Raised when a prompt block file is not found."""


class _SafeFormatDict(dict):
    def __missing__(self, key: str) -> str:
        return "{" + str(key) + "}"


def get_system_prompts_root() -> Path:
    """Return the canonical runtime prompt asset root."""
    return _SYSTEM_PROMPTS_ROOT


class PromptAssembler:
    """Modular prompt assembly engine.

    Loads immutable DNA files and atomic prompt blocks from the filesystem,
    optionally verifying DNA integrity via SHA-256 checksums.

    Usage::

        assembler = PromptAssembler()
        prompt = assembler.assemble(
            dna="shell_persona",
            blocks=["roles/backend_expert.md", "skills/python_ast.md"],
            memory_hints=["memory/episodic/exp_20260303_001.md"],
        )
    """

    def __init__(
        self,
        prompts_root: Optional[str] = None,
        *,
        dna_checksums: Optional[Dict[str, str]] = None,
        strict_dna: bool = False,
    ) -> None:
        self._root = Path(prompts_root) if prompts_root else _DEFAULT_PROMPTS_ROOT
        self._dna_dir = self._root / "dna"
        self._dna_checksums = dna_checksums or {}
        self._strict_dna = strict_dna
        self._cache: Dict[str, str] = {}

    # ── Public API ─────────────────────────────────────────────

    def load_dna(self, dna_name: str) -> str:
        """Load an immutable DNA file and verify integrity.

        Args:
            dna_name: Name without extension (e.g. ``"shell_persona"``).

        Returns:
            Content of the DNA file.

        Raises:
            PromptBlockNotFoundError: If the DNA file does not exist.
            DNAIntegrityError: If strict mode is on and checksum fails.
        """
        candidates = [
            self._dna_dir / f"{dna_name}.md",
            self._root / "core" / "dna" / f"{dna_name}.md",
        ]
        path = next((candidate for candidate in candidates if candidate.exists()), None)
        if path is None:
            raise PromptBlockNotFoundError(f"DNA file not found: {candidates[0]}")

        content = self._read_cached(path)

        expected_hash = self._dna_checksums.get(dna_name)
        if expected_hash:
            actual_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
            if actual_hash != expected_hash:
                msg = (
                    f"DNA integrity check failed for '{dna_name}': "
                    f"expected {expected_hash[:16]}..., got {actual_hash[:16]}..."
                )
                if self._strict_dna:
                    raise DNAIntegrityError(msg)
                logger.warning(msg)

        return content

    def load_block(self, block_path: str) -> str:
        """Load a single atomic prompt block.

        Args:
            block_path: Relative path from prompts root (e.g. ``"roles/backend_expert.md"``).

        Returns:
            Content of the block file.

        Raises:
            PromptBlockNotFoundError: If the block file does not exist.
        """
        path = self._root / block_path
        if not path.exists():
            raise PromptBlockNotFoundError(f"Prompt block not found: {path}")
        return self._read_cached(path)

    def render_block(
        self,
        block_path: str,
        *,
        variables: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Load and render a prompt block with safe string substitution."""
        content = self.load_block(block_path)
        if not variables:
            return content
        try:
            return content.format_map(_SafeFormatDict(variables))
        except Exception:
            logger.warning("Prompt block render failed, returning raw block: %s", block_path, exc_info=True)
            return content

    def assemble(
        self,
        *,
        dna: Optional[str] = None,
        blocks: Optional[Sequence[str]] = None,
        memory_hints: Optional[Sequence[str]] = None,
        extra_sections: Optional[Sequence[str]] = None,
    ) -> str:
        """Assemble a complete system prompt from components.

        Args:
            dna: DNA name to load (e.g. ``"shell_persona"``). Optional.
            blocks: List of block paths relative to prompts root.
            memory_hints: L1 memory file paths to inject as references.
            extra_sections: Additional inline text sections to append.

        Returns:
            Assembled prompt string.
        """
        parts: List[str] = []

        # 1. DNA (always first)
        if dna:
            parts.append(self.load_dna(dna))

        # 2. Atomic blocks
        for block_path in (blocks or []):
            try:
                parts.append(self.load_block(block_path))
            except PromptBlockNotFoundError:
                logger.warning("Prompt block not found, skipping: %s", block_path)

        # 3. Extra inline sections
        for section in (extra_sections or []):
            if section.strip():
                parts.append(section)

        # 4. Memory hints (injected as reference list, not full content)
        if memory_hints:
            hint_lines = [f"- 参考: `{hint}`" for hint in memory_hints]
            parts.append("\n## 相关经验\n" + "\n".join(hint_lines))

        return "\n\n".join(parts)

    def list_blocks(self, category: Optional[str] = None) -> List[str]:
        """List available prompt blocks.

        Args:
            category: Optional subdirectory filter (e.g. ``"roles"``, ``"skills"``).

        Returns:
            List of block paths relative to prompts root.
        """
        search_dir = self._root / category if category else self._root
        if not search_dir.exists():
            return []
        blocks: List[str] = []
        for md_file in sorted(search_dir.rglob("*.md")):
            rel = md_file.relative_to(self._root)
            rel_parts = rel.parts
            if rel_parts[:1] == ("dna",):
                continue
            if rel_parts[:2] == ("core", "dna"):
                continue
            blocks.append(str(rel).replace("\\", "/"))
        return blocks

    def list_dna(self) -> List[str]:
        """List available DNA files."""
        names: set[str] = set()
        for dna_dir in (self._dna_dir, self._root / "core" / "dna"):
            if not dna_dir.exists():
                continue
            for path in dna_dir.glob("*.md"):
                names.add(path.stem)
        return sorted(names)

    # ── Internal ───────────────────────────────────────────────

    def _read_cached(self, path: Path) -> str:
        key = str(path)
        if key not in self._cache:
            self._cache[key] = path.read_text(encoding="utf-8")
        return self._cache[key]


__all__ = [
    "DNAIntegrityError",
    "PromptAssembler",
    "PromptBlockNotFoundError",
    "get_system_prompts_root",
]
