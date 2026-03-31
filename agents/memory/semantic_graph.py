"""
Tool-result topology persistence and query helpers.

This store models `session/tool/artifact/topic` execution topology from episodic
records. It is intentionally separate from Shell L2 Graph RAG in
`summer_memory/quintuple_graph.py`.

NGA-WS19-006:
- build/update topology from WS19-005 episodic records
- local JSON storage (no external dependency)
- provide tool -> artifact -> topic/session topology queries
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, TYPE_CHECKING

if TYPE_CHECKING:
    from agents.memory.episodic_memory import EpisodicRecord

logger = logging.getLogger(__name__)

_NODE_TYPES = {"session", "tool", "artifact", "topic"}
_RELATION_TYPES = {"emits", "references", "contains", "co_occurs"}
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]{2,}")
_NONE_MARKERS = {"", "(none)", "none", "null", "nil", "n/a", "undefined"}
_TOPIC_STOPWORDS = {
    "the",
    "and",
    "with",
    "from",
    "that",
    "this",
    "for",
    "are",
    "was",
    "tool",
    "tools",
    "result",
    "results",
    "status",
    "native",
    "forensic",
    "artifact",
    "summary",
    "display",
    "preview",
    "fetch",
    "hints",
    "session",
    "sessions",
    "jsonpath",
    "grep",
}


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _normalize_text(value: Any) -> str:
    text = re.sub(r"\s+", " ", _safe_text(value)).strip()
    return text


def _normalize_key(value: Any) -> str:
    return _normalize_text(value).lower()


def _normalize_topic(value: Any) -> str:
    topic = _normalize_key(value)
    if not topic:
        return ""
    if topic.isdigit():
        return ""
    if topic in _TOPIC_STOPWORDS:
        return ""
    if len(topic) <= 1:
        return ""
    return topic


def _clean_optional_ref(value: Any) -> str:
    text = _normalize_text(value)
    if text.lower() in _NONE_MARKERS:
        return ""
    return text


def _build_node_id(node_type: str, key: str) -> str:
    if node_type not in _NODE_TYPES:
        raise ValueError(f"unsupported node_type: {node_type}")
    return f"{node_type}:{key}"


class SemanticGraphStore:
    """Mutable lightweight tool-result topology store backed by local JSON."""

    def __init__(self, graph_path: Optional[Path] = None, *, max_topics_per_record: int = 8) -> None:
        self.graph_path = Path(graph_path) if graph_path is not None else _default_graph_path()
        self.max_topics_per_record = max(1, min(int(max_topics_per_record), 32))
        self._nodes: Dict[str, Dict[str, Any]] = {}
        self._edges: Dict[str, Dict[str, Any]] = {}
        self._loaded = False
        self._lock = threading.RLock()
        self.graph_path.parent.mkdir(parents=True, exist_ok=True)

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return

        self._nodes = {}
        self._edges = {}
        if self.graph_path.exists():
            try:
                payload = json.loads(self.graph_path.read_text(encoding="utf-8"))
                for item in payload.get("nodes", []):
                    if not isinstance(item, dict):
                        continue
                    node_id = _normalize_text(item.get("node_id"))
                    node_type = _normalize_text(item.get("node_type"))
                    label = _normalize_text(item.get("label"))
                    if not node_id or node_type not in _NODE_TYPES or not label:
                        continue
                    self._nodes[node_id] = {
                        "node_id": node_id,
                        "node_type": node_type,
                        "label": label,
                        "key": _normalize_text(item.get("key")),
                        "first_seen": float(item.get("first_seen", time.time())),
                        "last_seen": float(item.get("last_seen", time.time())),
                        "seen_count": int(item.get("seen_count", 1)),
                    }

                for item in payload.get("edges", []):
                    if not isinstance(item, dict):
                        continue
                    source_id = _normalize_text(item.get("source_id"))
                    relation = _normalize_text(item.get("relation"))
                    target_id = _normalize_text(item.get("target_id"))
                    if not source_id or relation not in _RELATION_TYPES or not target_id:
                        continue
                    edge_id = self._edge_id(source_id, relation, target_id)
                    self._edges[edge_id] = {
                        "edge_id": edge_id,
                        "source_id": source_id,
                        "relation": relation,
                        "target_id": target_id,
                        "weight": int(item.get("weight", 1)),
                        "first_seen": float(item.get("first_seen", time.time())),
                        "last_seen": float(item.get("last_seen", time.time())),
                    }
            except Exception as exc:
                logger.warning("[SemanticGraph] failed to load graph file %s: %s", self.graph_path, exc)
        self._loaded = True

    @staticmethod
    def _edge_id(source_id: str, relation: str, target_id: str) -> str:
        if relation == "co_occurs" and source_id > target_id:
            source_id, target_id = target_id, source_id
        return f"{source_id}|{relation}|{target_id}"

    def _save_locked(self) -> None:
        payload = {
            "version": 1,
            "nodes": sorted(self._nodes.values(), key=lambda node: node["node_id"]),
            "edges": sorted(self._edges.values(), key=lambda edge: edge["edge_id"]),
        }
        temp_path = self.graph_path.with_suffix(self.graph_path.suffix + ".tmp")
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(self.graph_path)

    def _upsert_node(self, node_type: str, label: str, timestamp: float) -> str:
        normalized_label = _normalize_text(label)
        key = _normalize_key(normalized_label)
        if not normalized_label or not key:
            raise ValueError(f"invalid node label for {node_type}")

        node_id = _build_node_id(node_type, key)
        node = self._nodes.get(node_id)
        if node is None:
            self._nodes[node_id] = {
                "node_id": node_id,
                "node_type": node_type,
                "label": normalized_label,
                "key": key,
                "first_seen": float(timestamp),
                "last_seen": float(timestamp),
                "seen_count": 1,
            }
            return node_id

        node["last_seen"] = max(float(node.get("last_seen", timestamp)), float(timestamp))
        node["seen_count"] = int(node.get("seen_count", 1)) + 1
        return node_id

    def _upsert_edge(self, source_id: str, relation: str, target_id: str, timestamp: float) -> int:
        if relation not in _RELATION_TYPES:
            raise ValueError(f"unsupported relation: {relation}")
        edge_id = self._edge_id(source_id, relation, target_id)
        if relation == "co_occurs" and source_id > target_id:
            source_id, target_id = target_id, source_id

        edge = self._edges.get(edge_id)
        if edge is None:
            self._edges[edge_id] = {
                "edge_id": edge_id,
                "source_id": source_id,
                "relation": relation,
                "target_id": target_id,
                "weight": 1,
                "first_seen": float(timestamp),
                "last_seen": float(timestamp),
            }
            return 1

        edge["weight"] = int(edge.get("weight", 1)) + 1
        edge["last_seen"] = max(float(edge.get("last_seen", timestamp)), float(timestamp))
        return 1

    def _extract_topics(self, record: "EpisodicRecord") -> List[str]:
        text_parts = [record.narrative_summary]
        if record.fetch_hints:
            text_parts.extend(record.fetch_hints)
        merged = " ".join(_normalize_text(part) for part in text_parts if _normalize_text(part))
        if not merged:
            return []

        topic_counts: Dict[str, int] = {}
        for token in _TOKEN_RE.findall(merged):
            topic = _normalize_topic(token)
            if not topic:
                continue
            topic_counts[topic] = topic_counts.get(topic, 0) + 1

        ranked = sorted(topic_counts.items(), key=lambda item: (-item[1], -len(item[0]), item[0]))
        return [topic for topic, _count in ranked[: self.max_topics_per_record]]

    def update_from_records(self, session_id: str, records: Sequence["EpisodicRecord"]) -> int:
        if not records:
            return 0

        updates = 0
        fallback_session = _normalize_text(session_id)
        if not fallback_session:
            return 0

        with self._lock:
            self._ensure_loaded()
            for record in records:
                ts = float(getattr(record, "timestamp", time.time()) or time.time())
                record_session = _normalize_text(getattr(record, "session_id", "")) or fallback_session
                source_tool = _normalize_text(getattr(record, "source_tool", "")) or "unknown"
                artifact_ref = _clean_optional_ref(getattr(record, "forensic_artifact_ref", ""))

                session_id_node = self._upsert_node("session", record_session, ts)
                tool_id_node = self._upsert_node("tool", source_tool, ts)
                updates += self._upsert_edge(session_id_node, "contains", tool_id_node, ts)

                topics = self._extract_topics(record)
                topic_node_ids: List[str] = []
                for topic in topics:
                    topic_node_id = self._upsert_node("topic", topic, ts)
                    topic_node_ids.append(topic_node_id)
                    updates += self._upsert_edge(session_id_node, "contains", topic_node_id, ts)

                if artifact_ref:
                    artifact_node_id = self._upsert_node("artifact", artifact_ref, ts)
                    updates += self._upsert_edge(tool_id_node, "emits", artifact_node_id, ts)
                    updates += self._upsert_edge(session_id_node, "contains", artifact_node_id, ts)
                    for topic_node_id in topic_node_ids:
                        updates += self._upsert_edge(artifact_node_id, "references", topic_node_id, ts)
                else:
                    for topic_node_id in topic_node_ids:
                        updates += self._upsert_edge(tool_id_node, "references", topic_node_id, ts)

                for left_idx in range(len(topic_node_ids)):
                    for right_idx in range(left_idx + 1, len(topic_node_ids)):
                        updates += self._upsert_edge(topic_node_ids[left_idx], "co_occurs", topic_node_ids[right_idx], ts)

            if updates > 0:
                self._save_locked()
        return updates

    def query_tool_artifact_topology(
        self,
        tool: str,
        *,
        session_id: Optional[str] = None,
        top_k_topics: int = 8,
    ) -> List[Dict[str, Any]]:
        normalized_tool = _normalize_text(tool)
        if not normalized_tool:
            return []

        with self._lock:
            self._ensure_loaded()
            tool_node_id = _build_node_id("tool", _normalize_key(normalized_tool))
            tool_node = self._nodes.get(tool_node_id)
            if tool_node is None:
                return []

            session_filter_node_id = ""
            if session_id is not None:
                normalized_session = _normalize_text(session_id)
                if not normalized_session:
                    return []
                session_filter_node_id = _build_node_id("session", _normalize_key(normalized_session))

            emitted_edges = [
                edge
                for edge in self._edges.values()
                if edge["relation"] == "emits" and edge["source_id"] == tool_node_id
            ]
            emitted_edges.sort(key=lambda edge: (-int(edge["weight"]), edge["target_id"]))

            limit_topics = max(1, min(int(top_k_topics), 20))
            results: List[Dict[str, Any]] = []
            for emit_edge in emitted_edges:
                artifact_node = self._nodes.get(emit_edge["target_id"])
                if artifact_node is None:
                    continue

                session_nodes: List[Dict[str, Any]] = []
                for edge in self._edges.values():
                    if edge["relation"] != "contains" or edge["target_id"] != artifact_node["node_id"]:
                        continue
                    source_node = self._nodes.get(edge["source_id"])
                    if source_node is None or source_node["node_type"] != "session":
                        continue
                    if session_filter_node_id and source_node["node_id"] != session_filter_node_id:
                        continue
                    session_nodes.append(source_node)

                if session_filter_node_id and not session_nodes:
                    continue

                reference_edges = [
                    edge
                    for edge in self._edges.values()
                    if edge["relation"] == "references" and edge["source_id"] == artifact_node["node_id"]
                ]
                reference_edges.sort(key=lambda edge: (-int(edge["weight"]), edge["target_id"]))
                topics: List[Dict[str, Any]] = []
                for edge in reference_edges[:limit_topics]:
                    topic_node = self._nodes.get(edge["target_id"])
                    if topic_node is None or topic_node["node_type"] != "topic":
                        continue
                    topics.append(
                        {
                            "topic": topic_node["label"],
                            "weight": int(edge["weight"]),
                        }
                    )

                results.append(
                    {
                        "tool": tool_node["label"],
                        "artifact": artifact_node["label"],
                        "sessions": sorted({node["label"] for node in session_nodes}),
                        "topics": topics,
                        "emit_weight": int(emit_edge["weight"]),
                    }
                )
            return results

    def query_topic_co_occurrence(self, topic: str, *, top_k: int = 8) -> List[Dict[str, Any]]:
        normalized_topic = _normalize_topic(topic)
        if not normalized_topic:
            return []

        with self._lock:
            self._ensure_loaded()
            topic_node_id = _build_node_id("topic", normalized_topic)
            if topic_node_id not in self._nodes:
                return []

            neighbors: List[Dict[str, Any]] = []
            for edge in self._edges.values():
                if edge["relation"] != "co_occurs":
                    continue
                if edge["source_id"] == topic_node_id:
                    other_id = edge["target_id"]
                elif edge["target_id"] == topic_node_id:
                    other_id = edge["source_id"]
                else:
                    continue
                other_node = self._nodes.get(other_id)
                if other_node is None or other_node["node_type"] != "topic":
                    continue
                neighbors.append({"topic": other_node["label"], "weight": int(edge["weight"])})

            neighbors.sort(key=lambda item: (-item["weight"], item["topic"]))
            return neighbors[: max(1, min(int(top_k), 20))]

    def size(self) -> Dict[str, int]:
        with self._lock:
            self._ensure_loaded()
            return {"nodes": len(self._nodes), "edges": len(self._edges)}


def _default_graph_path() -> Path:
    try:
        from system.config import get_config

        cfg = get_config()
        log_dir = Path(getattr(cfg.system, "log_dir", "logs"))
    except Exception:
        log_dir = Path("logs")
    return log_dir / "episodic_memory" / "semantic_graph.json"


_semantic_graph_singleton_lock = threading.Lock()
_semantic_graph_singleton: Optional[SemanticGraphStore] = None


def get_semantic_graph() -> SemanticGraphStore:
    global _semantic_graph_singleton
    if _semantic_graph_singleton is None:
        with _semantic_graph_singleton_lock:
            if _semantic_graph_singleton is None:
                _semantic_graph_singleton = SemanticGraphStore()
    return _semantic_graph_singleton


def update_semantic_graph_from_records(
    session_id: str,
    records: Sequence["EpisodicRecord"],
    *,
    graph: Optional[SemanticGraphStore] = None,
) -> int:
    store = graph or get_semantic_graph()
    return store.update_from_records(session_id, records)


def query_tool_artifact_topology(
    tool: str,
    *,
    session_id: Optional[str] = None,
    top_k_topics: int = 8,
    graph: Optional[SemanticGraphStore] = None,
) -> List[Dict[str, Any]]:
    store = graph or get_semantic_graph()
    return store.query_tool_artifact_topology(tool, session_id=session_id, top_k_topics=top_k_topics)


ToolResultTopologyStore = SemanticGraphStore


def get_tool_result_topology() -> SemanticGraphStore:
    return get_semantic_graph()


def update_tool_result_topology_from_records(
    session_id: str,
    records: Sequence["EpisodicRecord"],
    *,
    graph: Optional[SemanticGraphStore] = None,
) -> int:
    store = graph or get_tool_result_topology()
    return store.update_from_records(session_id, records)


def query_tool_result_topology(
    tool: str,
    *,
    session_id: Optional[str] = None,
    top_k_topics: int = 8,
    graph: Optional[SemanticGraphStore] = None,
) -> List[Dict[str, Any]]:
    store = graph or get_tool_result_topology()
    return store.query_tool_artifact_topology(tool, session_id=session_id, top_k_topics=top_k_topics)


__all__ = [
    "SemanticGraphStore",
    "ToolResultTopologyStore",
    "get_semantic_graph",
    "get_tool_result_topology",
    "query_tool_artifact_topology",
    "query_tool_result_topology",
    "update_semantic_graph_from_records",
    "update_tool_result_topology_from_records",
]
