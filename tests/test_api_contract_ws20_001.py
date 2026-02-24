from __future__ import annotations

from fastapi.testclient import TestClient

from apiserver.api_server import (
    API_CONTRACT_VERSION,
    API_DEFAULT_VERSION,
    _build_api_contract_snapshot,
    _resolve_api_deprecation_policy,
    app,
)


def test_api_contract_snapshot_contains_versioning_strategy() -> None:
    snapshot = _build_api_contract_snapshot()

    assert snapshot["api_version"] == API_DEFAULT_VERSION
    assert snapshot["contract_version"] == API_CONTRACT_VERSION
    assert API_DEFAULT_VERSION in snapshot["supported_versions"]
    assert int(snapshot["compatibility_window_days"]) > 0
    assert "/chat" in snapshot["deprecations"]


def test_unversioned_chat_route_has_deprecation_policy() -> None:
    policy = _resolve_api_deprecation_policy("/chat")
    assert isinstance(policy, dict)
    assert policy["replacement"] == "/v1/chat"
    assert _resolve_api_deprecation_policy("/v1/chat") is None


def test_v1_route_aliases_are_registered() -> None:
    route_paths = {route.path for route in app.routes}
    assert "/v1/health" in route_paths
    assert "/v1/system/info" in route_paths
    assert "/v1/chat" in route_paths
    assert "/v1/chat/stream" in route_paths
    assert "/system/api-contract" in route_paths
    assert "/v1/system/api-contract" in route_paths


def test_api_contract_headers_are_injected_for_unversioned_route() -> None:
    with TestClient(app) as client:
        resp = client.get("/health")

    assert resp.status_code == 200
    assert resp.headers.get("X-NagaAgent-Api-Version") == API_DEFAULT_VERSION
    assert resp.headers.get("X-NagaAgent-Contract-Version") == API_CONTRACT_VERSION
    assert resp.headers.get("Deprecation") == "true"
    assert resp.headers.get("Sunset")
    assert "/v1/health" in resp.headers.get("Link", "")
