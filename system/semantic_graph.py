"""Compatibility shim for semantic graph.

Canonical implementation moved to `agents.memory.semantic_graph`.
"""

from agents.memory.semantic_graph import (
    SemanticGraphStore,
    get_semantic_graph,
    query_tool_artifact_topology,
    update_semantic_graph_from_records,
)

__all__ = [
    "SemanticGraphStore",
    "get_semantic_graph",
    "query_tool_artifact_topology",
    "update_semantic_graph_from_records",
]
