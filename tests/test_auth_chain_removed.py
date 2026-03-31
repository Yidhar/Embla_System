from __future__ import annotations

from types import SimpleNamespace

import apiserver.api_server as api_server
import apiserver.llm_service as llm_service_module


def test_auth_routes_are_removed_from_api_server() -> None:
    auth_paths = {route.path for route in api_server.app.routes if route.path.startswith("/auth/")}
    assert auth_paths == set()


def test_litellm_params_use_config_without_auth_shim(monkeypatch) -> None:
    service = llm_service_module.LLMService.__new__(llm_service_module.LLMService)

    fake_cfg = SimpleNamespace(
        api=SimpleNamespace(
            api_key="cfg-key",
            base_url="https://api.example/v1",
            extra_body={"trace": "yes"},
            extra_headers={"X-Test": "1"},
        )
    )
    monkeypatch.setattr(llm_service_module, "get_config", lambda: fake_cfg)

    params = service._get_litellm_params(None, None)

    assert params["api_key"] == "cfg-key"
    assert params["api_base"] == "https://api.example/v1/"
    assert params["extra_body"] == {"trace": "yes"}
    assert params["extra_headers"] == {"X-Test": "1"}
