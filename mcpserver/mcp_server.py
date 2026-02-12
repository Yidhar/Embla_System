"""MCP Server - 独立FastAPI服务，提供统一的MCP工具调度HTTP API

外部用户/服务可通过 POST /schedule 调用已注册的MCP工具。
内部 background_analyzer 走 in-process 直调，不经过此HTTP层。
"""

import asyncio
import json
from contextlib import asynccontextmanager
from typing import Dict, Any, List

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from system.config import logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan - 启动时初始化MCP服务"""
    logger.info("[MCP Server] 正在初始化...")

    from mcpserver.mcp_manager import get_mcp_manager
    get_mcp_manager()

    from mcpserver.mcp_registry import auto_register_mcp
    auto_register_mcp()

    logger.info("[MCP Server] 初始化完成")
    yield

    from mcpserver.mcp_manager import get_mcp_manager
    await get_mcp_manager().cleanup()
    logger.info("[MCP Server] 已关闭")


app = FastAPI(title="NagaAgent MCP Server", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ScheduleRequest(BaseModel):
    query: str = ""
    tool_calls: list = []
    session_id: str = ""
    callback_url: str = ""


class ToolCallRequest(BaseModel):
    """单个工具调用请求"""
    service_name: str
    tool_name: str = ""
    message: str = ""
    # 允许透传任意额外参数
    params: Dict[str, Any] = {}


@app.post("/schedule")
async def schedule_task(req: ScheduleRequest):
    """调度MCP任务 - 并行执行所有 tool_calls，同步返回结果

    外部调用统一入口。多个 tool_calls 并行执行，全部完成后一次性返回结果。
    如果指定了 callback_url，也会异步回调。
    """
    from mcpserver.mcp_manager import get_mcp_manager
    manager = get_mcp_manager()

    if not req.tool_calls:
        return {"status": "ok", "results": [], "message": "无工具调用"}

    async def _execute_one(call: Dict[str, Any]) -> Dict[str, Any]:
        service_name = call.get("service_name", "")
        tool_name = call.get("tool_name", "")
        try:
            result = await manager.unified_call(service_name, call)
            return {"service_name": service_name, "tool_name": tool_name, "status": "ok", "result": result}
        except Exception as e:
            logger.error(f"[MCP Server] 工具调用失败: service={service_name}, error={e}")
            return {"service_name": service_name, "tool_name": tool_name, "status": "error", "error": str(e)}

    # 并行执行所有工具调用
    results = await asyncio.gather(*[_execute_one(call) for call in req.tool_calls], return_exceptions=False)

    response = {"status": "ok", "results": list(results)}

    # 如果有回调地址，异步发送结果（不阻塞返回）
    if req.callback_url:
        asyncio.create_task(_send_callback(req.callback_url, req.session_id, results))

    return response


@app.post("/call")
async def call_tool(req: ToolCallRequest):
    """调用单个MCP工具 - 同步返回结果

    简化接口，直接指定 service_name 和参数。
    """
    from mcpserver.mcp_manager import get_mcp_manager
    manager = get_mcp_manager()

    tool_call = {"service_name": req.service_name, "tool_name": req.tool_name, "message": req.message, **req.params}

    try:
        result = await manager.unified_call(req.service_name, tool_call)
        return {"status": "ok", "result": result}
    except Exception as e:
        logger.error(f"[MCP Server] 工具调用失败: service={req.service_name}, error={e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/services")
async def list_services():
    """列出已注册的MCP服务"""
    from mcpserver.mcp_registry import get_all_services_info, get_service_statistics
    return {
        "services": get_all_services_info(),
        "statistics": get_service_statistics(),
    }


@app.get("/status")
async def server_status():
    """服务器状态"""
    from mcpserver.mcp_registry import get_service_statistics
    stats = get_service_statistics()
    return {
        "status": "running",
        "registered_services": stats["total_services"],
        "total_tools": stats["total_tools"],
    }


async def _send_callback(callback_url: str, session_id: str, results: List[Dict[str, Any]]):
    """异步回调通知"""
    try:
        import httpx

        payload = {
            "session_id": session_id,
            "action": "show_mcp_result",
            "results": [r for r in results if isinstance(r, dict)],
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            for attempt in range(3):
                try:
                    resp = await client.post(callback_url, json=payload)
                    if resp.status_code == 200:
                        logger.info(f"[MCP Server] 回调成功: {callback_url}")
                        return
                except Exception as e:
                    logger.warning(f"[MCP Server] 回调重试 {attempt + 1}/3: {e}")
                    await asyncio.sleep(1)
    except Exception as e:
        logger.error(f"[MCP Server] 回调失败: {e}")
