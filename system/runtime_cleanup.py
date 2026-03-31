from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any, Dict


logger = logging.getLogger(__name__)


async def close_runtime_network_clients() -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "litellm": {"attempted": False, "closed": False, "error": ""},
        "mcp_pool": {"attempted": False, "closed": False, "error": ""},
    }

    try:
        import litellm

        close_litellm_async_clients = getattr(litellm, "close_litellm_async_clients", None)
        if callable(close_litellm_async_clients):
            report["litellm"]["attempted"] = True
            await close_litellm_async_clients()
            report["litellm"]["closed"] = True
    except Exception as exc:
        report["litellm"]["error"] = str(exc)
        logger.debug("Failed to close LiteLLM async clients", exc_info=True)

    try:
        from agents.runtime.mcp_client import close_global_mcp_pool

        report["mcp_pool"]["attempted"] = True
        await close_global_mcp_pool()
        report["mcp_pool"]["closed"] = True
    except Exception as exc:
        report["mcp_pool"]["error"] = str(exc)
        logger.debug("Failed to close global MCP pool", exc_info=True)

    return report


def close_runtime_network_clients_sync() -> Dict[str, Any]:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(close_runtime_network_clients())

    result: Dict[str, Any] = {}

    def _worker() -> None:
        try:
            result["value"] = asyncio.run(close_runtime_network_clients())
        except Exception as exc:
            result["error"] = str(exc)

    thread = threading.Thread(target=_worker, name="embla-runtime-cleanup", daemon=True)
    thread.start()
    thread.join()
    if "error" in result:
        return {
            "litellm": {"attempted": True, "closed": False, "error": str(result["error"])},
            "mcp_pool": {"attempted": True, "closed": False, "error": str(result["error"])},
        }
    return dict(result.get("value") or {})


__all__ = ["close_runtime_network_clients", "close_runtime_network_clients_sync"]
