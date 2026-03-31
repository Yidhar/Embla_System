"""L1 → Tool-Result Topology sync pipeline.

This module projects L1 episodic markdown into the execution topology store
(`agents.memory.semantic_graph`).  This is **not** the Shell L2 Graph —
Shell-exclusive L2 lives in `summer_memory/quintuple_graph.py`.

Naming convention:
  - L1  = file-based episodic / working / domain memory
  - L2  = Shell quintuple graph (summer_memory)
  - This module = Tool-Result Topology (execution artefact index)

Lightweight local implementation: regex-based extraction (no LLM required),
syncing to the existing local JSON topology store.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from agents.memory.episodic_memory import EpisodicRecord
from agents.memory.l1_memory import L1MemoryManager
from agents.memory.semantic_graph import SemanticGraphStore, get_semantic_graph

logger = logging.getLogger(__name__)

_FILE_REF_PATTERN = re.compile(r"`([a-zA-Z0-9_/\\.]+\.[a-z]{1,5})`")
_TAG_PATTERN = re.compile(r"#([a-zA-Z0-9_\u4e00-\u9fff]+)")


def extract_entities_from_experience_md(content: str) -> Dict[str, Any]:
    """Extract entities and relations from an experience MD file.

    Returns dict with keys:
        - title: str
        - tags: list[str]
        - task_id: str
        - outcome: str
        - files: list[str]
        - topics: list[str]  (derived from tags + title keywords)
    """
    title = ""
    tags: List[str] = []
    task_id = ""
    outcome = ""
    files: List[str] = []

    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("# ") and not title:
            title = stripped[2:].strip()
        elif stripped.startswith("tags:"):
            tags = [m for m in _TAG_PATTERN.findall(stripped)]
        elif stripped.startswith("task:"):
            task_id = stripped[5:].strip()
        elif stripped.startswith("outcome:"):
            outcome = stripped[8:].strip()

    # Extract file references from backtick-quoted paths
    files = list(dict.fromkeys(_FILE_REF_PATTERN.findall(content)))

    # Derive topic keywords from title
    topics = list(tags)
    if title:
        # Extract meaningful words from title (skip common prefixes like 经验：)
        clean_title = re.sub(r"^经验[：:]?\s*", "", title)
        words = re.findall(r"[a-zA-Z_]{3,}|[\u4e00-\u9fff]{2,}", clean_title)
        for w in words:
            if w.lower() not in {t.lower() for t in topics}:
                topics.append(w.lower())

    return {
        "title": title,
        "tags": tags,
        "task_id": task_id,
        "outcome": outcome,
        "files": files,
        "topics": topics,
    }


def sync_experience_to_graph(
    experience_path: Path,
    *,
    session_id: str = "l1_sync",
    graph: Optional[SemanticGraphStore] = None,
) -> Dict[str, Any]:
    """Sync a single L1 experience MD file into the Tool-Result Topology.

    Creates EpisodicRecord(s) and feeds them into SemanticGraphStore.
    Note: this is the execution-artefact topology, not Shell L2 graph.

    Returns sync summary dict.
    """
    if not experience_path.exists():
        return {"synced": False, "reason": "file_not_found"}

    content = experience_path.read_text(encoding="utf-8")
    entities = extract_entities_from_experience_md(content)

    record = EpisodicRecord(
        record_id=experience_path.stem,
        session_id=session_id,
        source_tool="l1_memory",
        narrative_summary=entities["title"],
        forensic_artifact_ref=str(experience_path),
        fetch_hints=entities["tags"] + entities["files"],
    )

    target_graph = graph or get_semantic_graph()
    target_graph.update_from_records(session_id, [record])

    return {
        "synced": True,
        "file": str(experience_path),
        "entities": entities,
        "record_id": record.record_id,
    }


def sync_all_experiences(
    episodic_dir: Path,
    *,
    session_id: str = "l1_sync",
    graph: Optional[SemanticGraphStore] = None,
) -> Dict[str, Any]:
    """Sync all L1 experience MD files into the Tool-Result Topology.

    Returns summary dict with counts.
    """
    if not episodic_dir.exists():
        return {"total": 0, "synced": 0, "errors": 0}

    target_graph = graph or get_semantic_graph()
    total = 0
    synced = 0
    errors = 0

    for md_file in sorted(episodic_dir.glob("exp_*.md")):
        total += 1
        try:
            result = sync_experience_to_graph(
                md_file,
                session_id=session_id,
                graph=target_graph,
            )
            if result.get("synced"):
                synced += 1
            else:
                errors += 1
        except Exception as exc:
            logger.warning("Failed to sync %s: %s", md_file, exc)
            errors += 1

    return {"total": total, "synced": synced, "errors": errors}


def register_l1_to_l2_hooks(manager: L1MemoryManager) -> None:
    """Register the L1 → Tool-Result Topology sync as a post-write hook."""

    def _on_write(episodic_dir: Path, tags: list) -> None:
        try:
            sync_all_experiences(episodic_dir, session_id="l1_auto_sync", graph=None)
        except Exception:
            pass  # L2 sync failure should not block L1 write

    manager.register_post_write_hook(_on_write)


__all__ = [
    "extract_entities_from_experience_md",
    "extract_entities_from_experience_md_for_topology",
    "register_l1_to_l2_hooks",
    "sync_all_experiences",
    "sync_all_experiences_to_tool_result_topology",
    "sync_experience_to_graph",
    "sync_experience_to_tool_result_topology",
]


# Canonical aliases for the execution-topology naming.
extract_entities_from_experience_md_for_topology = extract_entities_from_experience_md
sync_experience_to_tool_result_topology = sync_experience_to_graph
sync_all_experiences_to_tool_result_topology = sync_all_experiences
