#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NagaAgent standalone server."""

from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException

from agentserver.task_scheduler import TaskStep, get_task_scheduler
from system.background_analyzer import get_background_analyzer
from system.config import config

logger = logging.getLogger(__name__)


class Modules:
    """Global module registry for the agent server."""

    analyzer = None
    task_scheduler = None


def _now_iso() -> str:
    return datetime.now().isoformat()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize analyzer and task scheduler."""
    try:
        Modules.analyzer = get_background_analyzer()
        Modules.task_scheduler = get_task_scheduler()

        if hasattr(config, "api") and config.api and Modules.task_scheduler:
            llm_config = {
                "model": config.api.model,
                "api_key": config.api.api_key,
                "api_base": config.api.base_url,
                "provider": getattr(config.api, "provider", ""),
                "protocol": getattr(config.api, "protocol", ""),
                "applied_proxy": bool(getattr(config.api, "applied_proxy", False)),
                "request_timeout": getattr(config.api, "request_timeout", 120),
                "extra_headers": dict(getattr(config.api, "extra_headers", {}) or {}),
                "extra_body": dict(getattr(config.api, "extra_body", {}) or {}),
            }
            Modules.task_scheduler.set_llm_config(llm_config)

        logger.info("Agent server initialized")
    except Exception as exc:
        logger.error("Agent server initialization failed: %s", exc)
        raise

    yield

    logger.info("Agent server shutdown complete")


app = FastAPI(title="NagaAgent Server", version="2.0.0", lifespan=lifespan)


@app.get("/health")
async def health_check() -> Dict[str, Any]:
    return {
        "status": "healthy",
        "timestamp": _now_iso(),
        "modules": {
            "analyzer": Modules.analyzer is not None,
            "task_scheduler": Modules.task_scheduler is not None,
        },
    }


@app.post("/schedule")
async def schedule_agent_tasks(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Legacy endpoint kept for compatibility after agent execution removal."""
    request_id = (payload or {}).get("request_id") or str(uuid.uuid4())
    session_id = (payload or {}).get("session_id")
    analysis_session_id = (payload or {}).get("analysis_session_id")
    return {
        "success": False,
        "status": "deprecated",
        "task_id": request_id,
        "session_id": session_id,
        "analysis_session_id": analysis_session_id,
        "message": "Legacy agent execution endpoint was removed. Use API server native/MCP tool loop.",
        "accepted_at": _now_iso(),
    }


