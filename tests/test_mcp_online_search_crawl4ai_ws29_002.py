from __future__ import annotations

import asyncio
import json

from mcpserver.agent_crawl4ai.agent_crawl4ai import Crawl4AIAgent
from mcpserver.agent_online_search.agent_online_search import OnlineSearchAgent
from mcpserver.mcp_manager import MCPManager
from mcpserver.mcp_registry import MCP_REGISTRY, clear_registry, scan_and_register_mcp_agents


def test_online_search_agent_success(monkeypatch) -> None:
    agent = OnlineSearchAgent()

    async def _fake_fetch(**kwargs):
        assert kwargs["query"] == "asyncio to_thread hang"
        assert kwargs["searxng_url"].startswith("http")
        return {
            "results": [
                {
                    "title": "Result A",
                    "url": "https://example.com/a",
                    "content": "A content",
                    "engine": "google",
                    "score": 1.0,
                },
                {
                    "title": "Result B",
                    "url": "https://example.com/b",
                    "content": "B content",
                    "engine": "google",
                    "score": 0.9,
                },
            ]
        }

    monkeypatch.setattr(agent, "_fetch_from_searxng", _fake_fetch)
    raw = asyncio.run(
        agent.handle_handoff(
            {
                "tool_name": "search_web",
                "query": "asyncio to_thread hang",
                "num_results": 1,
            }
        )
    )
    payload = json.loads(raw)
    assert payload["status"] == "ok"
    assert payload["data"]["num_results"] == 1
    assert payload["data"]["results"][0]["title"] == "Result A"


def test_online_search_agent_requires_query() -> None:
    agent = OnlineSearchAgent()
    raw = asyncio.run(agent.handle_handoff({"tool_name": "search_web"}))
    payload = json.loads(raw)
    assert payload["status"] == "error"
    assert "query" in payload["message"]


def test_crawl4ai_agent_success(monkeypatch) -> None:
    agent = Crawl4AIAgent()

    async def _fake_fetch_url(**kwargs):
        assert kwargs["url"] == "https://example.com"
        html_doc = """
        <html>
          <head><title>Example Title</title></head>
          <body>
            <h1>Header</h1>
            <p>Hello <b>Embla</b> world.</p>
            <a href=\"https://example.com/docs\">Docs</a>
          </body>
        </html>
        """
        return html_doc, 200, "text/html", "https://example.com"

    monkeypatch.setattr(agent, "_fetch_url", _fake_fetch_url)
    raw = asyncio.run(
        agent.handle_handoff(
            {
                "tool_name": "crawl_page",
                "url": "https://example.com",
                "max_chars": 2000,
                "include_links": True,
            }
        )
    )
    payload = json.loads(raw)
    assert payload["status"] == "ok"
    assert payload["data"]["title"] == "Example Title"
    assert "Hello Embla world." in payload["data"]["content_text"]
    assert payload["data"]["links"][0]["href"] == "https://example.com/docs"


def test_crawl4ai_agent_requires_url() -> None:
    agent = Crawl4AIAgent()
    raw = asyncio.run(agent.handle_handoff({"tool_name": "crawl_page"}))
    payload = json.loads(raw)
    assert payload["status"] == "error"
    assert "url" in payload["message"]


def test_builtin_registry_contains_new_services_and_alias_resolution() -> None:
    clear_registry()
    try:
        registered = scan_and_register_mcp_agents("mcpserver")
        assert "online_search" in registered
        assert "crawl4ai" in registered

        manager = MCPManager()
        MCP_REGISTRY["app_launcher"] = object()
        assert manager._resolve_local_service_name("open_launcher") == "app_launcher"
    finally:
        clear_registry()
