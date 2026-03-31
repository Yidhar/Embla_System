from __future__ import annotations

import json

from summer_memory import quintuple_graph as graph_mod


def test_store_quintuples_persists_file_when_neo4j_unavailable(monkeypatch, tmp_path) -> None:
    quintuples_file = tmp_path / "knowledge_graph" / "quintuples.json"
    monkeypatch.setattr(graph_mod, "QUINTUPLES_FILE", str(quintuples_file))
    monkeypatch.setattr(graph_mod, "get_graph", lambda: None)

    ok = graph_mod.store_quintuples([("小明", "人物", "在", "公园", "地点")])

    assert ok is True
    assert json.loads(quintuples_file.read_text(encoding="utf-8")) == [["小明", "人物", "在", "公园", "地点"]]