@app.post("/analyze_and_execute")
async def analyze_and_execute(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Legacy endpoint kept for compatibility after agent execution removal."""
    session_id = (payload or {}).get("session_id")
    return {
        "success": False,
        "status": "deprecated",
        "session_id": session_id,
        "message": "Legacy agent execution endpoint was removed. analyze_and_execute is no longer supported.",
        "accepted_at": _now_iso(),
    }


@app.get("/tasks")
async def get_tasks(session_id: Optional[str] = None) -> Dict[str, Any]:
    if not Modules.task_scheduler:
        raise HTTPException(503, "Task scheduler is not ready")

    try:
        running_tasks = await Modules.task_scheduler.get_running_tasks()
        return {"success": True, "running_tasks": running_tasks, "session_id": session_id}
    except Exception as exc:
        logger.error("Failed to get task list: %s", exc)
        raise HTTPException(500, f"Failed to get tasks: {exc}")


@app.get("/tasks/{task_id}")
async def get_task_status(task_id: str) -> Dict[str, Any]:
    if not Modules.task_scheduler:
        raise HTTPException(503, "Task scheduler is not ready")

    try:
        task_status = await Modules.task_scheduler.get_task_status(task_id)
        if not task_status:
            raise HTTPException(404, f"Task {task_id} not found")
        return {"success": True, "task": task_status}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to get task status: %s", exc)
        raise HTTPException(500, f"Failed to get task: {exc}")


@app.get("/tasks/{task_id}/memory")
async def get_task_memory(task_id: str, include_key_facts: bool = True) -> Dict[str, Any]:
    if not Modules.task_scheduler:
        raise HTTPException(503, "Task scheduler is not ready")

    try:
        memory_summary = await Modules.task_scheduler.get_task_memory_summary(task_id, include_key_facts)
        return {"success": True, "task_id": task_id, "memory_summary": memory_summary}
    except Exception as exc:
        logger.error("Failed to get task memory: %s", exc)
        raise HTTPException(500, f"Failed to get task memory: {exc}")


@app.get("/memory/global")
async def get_global_memory() -> Dict[str, Any]:
    if not Modules.task_scheduler:
        raise HTTPException(503, "Task scheduler is not ready")

    try:
        global_summary = await Modules.task_scheduler.get_global_memory_summary()
        failed_attempts = await Modules.task_scheduler.get_failed_attempts_summary()
        return {"success": True, "global_summary": global_summary, "failed_attempts": failed_attempts}
    except Exception as exc:
        logger.error("Failed to get global memory: %s", exc)
        raise HTTPException(500, f"Failed to get global memory: {exc}")


@app.post("/tasks/{task_id}/steps")
async def add_task_step(task_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if not Modules.task_scheduler:
        raise HTTPException(503, "Task scheduler is not ready")

    try:
        step = TaskStep(
            step_id=payload.get("step_id", str(uuid.uuid4())),
            task_id=task_id,
            purpose=payload.get("purpose", "execute step"),
            content=payload.get("content", ""),
            output=payload.get("output", ""),
            analysis=payload.get("analysis"),
            success=payload.get("success", True),
            error=payload.get("error"),
        )
        await Modules.task_scheduler.add_task_step(task_id, step)
        return {"success": True, "message": "Task step added", "step_id": step.step_id}
    except Exception as exc:
        logger.error("Failed to add task step: %s", exc)
        raise HTTPException(500, f"Failed to add task step: {exc}")


@app.delete("/tasks/{task_id}/memory")
async def clear_task_memory(task_id: str) -> Dict[str, Any]:
    if not Modules.task_scheduler:
        raise HTTPException(503, "Task scheduler is not ready")

    try:
        success = await Modules.task_scheduler.clear_task_memory(task_id)
        if not success:
            raise HTTPException(404, f"Task {task_id} not found")
        return {"success": True, "message": f"Task memory cleared: {task_id}"}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to clear task memory: %s", exc)
        raise HTTPException(500, f"Failed to clear task memory: {exc}")


@app.delete("/memory/global")
async def clear_global_memory() -> Dict[str, Any]:
    if not Modules.task_scheduler:
        raise HTTPException(503, "Task scheduler is not ready")

    try:
        await Modules.task_scheduler.clear_all_memory()
        return {"success": True, "message": "Global memory cleared"}
    except Exception as exc:
        logger.error("Failed to clear global memory: %s", exc)
        raise HTTPException(500, f"Failed to clear global memory: {exc}")


@app.get("/sessions")
async def get_all_sessions() -> Dict[str, Any]:
    if not Modules.task_scheduler:
        raise HTTPException(503, "Task scheduler is not ready")

    try:
        sessions = await Modules.task_scheduler.get_all_sessions()
        return {"success": True, "sessions": sessions, "total_sessions": len(sessions)}
    except Exception as exc:
        logger.error("Failed to get sessions: %s", exc)
        raise HTTPException(500, f"Failed to get sessions: {exc}")


@app.get("/sessions/{session_id}/memory")
async def get_session_memory_summary(session_id: str) -> Dict[str, Any]:
    if not Modules.task_scheduler:
        raise HTTPException(503, "Task scheduler is not ready")

    try:
        summary = await Modules.task_scheduler.get_session_memory_summary(session_id)
        if "error" in summary:
            raise HTTPException(404, summary["error"])
        return {"success": True, "session_id": session_id, "memory_summary": summary}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to get session memory summary: %s", exc)
        raise HTTPException(500, f"Failed to get session memory summary: {exc}")


@app.get("/sessions/{session_id}/compressed_memories")
async def get_session_compressed_memories(session_id: str) -> Dict[str, Any]:
    if not Modules.task_scheduler:
        raise HTTPException(503, "Task scheduler is not ready")

    try:
        memories = await Modules.task_scheduler.get_session_compressed_memories(session_id)
        return {"success": True, "session_id": session_id, "compressed_memories": memories, "count": len(memories)}
    except Exception as exc:
        logger.error("Failed to get compressed memories: %s", exc)
        raise HTTPException(500, f"Failed to get compressed memories: {exc}")


@app.get("/sessions/{session_id}/key_facts")
async def get_session_key_facts(session_id: str) -> Dict[str, Any]:
    if not Modules.task_scheduler:
        raise HTTPException(503, "Task scheduler is not ready")

    try:
        key_facts = await Modules.task_scheduler.get_session_key_facts(session_id)
        return {"success": True, "session_id": session_id, "key_facts": key_facts, "count": len(key_facts)}
    except Exception as exc:
        logger.error("Failed to get key facts: %s", exc)
        raise HTTPException(500, f"Failed to get key facts: {exc}")


@app.get("/sessions/{session_id}/failed_attempts")
async def get_session_failed_attempts(session_id: str) -> Dict[str, Any]:
    if not Modules.task_scheduler:
        raise HTTPException(503, "Task scheduler is not ready")

    try:
        failed_attempts = await Modules.task_scheduler.get_session_failed_attempts(session_id)
        return {
            "success": True,
            "session_id": session_id,
            "failed_attempts": failed_attempts,
            "count": len(failed_attempts),
        }
    except Exception as exc:
        logger.error("Failed to get failed attempts: %s", exc)
        raise HTTPException(500, f"Failed to get failed attempts: {exc}")


@app.get("/sessions/{session_id}/tasks")
async def get_session_tasks(session_id: str) -> Dict[str, Any]:
    if not Modules.task_scheduler:
        raise HTTPException(503, "Task scheduler is not ready")

    try:
        tasks = await Modules.task_scheduler.get_session_tasks(session_id)
        return {"success": True, "session_id": session_id, "tasks": tasks, "count": len(tasks)}
    except Exception as exc:
        logger.error("Failed to get session tasks: %s", exc)
        raise HTTPException(500, f"Failed to get session tasks: {exc}")


@app.delete("/sessions/{session_id}/memory")
async def clear_session_memory(session_id: str) -> Dict[str, Any]:
    if not Modules.task_scheduler:
        raise HTTPException(503, "Task scheduler is not ready")

    try:
        success = await Modules.task_scheduler.clear_session_memory(session_id)
        if not success:
            raise HTTPException(404, f"Session {session_id} not found")
        return {"success": True, "message": f"Session memory cleared: {session_id}"}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to clear session memory: %s", exc)
        raise HTTPException(500, f"Failed to clear session memory: {exc}")


if __name__ == "__main__":
    import uvicorn

    from system.config import get_server_port

    uvicorn.run(app, host="127.0.0.1", port=get_server_port("agent_server"))
