"""L1 Memory Manager — structured MD file system memory.

Architecture ref: doc/14-multi-agent-architecture.md §5.1
Target ref: multi_agent_target_architecture §4.1

Three memory subdirectories:
  - working/session_{id}/  — short-term per-session state
  - episodic/              — mid-term experience reports + _index.md
  - domain/                — long-term domain knowledge + _index.md
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

_DEFAULT_MEMORY_ROOT = Path(__file__).resolve().parent.parent.parent / "memory"


class L1MemoryManager:
    """Manages the Layer 1 MD file system memory.

    Provides structured read/write access to working, episodic, and domain
    memory directories. Maintains `_index.md` tag-based indices for fast
    retrieval.

    Usage::

        mgr = L1MemoryManager()
        mgr.init_working_session("sess-001")
        mgr.write_context("sess-001", "Refactoring pipeline.py")
        mgr.write_experience(
            task_id="t-001", title="Pipeline Refactor",
            outcome="success", problem="...", solution="...",
            files=["agents/pipeline.py"], tags=["refactor", "pipeline"],
        )
        paths = mgr.scan_index(tags=["pipeline"])
    """

    def __init__(self, memory_root: Optional[str] = None) -> None:
        self._root = Path(memory_root) if memory_root else _DEFAULT_MEMORY_ROOT
        self._working_dir = self._root / "working"
        self._episodic_dir = self._root / "episodic"
        self._domain_dir = self._root / "domain"
        self._post_write_hooks: List[Callable[[Path, List[str]], None]] = []

    @property
    def root(self) -> Path:
        return self._root

    @property
    def episodic_dir(self) -> Path:
        return self._episodic_dir

    @property
    def domain_dir(self) -> Path:
        return self._domain_dir

    def register_post_write_hook(
        self, hook: Callable[[Path, List[str]], None]
    ) -> None:
        """Register a callback invoked after each write_experience().

        Args:
            hook: callable(episodic_dir, tags) — called after write.
                  Use this for auto-triggering compression or distillation.
        """
        self._post_write_hooks.append(hook)

    def episodic_file_count(self) -> int:
        """Count experience files in the episodic directory."""
        if not self._episodic_dir.exists():
            return 0
        return sum(1 for _ in self._episodic_dir.glob("exp_*.md"))

    # ── Working Memory (per-session) ───────────────────────────

    def init_working_session(self, session_id: str) -> Path:
        """Create a working memory directory for a session.

        Returns the session directory path.
        """
        session_dir = self._working_dir / f"session_{session_id}"
        session_dir.mkdir(parents=True, exist_ok=True)

        for filename in ("context.md", "findings.md", "decisions.md"):
            filepath = session_dir / filename
            if not filepath.exists():
                title = filename.replace(".md", "").capitalize()
                filepath.write_text(
                    f"# {title}\n\n> Session: {session_id}\n\n",
                    encoding="utf-8",
                )
        return session_dir

    def write_context(self, session_id: str, content: str) -> Path:
        """Write or append context for a working session."""
        return self._append_working_file(session_id, "context.md", content)

    def write_findings(self, session_id: str, content: str) -> Path:
        """Write or append findings for a working session."""
        return self._append_working_file(session_id, "findings.md", content)

    def write_decisions(self, session_id: str, content: str) -> Path:
        """Write or append decisions for a working session."""
        return self._append_working_file(session_id, "decisions.md", content)

    def read_working(self, session_id: str) -> Dict[str, str]:
        """Read all working memory files for a session.

        Returns dict with keys: context, findings, decisions.
        """
        session_dir = self._working_dir / f"session_{session_id}"
        result: Dict[str, str] = {}
        for filename in ("context.md", "findings.md", "decisions.md"):
            filepath = session_dir / filename
            key = filename.replace(".md", "")
            result[key] = filepath.read_text(encoding="utf-8") if filepath.exists() else ""
        return result

    def cleanup_working_session(self, session_id: str) -> bool:
        """Remove a working session directory.

        Returns True if the directory existed and was removed.
        """
        session_dir = self._working_dir / f"session_{session_id}"
        if not session_dir.exists():
            return False
        import shutil
        shutil.rmtree(session_dir)
        return True

    # ── Episodic Memory ────────────────────────────────────────

    def write_experience(
        self,
        *,
        name: str,
        task_id: str,
        title: str,
        outcome: str,
        problem: str = "",
        solution: str = "",
        files: Optional[Sequence[str]] = None,
        tags: Optional[Sequence[str]] = None,
    ) -> Path:
        """Write an experience report as MD and update the index.

        Args:
            name: **Required** descriptive slug for the filename.
                  Must be a concise human-readable description so agents
                  can identify the experience by scanning the directory.
                  Examples: ``"pipeline_refactoring"``, ``"ssh_permission_fix"``,
                  ``"ast_chunker_implementation"``.
            task_id: Task identifier (e.g. ``"t-001"``).
            title: Full title for the experience header.
            outcome: ``"success"`` / ``"failure"`` / ``"partial"``.
            problem: Problem description.
            solution: Solution description.
            files: List of changed files.
            tags: Tag list for indexing.

        Returns:
            Path to the written experience file.

        Raises:
            ValueError: If ``name`` is empty.
        """
        if not name or not name.strip():
            raise ValueError(
                "Experience `name` is required. "
                "Provide a descriptive slug, e.g. 'pipeline_refactoring'."
            )

        self._episodic_dir.mkdir(parents=True, exist_ok=True)

        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        slug = self._sanitize_slug(name)
        filename = f"exp_{date_str}_{slug}.md"
        filepath = self._episodic_dir / filename

        # Ensure uniqueness: append counter if file already exists
        counter = 1
        while filepath.exists():
            counter += 1
            filename = f"exp_{date_str}_{slug}_{counter}.md"
            filepath = self._episodic_dir / filename

        tag_str = " ".join(f"#{t}" for t in (tags or []))
        files_str = "\n".join(f"- `{f}`" for f in (files or []))

        content = (
            f"# 经验：{title}\n\n"
            f"tags: {tag_str}\n"
            f"task: {task_id}\n"
            f"outcome: {outcome}\n"
            f"date: {date_str}\n\n"
            f"## 问题\n{problem}\n\n"
            f"## 解决方案\n{solution}\n\n"
            f"## 变更文件\n{files_str}\n"
        )
        filepath.write_text(content, encoding="utf-8")

        # Update index
        self._update_episodic_index(filename, tags or [], title)

        logger.info("Wrote experience: %s (tags=%s)", filename, tags)

        # Fire post-write hooks (compression/distillation triggers)
        tag_list = list(tags) if tags else []
        for hook in self._post_write_hooks:
            try:
                hook(self._episodic_dir, tag_list)
            except Exception as exc:
                logger.warning("Post-write hook failed: %s", exc)
        return filepath

    @staticmethod
    def _sanitize_slug(name: str) -> str:
        """Convert a descriptive name to a safe filesystem slug."""
        import re
        slug = name.strip().lower()
        slug = slug.replace(" ", "_").replace("-", "_").replace("/", "_")
        slug = re.sub(r"[^a-z0-9_\u4e00-\u9fff]", "", slug)
        slug = re.sub(r"_+", "_", slug).strip("_")
        return slug or "unnamed"

    def scan_index(
        self,
        tags: Optional[Sequence[str]] = None,
        *,
        top_k: int = 5,
    ) -> List[str]:
        """Scan the episodic index for matching experience paths.

        Returns file paths (relative to memory root) sorted by relevance.
        """
        index_path = self._episodic_dir / "_index.md"
        if not index_path.exists():
            return []

        index_content = index_path.read_text(encoding="utf-8")
        if not tags:
            # Return all entries
            return self._parse_index_entries(index_content)[:top_k]

        tag_set = {t.lower().strip("#") for t in tags}
        entries = self._parse_index_entries(index_content)
        scored: List[tuple] = []
        for entry in entries:
            entry_tags = self._extract_tags_from_index_line(entry, index_content)
            overlap = len(tag_set & entry_tags)
            if overlap > 0:
                scored.append((overlap, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in scored][:top_k]

    def rebuild_index(self) -> int:
        """Rebuild _index.md from all experience MD files.

        Returns the number of entries indexed.
        """
        self._episodic_dir.mkdir(parents=True, exist_ok=True)
        index_path = self._episodic_dir / "_index.md"

        entries: List[Dict[str, Any]] = []
        for md_file in sorted(self._episodic_dir.glob("exp_*.md")):
            content = md_file.read_text(encoding="utf-8")
            title = self._extract_md_title(content)
            tags = self._extract_md_tags(content)
            entries.append({
                "filename": md_file.name,
                "title": title,
                "tags": tags,
            })

        lines = ["# 经验索引\n\n> 自动生成，勿手动编辑\n"]
        for entry in entries:
            tag_str = " ".join(f"#{t}" for t in entry["tags"])
            lines.append(
                f"- [{entry['title']}](episodic/{entry['filename']}) {tag_str}"
            )

        index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return len(entries)

    # ── Domain Memory ──────────────────────────────────────────

    def write_domain_knowledge(
        self,
        topic: str,
        content: str,
        *,
        tags: Optional[Sequence[str]] = None,
    ) -> Path:
        """Write or update a domain knowledge file.

        Returns the path to the domain file.
        """
        self._domain_dir.mkdir(parents=True, exist_ok=True)
        safe_topic = topic.lower().replace(" ", "_").replace("/", "_")
        filepath = self._domain_dir / f"{safe_topic}.md"
        filepath.write_text(content, encoding="utf-8")

        self._update_domain_index(safe_topic, tags or [], topic)
        return filepath

    def search_domain(self, query: str, *, top_k: int = 5) -> List[str]:
        """Search domain index by keyword.

        Returns file paths relative to memory root.
        """
        index_path = self._domain_dir / "_index.md"
        if not index_path.exists():
            return []

        query_lower = query.lower()
        index_content = index_path.read_text(encoding="utf-8")
        entries = self._parse_index_entries(index_content)
        matches = [e for e in entries if query_lower in e.lower()]
        return matches[:top_k]

    # ── Internal ───────────────────────────────────────────────

    def _append_working_file(
        self, session_id: str, filename: str, content: str
    ) -> Path:
        session_dir = self._working_dir / f"session_{session_id}"
        session_dir.mkdir(parents=True, exist_ok=True)
        filepath = session_dir / filename

        if filepath.exists():
            existing = filepath.read_text(encoding="utf-8")
            ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
            new_content = f"{existing}\n---\n\n**[{ts}]**\n\n{content}\n"
        else:
            title = filename.replace(".md", "").capitalize()
            new_content = f"# {title}\n\n> Session: {session_id}\n\n{content}\n"

        filepath.write_text(new_content, encoding="utf-8")
        return filepath

    def _update_episodic_index(
        self, filename: str, tags: Sequence[str], title: str
    ) -> None:
        index_path = self._episodic_dir / "_index.md"
        tag_str = " ".join(f"#{t}" for t in tags)
        entry_line = f"- [{title}](episodic/{filename}) {tag_str}"

        if index_path.exists():
            existing = index_path.read_text(encoding="utf-8")
            # Remove old entry for same filename if exists
            lines = [
                line for line in existing.splitlines()
                if filename not in line
            ]
            lines.append(entry_line)
            index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        else:
            content = f"# 经验索引\n\n> 自动生成，勿手动编辑\n\n{entry_line}\n"
            index_path.write_text(content, encoding="utf-8")

    def _update_domain_index(
        self, safe_topic: str, tags: Sequence[str], display_name: str
    ) -> None:
        index_path = self._domain_dir / "_index.md"
        tag_str = " ".join(f"#{t}" for t in tags)
        entry_line = f"- [{display_name}](domain/{safe_topic}.md) {tag_str}"

        if index_path.exists():
            existing = index_path.read_text(encoding="utf-8")
            lines = [
                line for line in existing.splitlines()
                if f"{safe_topic}.md" not in line
            ]
            lines.append(entry_line)
            index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        else:
            content = f"# 领域知识索引\n\n> 自动生成，勿手动编辑\n\n{entry_line}\n"
            index_path.write_text(content, encoding="utf-8")

    @staticmethod
    def _parse_index_entries(index_content: str) -> List[str]:
        entries = []
        for line in index_content.splitlines():
            stripped = line.strip()
            if stripped.startswith("- ["):
                entries.append(stripped)
        return entries

    @staticmethod
    def _extract_tags_from_index_line(
        entry: str, index_content: str
    ) -> set:
        """Extract #tag values from an index entry line."""
        tags = set()
        for part in entry.split():
            if part.startswith("#"):
                tags.add(part.lstrip("#").lower())
        return tags

    @staticmethod
    def _extract_md_title(content: str) -> str:
        for line in content.splitlines():
            if line.startswith("# "):
                return line[2:].strip()
        return "untitled"

    @staticmethod
    def _extract_md_tags(content: str) -> List[str]:
        for line in content.splitlines():
            if line.startswith("tags:"):
                raw = line[5:].strip()
                return [t.strip("#").strip() for t in raw.split() if t.startswith("#")]
        return []


__all__ = ["L1MemoryManager"]
