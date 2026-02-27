from __future__ import annotations

from apiserver.api_server import _build_mcp_runtime_snapshot, _build_mcp_task_snapshot


def test_build_mcp_runtime_snapshot_counts_builtin_and_external_services() -> None:
    snapshot = _build_mcp_runtime_snapshot(
        registry_status={
            "registered_services": 2,
            "cached_manifests": 2,
            "service_names": ["weather-time", "game-guide"],
        },
        external_services=["external-ci", "weather-time"],
    )

    assert snapshot["server"] == "online"
    assert snapshot["tasks"]["total"] == 3
    assert snapshot["tasks"]["completed"] == 2
    assert snapshot["registry"]["service_names"] == ["weather-time", "game-guide"]
    assert snapshot["registry"]["external_service_names"] == ["external-ci"]


def test_build_mcp_task_snapshot_supports_status_filter() -> None:
    snapshot = {
        "registry": {
            "service_names": ["weather-time"],
            "external_service_names": ["external-ci"],
        }
    }

    all_tasks = _build_mcp_task_snapshot(snapshot=snapshot)
    assert all_tasks["total"] == 2

    registered = _build_mcp_task_snapshot("registered", snapshot=snapshot)
    configured = _build_mcp_task_snapshot("configured", snapshot=snapshot)

    assert registered["total"] == 1
    assert registered["tasks"][0]["source"] == "builtin"
    assert configured["total"] == 1
    assert configured["tasks"][0]["source"] == "mcporter"
