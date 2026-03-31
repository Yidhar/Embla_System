from __future__ import annotations

from summer_memory import quintuple_graph as qg


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def data(self):
        return self._rows


class _FakeGraph:
    def __init__(self, rows):
        self.rows = rows

    def run(self, *_args, **_kwargs):
        return _FakeCursor(self.rows)


def test_get_vector_index_status_disabled(monkeypatch):
    monkeypatch.setattr(
        qg,
        "_resolve_vector_runtime",
        lambda: {
            "enabled": False,
            "index_name": "entity_embedding_index",
            "top_k": 8,
            "similarity": "cosine",
        },
    )
    status = qg.get_vector_index_status()
    assert status["enabled"] is False
    assert status["state"] == "disabled"


def test_get_vector_index_status_reports_neo4j_unavailable(monkeypatch):
    monkeypatch.setattr(
        qg,
        "_resolve_vector_runtime",
        lambda: {
            "enabled": True,
            "index_name": "entity_embedding_index",
            "top_k": 8,
            "similarity": "cosine",
        },
    )
    monkeypatch.setattr(qg, "get_graph", lambda: None)
    status = qg.get_vector_index_status()
    assert status["enabled"] is True
    assert status["state"] == "neo4j_unavailable"


def test_get_vector_index_status_online(monkeypatch):
    monkeypatch.setattr(
        qg,
        "_resolve_vector_runtime",
        lambda: {
            "enabled": True,
            "index_name": "entity_embedding_index",
            "top_k": 8,
            "similarity": "cosine",
        },
    )
    monkeypatch.setattr(
        qg,
        "get_graph",
        lambda: _FakeGraph([{"name": "entity_embedding_index", "type": "VECTOR", "state": "ONLINE"}]),
    )

    status = qg.get_vector_index_status()
    assert status["enabled"] is True
    assert status["state"] == "online"
    assert status["ready"] is True
