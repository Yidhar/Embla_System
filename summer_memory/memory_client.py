"""
Local-only memory client shim.

Remote memory microservice has been removed from runtime architecture.
`get_remote_memory_client()` always returns None so callers use local GRAG flow.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger("EmblaMemoryClient")

QuintupleType = Tuple[str, str, str, str, str]


class RemoteMemoryClient:
    """
    Kept for backward compatibility only.
    In local-only mode this client is never instantiated by project code.
    """

    def __init__(self, base_url: str, token: Optional[str] = None, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        headers: Dict[str, str] = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = httpx.AsyncClient(timeout=timeout, headers=headers)

    async def close(self):
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        try:
            resp = await self._client.request(method, url, **kwargs)
            resp.raise_for_status()
            return resp.json() if resp.content else {"success": False, "error": "empty response"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def health_check(self) -> Dict[str, Any]:
        return await self._request("GET", "/health")

    async def get_stats(self) -> Dict[str, Any]:
        return await self._request("GET", "/stats")

    async def add_quintuples(self, quintuples: List[QuintupleType]) -> Dict[str, Any]:
        return await self._request("POST", "/quintuples", json={"quintuples": quintuples})

    async def get_quintuples(self, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        return await self._request("GET", f"/quintuples?limit={limit}&offset={offset}")

    async def query_by_keywords(self, keywords: List[str], limit: int = 10) -> Dict[str, Any]:
        return await self._request("POST", "/quintuples/query", json={"keywords": keywords, "limit": limit})

    async def query_by_entity(self, entity_name: str, direction: str = "both", limit: int = 20) -> Dict[str, Any]:
        return await self._request("GET", f"/quintuples/entity/{entity_name}?direction={direction}&limit={limit}")

    async def add_memory(
        self,
        user_input: str = "",
        ai_response: str = "",
        quintuples: Optional[List[QuintupleType]] = None,
    ) -> Dict[str, Any]:
        data: Dict[str, Any] = {"user_input": user_input, "ai_response": ai_response}
        if quintuples:
            data["quintuples"] = quintuples
        return await self._request("POST", "/add", json=data)

    async def query_memory(self, question: str = "", keywords: Optional[List[str]] = None, limit: int = 5) -> Dict[str, Any]:
        data: Dict[str, Any] = {"question": question, "limit": limit}
        if keywords:
            data["keywords"] = keywords
        return await self._request("POST", "/query", json=data)

    async def get_entities(self, entity_type: Optional[str] = None, limit: int = 100) -> Dict[str, Any]:
        params = f"?limit={limit}"
        if entity_type:
            params += f"&type={entity_type}"
        return await self._request("GET", f"/graph/entities{params}")

    async def get_relationships(self) -> Dict[str, Any]:
        return await self._request("GET", "/graph/relationships")


_client: Optional[RemoteMemoryClient] = None


def get_remote_memory_client() -> Optional[RemoteMemoryClient]:
    """
    Local-only behavior: always disable remote memory microservice.
    """
    global _client
    if _client is not None:
        logger.info("Remote memory client disabled in local-only mode; releasing stale client")
        _client = None
    return None
