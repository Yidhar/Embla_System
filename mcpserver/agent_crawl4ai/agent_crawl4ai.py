"""MCP crawl agent for structured web content extraction."""

from __future__ import annotations

import html
import json
import re
from typing import Any, Dict, List, Tuple

import aiohttp

from system.config import get_config


_SCRIPT_STYLE_RE = re.compile(r"(?is)<(script|style).*?>.*?</\\1>")
_TAG_RE = re.compile(r"(?is)<[^>]+>")
_TITLE_RE = re.compile(r"(?is)<title[^>]*>(.*?)</title>")
_LINK_RE = re.compile(r"(?is)<a[^>]+href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>")
_WHITESPACE_RE = re.compile(r"\s+")


class Crawl4AIAgent:
    """Fetch web pages and return cleaned content for downstream tools."""

    name = "Crawl4AI Agent"

    def __init__(self) -> None:
        config = get_config()
        crawl_cfg = getattr(config, "crawl4ai", None)
        self._default_timeout_seconds = 30.0
        self._default_user_agent = (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        if crawl_cfg is not None:
            timeout_ms = float(getattr(crawl_cfg, "timeout", 30000) or 30000)
            self._default_timeout_seconds = max(1.0, min(180.0, timeout_ms / 1000.0))
            user_agent = str(getattr(crawl_cfg, "user_agent", "") or "").strip()
            if user_agent:
                self._default_user_agent = user_agent

    async def handle_handoff(self, task: Dict[str, Any]) -> str:
        try:
            tool_name = str(task.get("tool_name") or "").strip().lower()
            if tool_name not in {
                "crawl_page",
                "extract_web_content",
                "fetch_page",
                "crawl",
            }:
                return self._json_error(
                    "未知工具，仅支持 crawl_page/extract_web_content/fetch_page/crawl",
                    tool_name=tool_name,
                )

            url = str(task.get("url") or task.get("link") or "").strip()
            if not url:
                return self._json_error("缺少 url 参数", tool_name=tool_name)
            if not url.startswith(("http://", "https://")):
                return self._json_error("url 仅支持 http/https", tool_name=tool_name)

            timeout_seconds = self._parse_timeout_seconds(
                task.get("timeout_seconds"),
                default=self._default_timeout_seconds,
            )
            max_chars = self._parse_max_chars(task.get("max_chars"))
            include_links = bool(task.get("include_links", True))

            html_text, status_code, content_type, final_url = await self._fetch_url(
                url=url,
                timeout_seconds=timeout_seconds,
                user_agent=self._default_user_agent,
            )

            title = self._extract_title(html_text)
            plain_text = self._extract_plain_text(html_text)
            truncated = False
            if len(plain_text) > max_chars:
                plain_text = plain_text[:max_chars]
                truncated = True

            links = self._extract_links(html_text, limit=30) if include_links else []

            return json.dumps(
                {
                    "status": "ok",
                    "message": "网页抓取完成",
                    "data": {
                        "url": url,
                        "final_url": final_url,
                        "status_code": status_code,
                        "content_type": content_type,
                        "title": title,
                        "content_text": plain_text,
                        "content_length": len(plain_text),
                        "truncated": truncated,
                        "links": links,
                    },
                },
                ensure_ascii=False,
            )
        except Exception as exc:
            return self._json_error(str(exc), tool_name=str(task.get("tool_name") or ""))

    async def _fetch_url(self, *, url: str, timeout_seconds: float, user_agent: str) -> Tuple[str, int, str, str]:
        headers = {
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(url, allow_redirects=True) as response:
                html_text = await response.text(errors="ignore")
                content_type = str(response.headers.get("Content-Type") or "")
                final_url = str(response.url)
                if response.status >= 400:
                    raise RuntimeError(f"抓取失败: HTTP {response.status}")
                return html_text, int(response.status), content_type, final_url

    @staticmethod
    def _extract_title(html_text: str) -> str:
        match = _TITLE_RE.search(html_text)
        if not match:
            return ""
        title = html.unescape(match.group(1))
        return _WHITESPACE_RE.sub(" ", title).strip()

    @staticmethod
    def _extract_plain_text(html_text: str) -> str:
        content = _SCRIPT_STYLE_RE.sub(" ", html_text)
        content = _TAG_RE.sub(" ", content)
        content = html.unescape(content)
        return _WHITESPACE_RE.sub(" ", content).strip()

    @staticmethod
    def _extract_links(html_text: str, *, limit: int) -> List[Dict[str, str]]:
        links: List[Dict[str, str]] = []
        for href, text in _LINK_RE.findall(html_text):
            normalized_href = str(href or "").strip()
            if not normalized_href:
                continue
            normalized_text = _WHITESPACE_RE.sub(" ", html.unescape(text or "")).strip()
            links.append({"href": normalized_href, "text": normalized_text})
            if len(links) >= limit:
                break
        return links

    @staticmethod
    def _parse_timeout_seconds(value: Any, *, default: float) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return default
        return max(1.0, min(180.0, parsed))

    @staticmethod
    def _parse_max_chars(value: Any) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return 6000
        return max(500, min(200000, parsed))

    @staticmethod
    def _json_error(message: str, *, tool_name: str) -> str:
        return json.dumps(
            {
                "status": "error",
                "message": message,
                "tool_name": tool_name,
                "data": {},
            },
            ensure_ascii=False,
        )
