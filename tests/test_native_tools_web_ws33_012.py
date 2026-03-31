"""Tests for web_scraper and search_engine native tools (WS33-012)."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    """Run an async coroutine in a fresh event loop (test helper)."""
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_executor():
    """Create a NativeToolExecutor with mocked internals so it works in tests."""
    with patch("apiserver.native_tools.NativeExecutor"):
        from apiserver.native_tools import NativeToolExecutor

        executor = NativeToolExecutor()
        executor.project_root = MagicMock()
        return executor


_SAMPLE_HTML = """
<html>
<head><title>Test Page</title></head>
<body>
    <nav>Navigation bar</nav>
    <header>Header area</header>
    <script>var x = 1;</script>
    <style>body { color: red; }</style>
    <div>
        <p>Hello world. This is the main content.</p>
        <p>Second paragraph with useful info.</p>
    </div>
    <footer>Footer area</footer>
    <aside>Sidebar</aside>
</body>
</html>
"""


# ── web_scraper ───────────────────────────────────────────────────────────


class TestWebScraper:
    """Tests for NativeToolExecutor._web_scraper."""

    def test_missing_url_raises(self) -> None:
        executor = _make_executor()
        with pytest.raises(ValueError, match="web_scraper 缺少 url"):
            _run(executor._web_scraper({}))

    def test_empty_url_raises(self) -> None:
        executor = _make_executor()
        with pytest.raises(ValueError, match="web_scraper 缺少 url"):
            _run(executor._web_scraper({"url": "  "}))

    def test_fetches_and_extracts_text(self) -> None:
        executor = _make_executor()

        mock_response = MagicMock()
        mock_response.text = _SAMPLE_HTML
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = _run(executor._web_scraper({"url": "https://example.com"}))

        assert "[url] https://example.com" in result
        assert "[title] Test Page" in result
        assert "Hello world" in result
        assert "Second paragraph" in result

    def test_strips_script_style_nav_footer(self) -> None:
        executor = _make_executor()

        mock_response = MagicMock()
        mock_response.text = _SAMPLE_HTML
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = _run(executor._web_scraper({"url": "https://example.com"}))

        # These tags should have been decomposed
        assert "var x = 1" not in result
        assert "color: red" not in result
        assert "Navigation bar" not in result
        assert "Footer area" not in result
        assert "Header area" not in result
        assert "Sidebar" not in result

    def test_max_chars_truncation(self) -> None:
        executor = _make_executor()
        long_html = "<html><head><title>T</title></head><body><p>" + "A" * 10000 + "</p></body></html>"

        mock_response = MagicMock()
        mock_response.text = long_html
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = _run(executor._web_scraper({"url": "https://example.com", "max_chars": 500}))

        # The [content] section should be truncated
        content_start = result.index("[content]")
        content_body = result[content_start + len("[content]\n"):]
        assert len(content_body) <= 500


# ── search_engine ─────────────────────────────────────────────────────────


_SEARXNG_RESPONSE = {
    "results": [
        {"title": "Result One", "url": "https://example.com/1", "content": "First result snippet text."},
        {"title": "Result Two", "url": "https://example.com/2", "content": "Second result snippet text."},
        {"title": "Result Three", "url": "https://example.com/3", "content": "Third result snippet."},
    ]
}


class TestSearchEngine:
    """Tests for NativeToolExecutor._search_engine."""

    def test_missing_query_raises(self) -> None:
        executor = _make_executor()
        with pytest.raises(ValueError, match="search_engine 缺少 query"):
            _run(executor._search_engine({}))

    def test_empty_query_raises(self) -> None:
        executor = _make_executor()
        with pytest.raises(ValueError, match="search_engine 缺少 query"):
            _run(executor._search_engine({"query": ""}))

    def test_searxng_success(self) -> None:
        executor = _make_executor()

        mock_response = MagicMock()
        mock_response.json = MagicMock(return_value=_SEARXNG_RESPONSE)
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        mock_cfg = MagicMock()
        mock_cfg.online_search.searxng_url = "http://localhost:8080"

        with (
            patch("httpx.AsyncClient", return_value=mock_client),
            patch("system.config.get_config", return_value=mock_cfg),
        ):
            result = _run(executor._search_engine({"query": "test query", "max_results": 3}))

        assert "[query] test query" in result
        assert "SearxNG" in result
        assert "Result One" in result
        assert "https://example.com/1" in result
        assert "Result Two" in result
        assert "[results] 3" in result

    def test_searxng_max_results_limits(self) -> None:
        executor = _make_executor()

        mock_response = MagicMock()
        mock_response.json = MagicMock(return_value=_SEARXNG_RESPONSE)
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        mock_cfg = MagicMock()
        mock_cfg.online_search.searxng_url = "http://localhost:8080"

        with (
            patch("httpx.AsyncClient", return_value=mock_client),
            patch("system.config.get_config", return_value=mock_cfg),
        ):
            result = _run(executor._search_engine({"query": "test", "max_results": 2}))

        assert "[results] 2" in result
        assert "Result Three" not in result

    def test_falls_back_to_local_when_searxng_unavailable(self) -> None:
        executor = _make_executor()

        mock_cfg = MagicMock()
        mock_cfg.online_search.searxng_url = "http://localhost:8080"

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("Connection refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        # Mock the fallback _search_keyword
        executor._search_keyword = AsyncMock(return_value="[local fallback result]")

        with (
            patch("httpx.AsyncClient", return_value=mock_client),
            patch("system.config.get_config", return_value=mock_cfg),
        ):
            result = _run(executor._search_engine({"query": "test query"}))

        assert result == "[local fallback result]"
        executor._search_keyword.assert_called_once()
        kw_call = executor._search_keyword.call_args[0][0]
        assert kw_call["keyword"] == "test query"

    def test_falls_back_when_no_searxng_url(self) -> None:
        executor = _make_executor()

        mock_cfg = MagicMock()
        mock_cfg.online_search.searxng_url = ""

        executor._search_keyword = AsyncMock(return_value="[local search]")

        with patch("system.config.get_config", return_value=mock_cfg):
            result = _run(executor._search_engine({"query": "fallback test"}))

        assert result == "[local search]"
        executor._search_keyword.assert_called_once()
