"""MCP online search agent backed by SearXNG."""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List

import aiohttp

from system.config import get_config


class OnlineSearchAgent:
    """Search the web through a configured SearXNG endpoint."""

    name = "Online Search Agent"

    def __init__(self) -> None:
        config = get_config()
        self._default_searxng_url = str(config.online_search.searxng_url or "").strip()
        self._default_engines = list(config.online_search.engines or [])
        self._default_num_results = int(config.online_search.num_results or 5)

    async def handle_handoff(self, task: Dict[str, Any]) -> str:
        try:
            tool_name = str(task.get("tool_name") or "").strip().lower()
            if tool_name not in {
                "search_web",
                "online_search",
                "web_search",
                "search",
            }:
                return self._json_error(
                    "未知工具，仅支持 search_web/online_search/web_search/search",
                    tool_name=tool_name,
                )

            query = str(task.get("query") or task.get("keyword") or "").strip()
            if not query:
                return self._json_error("缺少 query 参数", tool_name=tool_name)

            searxng_url = str(task.get("searxng_url") or self._default_searxng_url).strip()
            if not searxng_url:
                return self._json_error("未配置 searxng_url", tool_name=tool_name)

            requested_results = task.get("num_results", task.get("top_k", self._default_num_results))
            try:
                num_results = max(1, min(20, int(requested_results)))
            except (TypeError, ValueError):
                num_results = self._default_num_results

            requested_engines = task.get("engines")
            engines = self._normalize_engines(requested_engines) or self._normalize_engines(self._default_engines)

            timeout_raw = task.get("timeout_seconds", 20)
            try:
                timeout_seconds = max(1.0, min(120.0, float(timeout_raw)))
            except (TypeError, ValueError):
                timeout_seconds = 20.0

            payload = await self._fetch_from_searxng(
                query=query,
                searxng_url=searxng_url,
                engines=engines,
                timeout_seconds=timeout_seconds,
            )
            normalized_results = self._normalize_results(payload, limit=num_results)

            return json.dumps(
                {
                    "status": "ok",
                    "message": f"搜索完成，返回 {len(normalized_results)} 条结果",
                    "data": {
                        "query": query,
                        "searxng_url": searxng_url,
                        "engines": engines,
                        "num_results": len(normalized_results),
                        "results": normalized_results,
                    },
                },
                ensure_ascii=False,
            )
        except Exception as exc:
            return self._json_error(str(exc), tool_name=str(task.get("tool_name") or ""))

    async def _fetch_from_searxng(
        self,
        *,
        query: str,
        searxng_url: str,
        engines: List[str],
        timeout_seconds: float,
    ) -> Dict[str, Any]:
        base_url = searxng_url.rstrip("/")
        params: Dict[str, Any] = {
            "q": query,
            "format": "json",
        }
        if engines:
            params["engines"] = ",".join(engines)

        timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(f"{base_url}/search", params=params) as response:
                text = await response.text()
                if response.status >= 400:
                    raise RuntimeError(f"SearXNG 请求失败: HTTP {response.status} {text[:200]}")
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError as exc:
                    raise RuntimeError(f"SearXNG 返回非 JSON: {exc}") from exc

        if not isinstance(payload, dict):
            raise RuntimeError("SearXNG 返回格式非法")
        return payload

    @staticmethod
    def _normalize_results(payload: Dict[str, Any], *, limit: int) -> List[Dict[str, Any]]:
        raw_rows = payload.get("results")
        if not isinstance(raw_rows, list):
            return []

        normalized: List[Dict[str, Any]] = []
        for row in raw_rows:
            if not isinstance(row, dict):
                continue
            normalized.append(
                {
                    "title": str(row.get("title") or "").strip(),
                    "url": str(row.get("url") or row.get("link") or "").strip(),
                    "content": str(row.get("content") or row.get("snippet") or "").strip(),
                    "engine": str(row.get("engine") or "").strip(),
                    "score": row.get("score"),
                    "published_date": str(row.get("publishedDate") or row.get("published") or "").strip(),
                }
            )
            if len(normalized) >= limit:
                break
        return normalized

    @staticmethod
    def _normalize_engines(engines: Any) -> List[str]:
        if isinstance(engines, str):
            parts = engines.split(",")
        elif isinstance(engines, Iterable):
            parts = [str(item) for item in engines]
        else:
            return []

        normalized: List[str] = []
        for part in parts:
            item = str(part or "").strip()
            if not item:
                continue
            if item not in normalized:
                normalized.append(item)
        return normalized

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
