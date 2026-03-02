"""L1 → L2 sync pipeline: extract entities from L1 episodic MD → SemanticGraphStore.

Architecture ref: doc/14-multi-agent-architecture.md §5.2
  "L1→L2 管道：定期从经验 MD 中用次模型抽取五元组 → 写入 Neo4j + 向量化"

Lightweight local implementation: regex-based extraction (no LLM required),
syncing to the existing `SemanticGraphStore` (local JSON graph).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from agents.memory.episodic_memory import EpisodicRecord
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
    """Sync a single L1 experience MD file into the L2 graph.

    Creates EpisodicRecord(s) and feeds them into SemanticGraphStore.

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
    """Sync all L1 experience MD files from a directory into L2.

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


__all__ = [
    "extract_entities_from_experience_md",
    "sync_all_experiences",
    "sync_experience_to_graph",
]
