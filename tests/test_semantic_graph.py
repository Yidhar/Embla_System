from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from agents.memory.episodic_memory import EpisodicRecord
from agents.memory.semantic_graph import SemanticGraphStore, update_semantic_graph_from_records


def _make_case_dir() -> Path:
    root = Path(".tmp_test_semantic_graph")
    root.mkdir(parents=True, exist_ok=True)
    case_dir = root / f"case_{uuid.uuid4().hex}"
    case_dir.mkdir(parents=True, exist_ok=True)
    return case_dir


def test_semantic_graph_builds_tool_artifact_topic_session_topology():
    case_dir = _make_case_dir()
    try:
        graph_path = case_dir / "semantic_graph.json"
        store = SemanticGraphStore(graph_path=graph_path, max_topics_per_record=10)

        records = [
            EpisodicRecord(
                record_id="ep_tool_001",
                session_id="sess-alpha",
                source_tool="native:run_cmd",
                narrative_summary="修复 npm install E401 鉴权失败，更新 token 后恢复。",
                forensic_artifact_ref="artifact_cmd_001",
                fetch_hints=["jsonpath:$..error_code", "grep:E401"],
                timestamp=1_700_000_101.0,
            )
        ]

        mutations = update_semantic_graph_from_records("sess-alpha", records, graph=store)
        assert mutations > 0

        topology = store.query_tool_artifact_topology("native:run_cmd", session_id="sess-alpha", top_k_topics=10)
        assert topology
        assert topology[0]["artifact"] == "artifact_cmd_001"
        assert topology[0]["sessions"] == ["sess-alpha"]

        topic_names = {item["topic"] for item in topology[0]["topics"]}
        assert "e401" in topic_names
        assert "error_code" in topic_names

        co_topics = store.query_topic_co_occurrence("e401", top_k=10)
        assert any(item["topic"] == "error_code" for item in co_topics)
    finally:
        shutil.rmtree(case_dir, ignore_errors=True)


def test_semantic_graph_reload_and_session_filter():
    case_dir = _make_case_dir()
    try:
        graph_path = case_dir / "semantic_graph.json"
        store = SemanticGraphStore(graph_path=graph_path, max_topics_per_record=10)

        record_a = EpisodicRecord(
            record_id="ep_shared_001",
            session_id="sess-a",
            source_tool="native:run_cmd",
            narrative_summary="npm install 失败，提示 E401 token 过期。",
            forensic_artifact_ref="artifact_shared",
            fetch_hints=["grep:E401"],
            timestamp=1_700_000_201.0,
        )
        record_b = EpisodicRecord(
            record_id="ep_shared_002",
            session_id="sess-b",
            source_tool="native:run_cmd",
            narrative_summary="同一 artifact 在另一次会话中关联 timeout 与 retry 策略。",
            forensic_artifact_ref="artifact_shared",
            fetch_hints=["grep:timeout"],
            timestamp=1_700_000_301.0,
        )

        store.update_from_records("sess-a", [record_a])
        store.update_from_records("sess-b", [record_b])

        reloaded = SemanticGraphStore(graph_path=graph_path, max_topics_per_record=10)
        full_view = reloaded.query_tool_artifact_topology("native:run_cmd")
        assert len(full_view) == 1
        assert full_view[0]["artifact"] == "artifact_shared"
        assert set(full_view[0]["sessions"]) == {"sess-a", "sess-b"}

        sess_b_view = reloaded.query_tool_artifact_topology("native:run_cmd", session_id="sess-b")
        assert len(sess_b_view) == 1
        assert sess_b_view[0]["sessions"] == ["sess-b"]
    finally:
        shutil.rmtree(case_dir, ignore_errors=True)
