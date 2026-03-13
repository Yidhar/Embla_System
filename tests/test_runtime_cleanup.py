from __future__ import annotations

import aiohttp
import litellm

from litellm.llms.custom_httpx.aiohttp_handler import BaseLLMAIOHTTPHandler

from system.runtime_cleanup import close_runtime_network_clients


def test_close_runtime_network_clients_closes_litellm_aiohttp_handlers(monkeypatch) -> None:
    original_cache = getattr(litellm.in_memory_llm_clients_cache, "cache_dict", None)

    async def _run() -> None:
        session = aiohttp.ClientSession()
        handler = BaseLLMAIOHTTPHandler(client_session=session)
        handler._owns_session = True
        litellm.in_memory_llm_clients_cache.cache_dict = {"test-handler": handler}

        async def _fake_close_global_mcp_pool():
            return None

        monkeypatch.setattr(
            "agents.runtime.mcp_client.close_global_mcp_pool",
            _fake_close_global_mcp_pool,
        )

        report = await close_runtime_network_clients()

        assert report["litellm"]["attempted"] is True
        assert report["litellm"]["closed"] is True
        assert report["mcp_pool"]["attempted"] is True
        assert session.closed is True

    try:
        import asyncio

        asyncio.run(_run())
    finally:
        litellm.in_memory_llm_clients_cache.cache_dict = original_cache if isinstance(original_cache, dict) else {}
