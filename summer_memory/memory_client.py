"""
NagaMemory 远程记忆微服务客户端

轻量级 HTTP 客户端，将本地 summer_memory 的图谱/五元组操作
代理到远程 NagaMemory 服务（NebulaGraph 后端）。

用法::

    from summer_memory.memory_client import get_remote_memory_client

    client = get_remote_memory_client()
    if client is None:
        # memory_server 未启用，走本地 summer_memory 逻辑
        ...
    else:
        stats = await client.get_stats()
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger("NagaMemoryClient")

QuintupleType = Tuple[str, str, str, str, str]


class RemoteMemoryClient:
    """异步 NagaMemory 远程客户端"""

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
            if not resp.content:
                logger.warning(f"NagaMemory 返回空响应 [{method} {path}] status={resp.status_code}")
                return {"success": False, "error": "服务返回空响应，请检查网络或代理设置"}
            return resp.json()
        except httpx.HTTPError as e:
            logger.error(f"NagaMemory 请求失败 [{method} {path}]: {e}")
            return {"success": False, "error": str(e)}
        except ValueError as e:
            logger.error(f"NagaMemory 响应解析失败 [{method} {path}]: {e}")
            return {"success": False, "error": f"服务返回非JSON响应: {e}"}

    # ---- 健康 / 统计 ----

    async def health_check(self) -> Dict[str, Any]:
        return await self._request("GET", "/health")

    async def get_stats(self) -> Dict[str, Any]:
        return await self._request("GET", "/stats")

    # ---- 五元组 ----

    async def add_quintuples(self, quintuples: List[QuintupleType]) -> Dict[str, Any]:
        return await self._request("POST", "/quintuples", json={"quintuples": quintuples})

    async def get_quintuples(self, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        return await self._request("GET", f"/quintuples?limit={limit}&offset={offset}")

    async def query_by_keywords(self, keywords: List[str], limit: int = 10) -> Dict[str, Any]:
        return await self._request("POST", "/quintuples/query", json={"keywords": keywords, "limit": limit})

    async def query_by_entity(self, entity_name: str, direction: str = "both", limit: int = 20) -> Dict[str, Any]:
        return await self._request("GET", f"/quintuples/entity/{entity_name}?direction={direction}&limit={limit}")

    # ---- 记忆（对话级） ----

    async def add_memory(self, user_input: str = "", ai_response: str = "",
                         quintuples: Optional[List[QuintupleType]] = None) -> Dict[str, Any]:
        data: Dict[str, Any] = {"user_input": user_input, "ai_response": ai_response}
        if quintuples:
            data["quintuples"] = quintuples
        return await self._request("POST", "/add", json=data)

    async def query_memory(self, question: str = "", keywords: Optional[List[str]] = None,
                           limit: int = 5) -> Dict[str, Any]:
        data: Dict[str, Any] = {"question": question, "limit": limit}
        if keywords:
            data["keywords"] = keywords
        return await self._request("POST", "/query", json=data)

    # ---- 图查询 ----

    async def get_entities(self, entity_type: Optional[str] = None, limit: int = 100) -> Dict[str, Any]:
        params = f"?limit={limit}"
        if entity_type:
            params += f"&type={entity_type}"
        return await self._request("GET", f"/graph/entities{params}")

    async def get_relationships(self) -> Dict[str, Any]:
        return await self._request("GET", "/graph/relationships")


# ---- 全局单例 ----

_client: Optional[RemoteMemoryClient] = None
_client_token: Optional[str] = None


def get_remote_memory_client() -> Optional[RemoteMemoryClient]:
    """
    获取远程记忆客户端单例。

    仅当 config.memory_server.enabled == True 时返回实例，
    否则返回 None（调用方应回退到本地 summer_memory）。
    每次调用会重新检查 config，支持热更新和 token 刷新。
    """
    global _client, _client_token

    try:
        from system.config import config
        ms = config.memory_server
    except Exception as e:
        logger.warning(f"读取 memory_server 配置失败: {e}")
        return None

    if not ms.enabled:
        # 配置已关闭，清理已有客户端
        if _client is not None:
            logger.info("NagaMemory 远程客户端已因配置关闭而释放")
            _client = None
            _client_token = None
        return None

    # Token 变更时（如登录/登出/刷新），重新创建客户端
    if _client is not None and ms.token != _client_token:
        logger.info("NagaMemory token 已变更，重新创建客户端")
        _client = None

    if _client is not None:
        return _client

    try:
        _client = RemoteMemoryClient(base_url=ms.url, token=ms.token)
        _client_token = ms.token
        logger.info(f"NagaMemory 远程客户端已创建: {ms.url}")
        return _client
    except Exception as e:
        logger.warning(f"创建 NagaMemory 客户端失败: {e}")
        return None
