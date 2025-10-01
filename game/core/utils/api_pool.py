import asyncio
import time
from typing import Any, Callable, Awaitable, Optional


class ApiRateLimiter:
    """简单API限流器，控制并发与最小调用间隔。
    
    - 并发通过 asyncio.Semaphore 控制
    - 速率通过最小间隔时间控制
    """
    def __init__(self, max_concurrent: int = 10, min_interval_seconds: float = 0.0):
        self._sem = asyncio.Semaphore(max(1, int(max_concurrent)))
        self._min_interval = max(0.0, float(min_interval_seconds))
        self._last_call_ts = 0.0
        self._lock = asyncio.Lock()

    async def _rate_limit(self):
        async with self._lock:
            now = time.time()
            delta = now - self._last_call_ts
            if delta < self._min_interval:
                await asyncio.sleep(self._min_interval - delta)
            self._last_call_ts = time.time()

    async def call(self, func: Callable[..., Awaitable[Any]], *args, **kwargs) -> Any:
        """包装异步API调用，应用并发与速率限制。"""
        async with self._sem:
            await self._rate_limit()
            return await func(*args, **kwargs)


# 全局单例（可由外层根据配置替换）
_global_api_limiter: Optional[ApiRateLimiter] = None


def get_api_limiter() -> ApiRateLimiter:
    global _global_api_limiter
    if _global_api_limiter is None:
        _global_api_limiter = ApiRateLimiter(max_concurrent=10, min_interval_seconds=0.0)
    return _global_api_limiter


def set_api_limiter(limiter: ApiRateLimiter):
    global _global_api_limiter
    _global_api_limiter = limiter 