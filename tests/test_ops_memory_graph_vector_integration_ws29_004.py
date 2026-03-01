from __future__ import annotations

import asyncio

import apiserver.api_server as api_server


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
