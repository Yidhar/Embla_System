from __future__ import annotations

import asyncio

import apiserver.api_server
from apiserver import routes_ops as api_server


def test_ops_memory_graph_payload_contains_vector_index(monkeypatch):
    async def _fake_stats():
        return {
            "status": "success",
            "memory_stats": {
                "enabled": True,
                "total_quintuples": 3,
                "active_tasks": 0,
                "task_manager": {"pending_tasks": 0, "running_tasks": 0, "failed_tasks": 0},
                "vector_index": {
                    "enabled": True,
                    "index_name": "entity_embedding_index",
                    "state": "online",
                    "ready": True,
                },
            },
        }

    async def _fake_quintuples():
        return {
            "status": "success",
            "quintuples": [
                {
                    "subject": "服务A",
                    "subject_type": "Service",
                    "predicate": "depends_on",
                    "object": "数据库B",
                    "object_type": "Database",
                }
            ],
            "count": 1,
        }

    monkeypatch.setattr(api_server, "get_memory_stats", _fake_stats)
    monkeypatch.setattr(api_server, "get_quintuples", _fake_quintuples)

    payload = asyncio.run(api_server._ops_build_memory_graph_payload(sample_limit=20))
    assert payload["status"] == "success"
    assert payload["severity"] == "ok"
    assert payload["data"]["summary"]["vector_index_state"] == "online"
    assert payload["data"]["summary"]["vector_index_ready"] is True
    assert payload["data"]["vector_index"]["index_name"] == "entity_embedding_index"


def test_ops_memory_graph_payload_normalizes_legacy_shapes(monkeypatch):
    async def _fake_stats():
        return {
            "status": "success",
            "memory_stats": {
                "total_quintuples": 2,
                "active_tasks": 0,
                "tasks": {"pending_tasks": 1, "running_tasks": 0, "failed_tasks": 0},
                "vectorIndex": {
                    "enabled": True,
                    "index_name": "legacy_entity_index",
                    "status": "warming",
                    "ready": False,
                },
            },
        }

    async def _fake_quintuples():
        return {
            "status": "success",
            "quintuples": [
                {
                    "entity": "服务A",
                    "entity_type": "Service",
                    "relation": "depends_on",
                    "target": "数据库B",
                    "target_type": "Database",
                },
                ["服务A", "Service", "owned_by", "团队C", "Team"],
            ],
            "count": 2,
        }

    monkeypatch.setattr(api_server, "get_memory_stats", _fake_stats)
    monkeypatch.setattr(api_server, "get_quintuples", _fake_quintuples)

    payload = asyncio.run(api_server._ops_build_memory_graph_payload(sample_limit=20))

    assert payload["status"] == "success"
    assert payload["severity"] == "ok"
    assert payload["data"]["summary"]["enabled"] is True
    assert payload["data"]["summary"]["pending_tasks"] == 1
    assert payload["data"]["summary"]["vector_index_state"] == "warming"
    assert payload["data"]["vector_index"]["index_name"] == "legacy_entity_index"
    assert payload["data"]["graph_sample"][0]["predicate"] == "depends_on"
    assert any(item["relation"] == "depends_on" for item in payload["data"]["relation_hotspots"])


def test_ops_memory_search_payload_normalizes_legacy_shapes(monkeypatch):
    async def _fake_query(_keywords):
        return {
            "backend": "test_backend",
            "rows": [
                {
                    "entity": "服务A",
                    "entity_type": "Service",
                    "relation": "depends_on",
                    "target": "数据库B",
                    "target_type": "Database",
                },
                ["服务A", "Service", "owned_by", "团队C", "Team"],
            ],
        }

    monkeypatch.setattr(api_server, "_ops_query_memory_quintuples_by_keywords", _fake_query)

    payload = asyncio.run(api_server._ops_build_memory_search_payload(keywords="服务A, 团队C", limit=1))

    assert payload["status"] == "success"
    assert payload["severity"] == "ok"
    assert payload["data"]["summary"]["keyword_count"] == 2
    assert payload["data"]["summary"]["result_count"] == 2
    assert payload["data"]["summary"]["returned_count"] == 1
    assert payload["data"]["summary"]["truncated"] is True
    assert payload["data"]["summary"]["backend"] == "test_backend"
    assert payload["data"]["results"][0]["predicate"] == "depends_on"
