#!/usr/bin/env python3
"""
NagaAgent API服务器
提供RESTful API接口访问NagaAgent功能
"""

import asyncio
import json
import sys
import traceback
import os
import logging
import time
import threading
import uuid
from contextlib import asynccontextmanager
from typing import Dict, List, Optional, AsyncGenerator, Any, Callable

from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import shutil
from pathlib import Path
from system.coding_intent import contains_direct_coding_signal, has_recent_coding_context, is_coding_followup
from core.supervisor.watchdog_daemon import WatchdogDaemon
from core.event_bus import EventStore
from agents.router_engine import RouterRequest, TaskRouterEngine
from agents.router_arbiter_guard import RouterArbiterGuard
from agents.contract_runtime import (
    trim_contract_text as trim_brain_contract_text,
)
from agents.pipeline import run_multi_agent_pipeline
from agents.shell_agent import ShellAgent
from agents.runtime.agent_session import AgentSessionStore
from agents.runtime.mailbox import AgentMailbox
from agents.runtime.task_board import TaskBoardEngine
from agents.llm_gateway import (
    GatewayRouteRequest,
    LLMGateway,
    PromptEnvelopeInput,
)

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from .message_manager import message_manager  # noqa: E402 - keep script-mode compatibility path setup

from .llm_service import get_llm_service, llm_app  # noqa: E402 - mounted below
from .native_tools import get_native_tool_executor  # noqa: E402
from . import naga_auth  # noqa: E402 - keep script-mode compatibility path setup

# ── Backward-compat module delegation for extracted routes ─────
import apiserver.routes_ops as _routes_ops  # noqa: E402
import apiserver.routes_chat as _routes_chat  # noqa: E402
import apiserver.routes_brainstem as _routes_brainstem  # noqa: E402
_CHAT_LLM_GATEWAY = getattr(_routes_chat, "_CHAT_LLM_GATEWAY", None)

def __getattr__(name: str):  # noqa: N807
    """Delegate attribute lookup to extracted modules for backward compatibility."""
    for _mod in (_routes_ops, _routes_chat, _routes_brainstem):
        try:
            return getattr(_mod, name)
        except AttributeError:
            continue
    raise AttributeError(f"module 'apiserver.api_server' has no attribute {name!r}")


# 记录哪些会话曾发送过图片，后续消息继续走 VLM 直到新会话
_vlm_sessions: set = set()

# Multi-agent runtime persistence handles (shared across requests).
_PIPELINE_RUNTIME_LOCK = threading.Lock()
_PIPELINE_SESSION_STORE: Optional[AgentSessionStore] = None
_PIPELINE_MAILBOX: Optional[AgentMailbox] = None
_PIPELINE_TASK_BOARD: Optional[TaskBoardEngine] = None


def _get_pipeline_runtime_handles() -> tuple[AgentSessionStore, AgentMailbox, TaskBoardEngine]:
    global _PIPELINE_SESSION_STORE, _PIPELINE_MAILBOX, _PIPELINE_TASK_BOARD
    if _PIPELINE_SESSION_STORE is not None and _PIPELINE_MAILBOX is not None and _PIPELINE_TASK_BOARD is not None:
        return _PIPELINE_SESSION_STORE, _PIPELINE_MAILBOX, _PIPELINE_TASK_BOARD

    with _PIPELINE_RUNTIME_LOCK:
        if _PIPELINE_SESSION_STORE is None:
            runtime_dir = Path("scratch/runtime")
            runtime_dir.mkdir(parents=True, exist_ok=True)
            _PIPELINE_SESSION_STORE = AgentSessionStore(db_path=runtime_dir / "agent_sessions.db")
            _PIPELINE_MAILBOX = AgentMailbox(db_path=runtime_dir / "agent_mailbox.db")
            _PIPELINE_TASK_BOARD = TaskBoardEngine(
                boards_dir=Path("memory/working/boards"),
                db_path=runtime_dir / "task_boards.db",
            )
    return _PIPELINE_SESSION_STORE, _PIPELINE_MAILBOX, _PIPELINE_TASK_BOARD

# 导入配置系统
try:
    from system.config import (
        get_config,
        get_embla_system_config,
        save_embla_system_config,
        build_system_prompt,
    )  # 使用新的配置系统
    from system.config_manager import get_config_snapshot, update_config  # 导入配置管理
except ImportError:
    import sys
    import os

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from system.config import get_config, get_embla_system_config, save_embla_system_config  # 使用新的配置系统
    from system.config import build_system_prompt  # 导入提示词仓库
    from system.config_manager import get_config_snapshot, update_config  # 导入配置管理
from apiserver.response_util import extract_message  # noqa: E402 - imported after fallback config setup

# 在导入其他模块后设置HTTP库日志级别
logging.getLogger("httpcore.http11").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore.connection").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# 对话核心功能已集成到apiserver


# 统一后台意图分析触发函数 - 已整合到message_manager
def _trigger_background_analysis(session_id: str):
    """统一触发后台意图分析 - 委托给message_manager"""
    message_manager.trigger_background_analysis(session_id)


# 统一保存对话与日志函数 - 已整合到message_manager
def _save_conversation_and_logs(session_id: str, user_message: str, assistant_response: str):
    """统一保存对话历史与日志 - 委托给message_manager"""
    message_manager.save_conversation_and_logs(session_id, user_message, assistant_response)


def _format_memory_quintuple_line(item: Any) -> str:
    if isinstance(item, (list, tuple)) and len(item) >= 5:
        return f"- {item[0]}({item[1]}) —[{item[2]}]→ {item[3]}({item[4]})"
    if isinstance(item, dict):
        return (
            f"- {item.get('subject', '')}({item.get('subject_type', '')}) "
            f"—[{item.get('predicate', '')}]→ {item.get('object', '')}({item.get('object_type', '')})"
        )
    return ""


async def _recall_memory_lines(question: str, *, limit: int = 5) -> List[str]:
    """统一记忆召回入口：优先远程客户端，回退本地 GRAG。"""
    lines: List[str] = []

    # 1) 远程入口（若未来重新启用）
    try:
        from summer_memory.memory_client import get_remote_memory_client

        remote_mem = get_remote_memory_client()
        if remote_mem is not None:
            mem_result = await remote_mem.query_memory(question=question, limit=limit)
            quints = mem_result.get("quintuples") if isinstance(mem_result, dict) else None
            if isinstance(quints, list):
                for item in quints:
                    line = _format_memory_quintuple_line(item)
                    if line:
                        lines.append(line)
            if lines:
                return lines
            answer = str(mem_result.get("answer") or "").strip() if isinstance(mem_result, dict) else ""
            if answer:
                return [f"- {answer}"]
    except Exception as exc:
        logger.debug(f"[RAG] 远程记忆召回失败（回退本地）: {exc}")

    # 2) 本地 GRAG 回退（当前主路径）
    try:
        from summer_memory.memory_manager import memory_manager

        if memory_manager and memory_manager.enabled:
            quintuples = await memory_manager.get_relevant_memories(question, limit=limit)
            for item in quintuples:
                line = _format_memory_quintuple_line(item)
                if line:
                    lines.append(line)
    except Exception as exc:
        logger.debug(f"[RAG] 本地记忆召回失败: {exc}")
    return lines


# Brainstem bootstrap bindings
_bootstrap_global_mutex_lease_state = _routes_brainstem._bootstrap_global_mutex_lease_state
_bootstrap_budget_guard_state = _routes_brainstem._bootstrap_budget_guard_state
_bootstrap_immutable_dna_preflight = _routes_brainstem._bootstrap_immutable_dna_preflight
_bootstrap_immutable_dna_monitor_startup = _routes_brainstem._bootstrap_immutable_dna_monitor_startup
_bootstrap_brainstem_control_plane_startup = _routes_brainstem._bootstrap_brainstem_control_plane_startup
_bootstrap_immutable_dna_monitor_shutdown = _routes_brainstem._bootstrap_immutable_dna_monitor_shutdown
_bootstrap_brainstem_control_plane_shutdown = _routes_brainstem._bootstrap_brainstem_control_plane_shutdown

# Chat-route bindings
_resolve_chat_stream_route = _routes_chat._resolve_chat_stream_route
_apply_chat_route_quality_guard = _routes_chat._apply_chat_route_quality_guard
_apply_path_b_clarify_budget = _routes_chat._apply_path_b_clarify_budget
_apply_chat_route_router_arbiter_guard = _routes_chat._apply_chat_route_router_arbiter_guard
_apply_outer_core_session_bridge = _routes_chat._apply_outer_core_session_bridge
_get_chat_route_quality_guard_summary = _routes_chat._get_chat_route_quality_guard_summary
_read_chat_route_event_rows = _routes_chat._read_chat_route_event_rows
_collect_chat_route_bridge_events = _routes_chat._collect_chat_route_bridge_events
_build_chat_route_bridge_payload = _routes_chat._build_chat_route_bridge_payload
_CHAT_ROUTE_STATE_KEY = _routes_chat._CHAT_ROUTE_STATE_KEY
_emit_chat_route_prompt_event = _routes_chat._emit_chat_route_prompt_event
_emit_chat_route_guard_event = _routes_chat._emit_chat_route_guard_event
_emit_chat_route_arbiter_event = _routes_chat._emit_chat_route_arbiter_event
_sanitize_route_quality_reason_codes = _routes_chat._sanitize_route_quality_reason_codes
_sanitize_router_arbiter_reason_codes = _routes_chat._sanitize_router_arbiter_reason_codes
_build_chat_route_prompt_hints = _routes_chat._build_chat_route_prompt_hints
_build_path_model_override = _routes_chat._build_path_model_override
_emit_agentic_loop_completion_event = _routes_chat._emit_agentic_loop_completion_event
_extract_agentic_execution_receipt_text = _routes_chat._extract_agentic_execution_receipt_text
_format_sse_payload_chunk_json = _routes_chat._format_sse_payload_chunk_json
_CHAT_ROUTE_PATH_B_CLARIFY_LIMIT = _routes_chat._CHAT_ROUTE_PATH_B_CLARIFY_LIMIT
_CHAT_ROUTE_ARBITER_GUARD = _routes_chat._CHAT_ROUTE_ARBITER_GUARD

if hasattr(_routes_chat, "_bind_chat_runtime_context"):
    _routes_chat._bind_chat_runtime_context(
        message_manager=message_manager,
        message_manager_getter=lambda: message_manager,
        config_getter=lambda: get_config(),
        route_arbiter_guard_getter=lambda: _CHAT_ROUTE_ARBITER_GUARD,
        event_store_getter=lambda: _CHAT_ROUTE_EVENT_STORE,
        event_store_factory=lambda file_path: EventStore(file_path=file_path),
        quality_guard_summary_getter=lambda force_refresh=False: (
            _get_chat_route_quality_guard_summary(force_refresh=force_refresh)
            if _get_chat_route_quality_guard_summary is not _routes_chat._get_chat_route_quality_guard_summary
            else None
        ),
        event_rows_reader=lambda limit=2000: (
            _read_chat_route_event_rows(limit=limit)
            if _read_chat_route_event_rows is not _routes_chat._read_chat_route_event_rows
            else None
        ),
    )
if hasattr(_routes_brainstem, "_bind_brainstem_runtime_context"):
    _routes_brainstem._bind_brainstem_runtime_context(
        app_getter=lambda: globals().get("app"),
        llm_service_getter=get_llm_service,
        event_store_class_getter=lambda: EventStore,
    )



STREAM_PROTOCOL_JSON_V1 = "sse_json_v1"
STREAM_PROTOCOL_LEGACY_ALIASES = {"sse_base64", "base64", "legacy", "compat", "compatibility"}
STREAM_PROTOCOL_JSON_ALIASES = {"sse_json", "sse-json", "json", "structured", STREAM_PROTOCOL_JSON_V1}
STREAM_PROTOCOL_LEGACY_DECOMMISSIONED_AT = "2026-03-01"


def _resolve_stream_protocol(raw_value: Optional[str]) -> str:
    value = str(raw_value or "").strip().lower()
    if not value or value in STREAM_PROTOCOL_JSON_ALIASES:
        return STREAM_PROTOCOL_JSON_V1
    return STREAM_PROTOCOL_JSON_V1


def _is_legacy_stream_protocol_requested(raw_value: Optional[str]) -> bool:
    value = str(raw_value or "").strip().lower()
    return value in STREAM_PROTOCOL_LEGACY_ALIASES


def _is_supported_stream_protocol_requested(raw_value: Optional[str]) -> bool:
    value = str(raw_value or "").strip().lower()
    return (not value) or (value in STREAM_PROTOCOL_JSON_ALIASES) or (value in STREAM_PROTOCOL_LEGACY_ALIASES)


def _build_stream_response_headers(*, protocol: str) -> Dict[str, str]:
    return {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "Content-Type": "text/event-stream",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "*",
        "X-Accel-Buffering": "no",  # 禁用nginx缓冲
        "X-Embla-Stream-Protocol": protocol,
    }


def _format_stream_payload_chunk(payload: Dict[str, Any], *, protocol: str) -> str:
    _ = protocol
    return _format_sse_payload_chunk_json(payload)


# 历史流式文本切分器已移除，流式处理统一由 chat_stream 主循环管理


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    try:
        print("[INFO] 正在初始化API服务器...")
        mutex_bootstrap = _bootstrap_global_mutex_lease_state()
        app.state.global_mutex_bootstrap = mutex_bootstrap
        if not bool(mutex_bootstrap.get("passed", False)):
            print("[WARN] Global mutex 启动初始化未通过，锁状态可能显示 missing/unknown")
        budget_guard_bootstrap = _bootstrap_budget_guard_state()
        app.state.budget_guard_bootstrap = budget_guard_bootstrap
        if not bool(budget_guard_bootstrap.get("passed", False)):
            print("[WARN] Budget guard 启动初始化未通过，预算状态可能显示 missing/unknown")
        immutable_dna_preflight = _bootstrap_immutable_dna_preflight()
        app.state.immutable_dna_preflight = immutable_dna_preflight
        immutable_dna_required = bool(immutable_dna_preflight.get("required", True))
        immutable_dna_enabled = bool(immutable_dna_preflight.get("enabled", True))
        immutable_dna_passed = bool(immutable_dna_preflight.get("passed", False))
        if immutable_dna_required and immutable_dna_enabled and not immutable_dna_passed:
            raise RuntimeError(
                "Immutable DNA startup preflight failed: "
                f"{str(immutable_dna_preflight.get('reason') or 'unknown')}"
            )
        immutable_dna_monitor_bootstrap = _bootstrap_immutable_dna_monitor_startup()
        app.state.immutable_dna_monitor_bootstrap = immutable_dna_monitor_bootstrap
        if bool(immutable_dna_monitor_bootstrap.get("enabled")) and not bool(immutable_dna_monitor_bootstrap.get("passed", True)):
            print("[WARN] Immutable DNA monitor 启动未通过，篡改告警可能不可用")
        # 对话核心功能已集成到apiserver
        brainstem_bootstrap = _bootstrap_brainstem_control_plane_startup()
        app.state.brainstem_bootstrap = brainstem_bootstrap
        if bool(brainstem_bootstrap.get("enabled")) and not bool(brainstem_bootstrap.get("passed", True)):
            print("[WARN] Brainstem 控制面自动托管未通过，运行态势可能显示 unknown/missing")
        print("[SUCCESS] API服务器初始化完成")
        yield
    except Exception as e:
        print(f"[ERROR] API服务器初始化失败: {e}")
        traceback.print_exc()
        sys.exit(1)
    finally:
        print("[INFO] 正在清理资源...")
        # MCP服务现在由mcpserver独立管理，无需清理
        app.state.immutable_dna_monitor_shutdown = _bootstrap_immutable_dna_monitor_shutdown()
        app.state.brainstem_shutdown = _bootstrap_brainstem_control_plane_shutdown()


# 创建FastAPI应用
app = FastAPI(title="NagaAgent API", description="智能对话助手API服务", version="5.0.0", lifespan=lifespan)
if hasattr(_routes_ops, "_bind_ops_app_context"):
    _routes_ops._bind_ops_app_context(app)
if hasattr(_routes_brainstem, "_bind_brainstem_runtime_context"):
    _routes_brainstem._bind_brainstem_runtime_context(app=app)

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境建议限制具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_DEFAULT_VERSION = "v1"
API_CONTRACT_VERSION = "2026-02-24"
API_COMPATIBILITY_WINDOW_DAYS = 180
API_SUPPORTED_VERSIONS = [API_DEFAULT_VERSION]
_UNVERSIONED_ROUTE_DEPRECATIONS: Dict[str, Dict[str, str]] = {
    "/health": {
        "sunset": "2026-08-24",
        "replacement": "/v1/health",
    },
    "/system/info": {
        "sunset": "2026-08-24",
        "replacement": "/v1/system/info",
    },
    "/chat": {
        "sunset": "2026-08-24",
        "replacement": "/v1/chat",
    },
    "/chat/stream": {
        "sunset": "2026-08-24",
        "replacement": "/v1/chat/stream",
    },
}


def _resolve_api_deprecation_policy(path: str) -> Optional[Dict[str, str]]:
    return _UNVERSIONED_ROUTE_DEPRECATIONS.get(str(path or ""))


def _build_api_contract_snapshot() -> Dict[str, Any]:
    return {
        "api_version": API_DEFAULT_VERSION,
        "contract_version": API_CONTRACT_VERSION,
        "supported_versions": list(API_SUPPORTED_VERSIONS),
        "compatibility_window_days": API_COMPATIBILITY_WINDOW_DAYS,
        "deprecations": {
            route: {
                "sunset": meta["sunset"],
                "replacement": meta["replacement"],
            }
            for route, meta in _UNVERSIONED_ROUTE_DEPRECATIONS.items()
        },
    }


@app.middleware("http")
async def sync_auth_token(request: Request, call_next):
    """每次请求自动同步前端 token 到后端认证状态，避免 token 刷新后后端仍持有旧 token"""
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        if token and token != naga_auth.get_access_token():
            naga_auth.restore_token(token)
    response = await call_next(request)
    return response


@app.middleware("http")
async def inject_api_contract_headers(request: Request, call_next):
    response = await call_next(request)
    snapshot = _build_api_contract_snapshot()
    response.headers.setdefault("X-NagaAgent-Api-Version", str(snapshot["api_version"]))
    response.headers.setdefault("X-NagaAgent-Contract-Version", str(snapshot["contract_version"]))

    deprecation = _resolve_api_deprecation_policy(request.url.path)
    if isinstance(deprecation, dict):
        response.headers["Deprecation"] = "true"
        response.headers["Sunset"] = str(deprecation.get("sunset") or "")
        replacement = str(deprecation.get("replacement") or "").strip()
        if replacement:
            response.headers["Link"] = f"<{replacement}>; rel=\"successor-version\""
    return response


# 挂载静态文件
# ============ 内部服务代理 ============


# [已禁用] MCP Server 已从 main.py 启动流程中移除，此代理函数不再有效，调用必定 503
# async def _call_mcpserver(
#     method: str,
#     path: str,
#     params: Optional[Dict[str, Any]] = None,
#     timeout_seconds: float = 10.0,
# ) -> Any:
#     """调用 MCP Server 内部接口"""
#     import httpx
#     from system.config import get_server_port
#
#     port = get_server_port("mcp_server")
#     url = f"http://127.0.0.1:{port}{path}"
#     try:
#         async with httpx.AsyncClient(timeout=timeout_seconds, trust_env=False) as client:
#             resp = await client.request(method, url, params=params)
#     except Exception as e:
#         raise HTTPException(status_code=503, detail=f"MCP Server 不可达: {e}")
#     if resp.status_code >= 400:
#         detail = resp.text
#         try:
#             detail = resp.json()
#         except Exception:
#             pass
#         raise HTTPException(status_code=resp.status_code, detail=detail)
#     try:
#         return resp.json()
#     except Exception:
#         return resp.text


# ============ Skill Storage ============

SKILLS_TEMPLATE_DIR = Path(__file__).resolve().parent / "skills_templates"
LOCAL_SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"
LOCAL_SKILLS_DIR.mkdir(parents=True, exist_ok=True)
MCPORTER_DIR = Path.home() / ".mcporter"
MCPORTER_CONFIG_PATH = MCPORTER_DIR / "config.json"


def _is_path_within_root(path: Path, root: Path) -> bool:
    try:
        root_s = os.path.normcase(os.path.abspath(str(root)))
        path_s = os.path.normcase(os.path.abspath(str(path)))
        return os.path.commonpath([root_s, path_s]) == root_s
    except Exception:
        return False


def _resolve_child_path_within_root(root: Path, child: str, *, field_label: str) -> Path:
    root_resolved = root.resolve(strict=False)
    candidate = (root_resolved / child).resolve(strict=False)
    if not _is_path_within_root(candidate, root_resolved):
        raise HTTPException(status_code=400, detail=f"{field_label} 非法，路径越界")
    return candidate


def _normalize_skill_name(skill_name: str) -> str:
    normalized = str(skill_name or "").strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="技能名称不能为空")
    if len(normalized) > 128:
        raise HTTPException(status_code=400, detail="技能名称过长")
    if not all(ch.isalnum() or ch in {"_", "-"} for ch in normalized):
        raise HTTPException(status_code=400, detail="技能名称仅允许字母、数字、下划线、中划线")
    return normalized


def _normalize_uploaded_filename(filename: Optional[str]) -> str:
    raw = str(filename or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="文件名不能为空")

    # 浏览器可能携带 fakepath，统一只保留基名，避免目录逃逸。
    normalized = raw.replace("\\", "/")
    safe_name = Path(normalized).name.strip()
    if not safe_name or safe_name in {".", ".."}:
        raise HTTPException(status_code=400, detail="文件名不合法")
    if "\x00" in safe_name:
        raise HTTPException(status_code=400, detail="文件名包含非法字符")
    if len(safe_name) > 255:
        raise HTTPException(status_code=400, detail="文件名过长")
    return safe_name


def _write_skill_file(skill_name: str, content: str) -> Path:
    safe_skill_name = _normalize_skill_name(skill_name)
    skill_dir = _resolve_child_path_within_root(LOCAL_SKILLS_DIR, safe_skill_name, field_label="技能名称")
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_path = skill_dir / "SKILL.md"
    skill_path.write_text(content, encoding="utf-8")
    return skill_path

class ChatRequest(BaseModel):
    message: str
    stream: bool = False
    session_id: Optional[str] = None
    skip_intent_analysis: bool = False  # 新增：跳过意图分析
    skill: Optional[str] = None  # 用户主动选择的技能名称，注入完整指令到系统提示词
    images: Optional[List[str]] = None  # 截屏图片 base64 数据列表（data:image/png;base64,...）
    temporary: bool = False  # 临时会话标记，临时会话不持久化到磁盘
    stream_protocol: Optional[str] = None  # 仅支持 sse_json_v1（legacy 已下线）


class ChatResponse(BaseModel):
    response: str
    reasoning_content: Optional[str] = None  # COT 思考过程内容
    session_id: Optional[str] = None
    status: str = "success"


class SystemInfoResponse(BaseModel):
    version: str
    status: str
    available_services: List[str]
    api_key_configured: bool


class FileUploadResponse(BaseModel):
    filename: str
    file_path: str
    file_size: int
    file_type: str
    upload_time: str
    status: str = "success"
    message: str = "文件上传成功"


class DocumentProcessRequest(BaseModel):
    file_path: str
    action: str = "read"  # read, analyze, summarize
    session_id: Optional[str] = None


# ============ Local-only auth compatibility endpoints ============

AUTH_DISABLED_DETAIL = "Remote authentication is disabled in local-only mode"


@app.post("/auth/login")
async def auth_login(body: dict):
    raise HTTPException(status_code=410, detail=AUTH_DISABLED_DETAIL)


@app.get("/auth/me")
async def auth_me(request: Request):
    return {"user": None, "memory_url": None, "local_mode": True}


@app.post("/auth/logout")
async def auth_logout():
    naga_auth.logout()
    return {"success": True, "local_mode": True}


@app.post("/auth/register")
async def auth_register(body: dict):
    raise HTTPException(status_code=410, detail=AUTH_DISABLED_DETAIL)


@app.get("/auth/captcha")
async def auth_captcha():
    raise HTTPException(status_code=410, detail=AUTH_DISABLED_DETAIL)


@app.post("/auth/send-verification")
async def auth_send_verification(body: dict):
    raise HTTPException(status_code=410, detail=AUTH_DISABLED_DETAIL)


@app.post("/auth/refresh")
async def auth_refresh(request: Request):
    raise HTTPException(status_code=410, detail=AUTH_DISABLED_DETAIL)


# API路由
@app.get("/", response_model=Dict[str, str])
async def root():
    """API根路径"""
    system_version = str(getattr(get_config().system, "version", "5.0.0"))
    return {
        "name": "NagaAgent API",
        "version": system_version,
        "api_version": API_DEFAULT_VERSION,
        "status": "running",
        "docs": "/docs",
    }


@app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "healthy", "agent_ready": True, "timestamp": str(asyncio.get_event_loop().time())}


@app.get("/v1/health")
async def health_check_v1():
    return await health_check()


@app.get("/system/api-contract")
async def get_api_contract():
    """返回当前 API 契约版本、兼容窗口与弃用策略。"""
    return {"status": "success", **_build_api_contract_snapshot()}


@app.get("/v1/system/api-contract")
async def get_api_contract_v1():
    return await get_api_contract()


# ============ Utility APIs ============

@app.get("/system/info", response_model=SystemInfoResponse)
async def get_system_info():
    """获取系统信息"""
    system_version = str(getattr(get_config().system, "version", "5.0.0"))

    return SystemInfoResponse(
        version=system_version,
        status="running",
        available_services=[],  # MCP服务现在由mcpserver独立管理
        api_key_configured=bool(get_config().api.api_key and get_config().api.api_key != "sk-placeholder-key-not-set"),
    )


@app.get("/v1/system/info", response_model=SystemInfoResponse)
async def get_system_info_v1():
    return await get_system_info()


@app.get("/system/config")
async def get_system_config():
    """获取完整系统配置"""
    try:
        config_data = get_config_snapshot()
        embla_system = get_embla_system_config()
        if isinstance(config_data, dict):
            config_data["embla_system"] = _strip_embla_runtime_meta(embla_system if isinstance(embla_system, dict) else {})
        return {"status": "success", "config": config_data}
    except Exception as e:
        logger.error(f"获取系统配置失败: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"获取配置失败: {str(e)}")


@app.post("/system/config")
async def update_system_config(payload: Dict[str, Any]):
    """更新系统配置"""
    try:
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="配置补丁必须是对象")

        config_patch = dict(payload)
        embla_patch = config_patch.pop("embla_system", None)

        config_updated = False
        embla_updated = False

        if config_patch:
            config_updated = bool(update_config(config_patch))
            if not config_updated:
                raise HTTPException(status_code=500, detail="config.json 更新失败")

        if embla_patch is not None:
            if not isinstance(embla_patch, dict):
                raise HTTPException(status_code=400, detail="embla_system 必须是对象")
            current_embla = get_embla_system_config()
            merged_embla = _deep_merge_config_patch(
                _strip_embla_runtime_meta(current_embla if isinstance(current_embla, dict) else {}),
                embla_patch,
            )
            save_embla_system_config(merged_embla)
            embla_updated = True

        if not config_patch and embla_patch is None:
            raise HTTPException(status_code=400, detail="配置补丁为空")

        return {
            "status": "success",
            "message": "配置更新成功",
            "updated": {
                "config_json": config_updated,
                "embla_system_yaml": embla_updated,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新系统配置失败: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"更新配置失败: {str(e)}")


@app.get("/system/prompt")
async def get_system_prompt(include_skills: bool = False):
    """获取系统提示词（默认只返回人格提示词，不包含技能列表）"""
    try:
        prompt = build_system_prompt(include_skills=include_skills)
        return {"status": "success", "prompt": prompt}
    except Exception as e:
        logger.error(f"获取系统提示词失败: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"获取系统提示词失败: {str(e)}")


@app.post("/system/prompt")
async def update_system_prompt(payload: Dict[str, Any]):
    """更新系统提示词"""
    try:
        content = payload.get("content")
        if not content:
            raise HTTPException(status_code=400, detail="缺少content参数")
        from system.config import save_prompt, evaluate_prompt_acl

        approval_ticket = str(payload.get("approval_ticket") or "").strip()
        change_reason = str(payload.get("change_reason") or "").strip()
        acl_decision = evaluate_prompt_acl(
            prompt_name="conversation_style_prompt",
            approval_ticket=approval_ticket,
            change_reason=change_reason,
        )
        if bool(acl_decision.get("blocked")):
            raise HTTPException(
                status_code=403,
                detail={
                    "code": acl_decision.get("reason_code"),
                    "message": acl_decision.get("reason"),
                    "acl": acl_decision,
                },
            )
        save_prompt("conversation_style_prompt", content)
        return {
            "status": "success",
            "message": "提示词更新成功",
            "acl": acl_decision,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新系统提示词失败: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"更新系统提示词失败: {str(e)}")


def _normalize_prompt_template_name(name: str) -> str:
    normalized = str(name or "").strip()
    if normalized.lower().endswith(".md"):
        normalized = normalized[:-3]
    if not normalized:
        raise HTTPException(status_code=400, detail="提示词名称不能为空")
    if len(normalized) > 128:
        raise HTTPException(status_code=400, detail="提示词名称过长")
    if not all(ch.isalnum() or ch == "_" for ch in normalized):
        raise HTTPException(status_code=400, detail="提示词名称仅允许字母、数字、下划线")
    return normalized


def _deep_merge_config_patch(base: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    merged: Dict[str, Any] = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_config_patch(merged[key], value)
        else:
            merged[key] = value
    return merged


def _strip_embla_runtime_meta(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in payload.items() if k not in {"config_source", "config_loaded"}}


def _build_prompt_template_meta(path: Path) -> Dict[str, Any]:
    from datetime import datetime, timezone

    stat = path.stat()
    return {
        "name": path.stem,
        "filename": path.name,
        "size_bytes": int(stat.st_size),
        "updated_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
    }


def _list_prompt_template_metas() -> List[Dict[str, Any]]:
    from system.config import get_prompt_manager

    manager = get_prompt_manager()
    prompts_dir = Path(manager.prompts_dir)
    prompts_dir.mkdir(parents=True, exist_ok=True)
    items: List[Dict[str, Any]] = []
    for item in sorted(prompts_dir.glob("*.md"), key=lambda p: p.name.lower()):
        if not item.is_file():
            continue
        items.append(_build_prompt_template_meta(item))
    return items


@app.get("/system/prompts")
async def list_system_prompts():
    try:
        return {"status": "success", "prompts": _list_prompt_template_metas()}
    except Exception as e:
        logger.error(f"读取提示词列表失败: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"读取提示词列表失败: {str(e)}")


@app.get("/v1/system/prompts")
async def list_system_prompts_v1():
    return await list_system_prompts()


@app.get("/system/prompts/{name}")
async def get_system_prompt_template(name: str):
    try:
        from system.config import get_prompt_manager, resolve_prompt_registry_entry

        normalized = _normalize_prompt_template_name(name)
        manager = get_prompt_manager()
        resolved = resolve_prompt_registry_entry(prompt_name=normalized, prompts_dir=Path(manager.prompts_dir))
        prompt_file = Path(resolved["path"])
        if not prompt_file.exists():
            raise HTTPException(status_code=404, detail=f"提示词不存在: {normalized}")
        content = prompt_file.read_text(encoding="utf-8")
        return {
            "status": "success",
            "name": normalized,
            "content": content,
            "meta": _build_prompt_template_meta(prompt_file),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"读取提示词失败: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"读取提示词失败: {str(e)}")


@app.get("/v1/system/prompts/{name}")
async def get_system_prompt_template_v1(name: str):
    return await get_system_prompt_template(name)


@app.post("/system/prompts/{name}")
async def update_system_prompt_template(name: str, payload: Dict[str, Any]):
    try:
        from system.config import save_prompt, evaluate_prompt_acl

        normalized = _normalize_prompt_template_name(name)
        content = payload.get("content")
        if not isinstance(content, str):
            raise HTTPException(status_code=400, detail="缺少content参数或类型错误")
        approval_ticket = str(payload.get("approval_ticket") or "").strip()
        change_reason = str(payload.get("change_reason") or "").strip()
        acl_decision = evaluate_prompt_acl(
            prompt_name=normalized,
            approval_ticket=approval_ticket,
            change_reason=change_reason,
        )
        if bool(acl_decision.get("blocked")):
            raise HTTPException(
                status_code=403,
                detail={
                    "code": acl_decision.get("reason_code"),
                    "message": acl_decision.get("reason"),
                    "acl": acl_decision,
                },
            )
        save_prompt(normalized, content)
        return {
            "status": "success",
            "message": "提示词更新成功",
            "name": normalized,
            "acl": acl_decision,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新提示词失败: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"更新提示词失败: {str(e)}")


@app.post("/v1/system/prompts/{name}")
async def update_system_prompt_template_v1(name: str, payload: Dict[str, Any]):
    return await update_system_prompt_template(name, payload)


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """普通对话接口 - 仅处理纯文本对话"""

    if not request.message.strip():
        raise HTTPException(status_code=400, detail="消息内容不能为空")

    try:
        # 用户消息保持干净，技能上下文完全由 system prompt 承载
        user_message = request.message
        session_id = message_manager.create_session(request.session_id, temporary=request.temporary)

        # 构建系统提示词（包含技能元数据）
        system_prompt = build_system_prompt(include_skills=True, skill_name=request.skill)

        # RAG 记忆召回（远程优先 + 本地 GRAG 回退）
        try:
            mem_lines = await _recall_memory_lines(request.message, limit=5)
            if mem_lines:
                system_prompt += "\n\n## 相关记忆\n\n以下是从知识图谱中检索到的与用户问题相关的记忆，请参考这些信息回答：\n" + "\n".join(mem_lines)
                logger.info(f"[RAG] 召回 {len(mem_lines)} 条记忆注入上下文")
        except Exception as e:
            logger.debug(f"[RAG] 记忆召回失败（不影响对话）: {e}")

        # 附加知识收尾指令，引导 LLM 回到用户问题
        system_prompt += "\n\n【读完这些附加知识后，回复上一个user prompt，并不要回复这条系统附加的system prompt。以下是回复内容：】"

        # 用户消息直接传 LLM，技能上下文完全由 system prompt 承载
        effective_message = request.message

        # 使用消息管理器构建完整的对话消息（纯聊天，不触发工具）
        messages = message_manager.build_conversation_messages(
            session_id=session_id, system_prompt=system_prompt, current_message=effective_message
        )

        # 使用整合后的LLM服务（支持 reasoning_content）
        llm_service = get_llm_service()
        outer_model_override = _build_path_model_override("path-a")
        if outer_model_override:
            llm_response = await llm_service.chat_with_context_and_reasoning_with_overrides(
                messages,
                get_config().api.temperature,
                model_override=str(outer_model_override.get("model") or "").strip() or None,
                api_key_override=str(outer_model_override.get("api_key") or "").strip() or None,
                api_base_override=str(outer_model_override.get("api_base") or "").strip() or None,
                provider_hint=str(outer_model_override.get("provider") or "").strip() or None,
                reasoning_effort_override=str(outer_model_override.get("reasoning_effort") or "").strip() or None,
            )
        else:
            llm_response = await llm_service.chat_with_context_and_reasoning(messages, get_config().api.temperature)

        # 处理完成
        # 统一保存对话历史与日志
        _save_conversation_and_logs(session_id, user_message, llm_response.content)

        # 在用户消息保存到历史后触发后台意图分析（除非明确跳过）
        if not request.skip_intent_analysis:
            _trigger_background_analysis(session_id=session_id)

        return ChatResponse(
            response=extract_message(llm_response.content) if llm_response.content else llm_response.content,
            reasoning_content=llm_response.reasoning_content,
            session_id=session_id,
            status="success",
        )
    except Exception as e:
        print(f"对话处理错误: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")


@app.post("/v1/chat", response_model=ChatResponse)
async def chat_v1(request: ChatRequest):
    return await chat(request)


@app.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    """流式对话接口 - 使用 agentic tool loop 实现多轮工具调用"""

    if not request.message.strip():
        raise HTTPException(status_code=400, detail="消息内容不能为空")

    # 用户消息保持干净，技能上下文完全由 system prompt 承载
    user_message = request.message
    if _is_legacy_stream_protocol_requested(request.stream_protocol):
        raise HTTPException(
            status_code=410,
            detail={
                "error": "legacy_stream_protocol_decommissioned",
                "message": "Legacy stream protocol is decommissioned. Use stream_protocol=sse_json_v1.",
                "replacement": STREAM_PROTOCOL_JSON_V1,
                "decommissioned_at": STREAM_PROTOCOL_LEGACY_DECOMMISSIONED_AT,
            },
        )
    if not _is_supported_stream_protocol_requested(request.stream_protocol):
        raise HTTPException(
            status_code=400,
            detail={
                "error": "unsupported_stream_protocol",
                "message": "Unsupported stream_protocol. Use stream_protocol=sse_json_v1.",
                "supported": [STREAM_PROTOCOL_JSON_V1],
            },
        )
    stream_protocol = _resolve_stream_protocol(request.stream_protocol)

    async def generate_response() -> AsyncGenerator[str, None]:
        complete_response_parts: List[str] = []
        try:
            # 获取或创建会话ID
            session_id = message_manager.create_session(request.session_id, temporary=request.temporary)

            # 发送会话ID信息
            yield _format_stream_payload_chunk(
                {"type": "session_meta", "session_id": session_id},
                protocol=stream_protocol,
            )

            route_meta = _resolve_chat_stream_route(request.message, session_id=session_id)
            route_meta = _apply_chat_route_quality_guard(route_meta)
            route_meta = _apply_path_b_clarify_budget(route_meta, session_id=session_id)
            route_meta = _apply_chat_route_router_arbiter_guard(route_meta, session_id=session_id)
            route_meta = _apply_outer_core_session_bridge(route_meta, outer_session_id=session_id)
            route_decision = route_meta.get("router_decision") if isinstance(route_meta.get("router_decision"), dict) else {}
            path = str(route_meta.get("path") or "path-c")
            execution_session_id = str(route_meta.get("execution_session_id") or session_id)
            # ====== Prompt Slice 引擎：resolve + serialize ======
            try:
                if _CHAT_LLM_GATEWAY is not None:
                    _gw_request = GatewayRouteRequest(
                        task_type=str(route_decision.get("task_type") or ""),
                        severity=str(route_meta.get("risk_level") or ""),
                        path=path,
                        prompt_profile=str(route_decision.get("prompt_profile") or ""),
                        injection_mode=str(route_decision.get("injection_mode") or ""),
                        delegation_intent=str(route_decision.get("delegation_intent") or ""),
                    )
                    _gw_prompt_input = PromptEnvelopeInput(static_header="", long_term_summary="")
                    _gw_resolve = _CHAT_LLM_GATEWAY.resolve(request=_gw_request, prompt_input=_gw_prompt_input)
                    _gw_selected = _gw_resolve.get("selected") or []
                    _gw_dropped = _gw_resolve.get("dropped") or []
                    _gw_cache = _CHAT_LLM_GATEWAY.serialize_for_cache(selected_slices=_gw_selected)
                    route_meta["_slice_selected"] = [s.slice_uid for s in _gw_selected if hasattr(s, "slice_uid")]
                    route_meta["_slice_dropped"] = [s.slice_uid for s in _gw_dropped if hasattr(s, "slice_uid")]
                    route_meta["_slice_selected_count"] = len(_gw_selected)
                    route_meta["_slice_dropped_count"] = len(_gw_dropped)
                    route_meta["_slice_prefix_hash"] = str(_gw_cache.get("prefix_hash") or "")
                    route_meta["_slice_tail_hash"] = str(_gw_cache.get("tail_hash") or "")
                    route_meta["_slice_selected_layers"] = sorted(set(
                        str(getattr(s, "layer", "")) for s in _gw_selected if getattr(s, "layer", "")
                    ))
            except Exception as _gw_exc:
                logger.debug("[prompt_slice] gateway resolve/serialize 降级: %s", _gw_exc)

            _emit_chat_route_prompt_event(route_meta, session_id=session_id)
            _emit_chat_route_guard_event(route_meta, session_id=session_id)
            _emit_chat_route_arbiter_event(route_meta, session_id=session_id)
            yield _format_stream_payload_chunk(
                {
                    "type": "route_decision",
                    "path": path,
                    "risk_level": route_meta.get("risk_level"),
                    "outer_readonly_hit": bool(route_meta.get("outer_readonly_hit")),
                    "core_escalation": bool(route_meta.get("core_escalation")),
                    "prompt_profile": route_decision.get("prompt_profile", ""),
                    "injection_mode": route_decision.get("injection_mode", ""),
                    "delegation_intent": route_decision.get("delegation_intent", ""),
                    "path_b_clarify_turns": int(route_meta.get("path_b_clarify_turns") or 0),
                    "path_b_clarify_limit": int(route_meta.get("path_b_clarify_limit") or _CHAT_ROUTE_PATH_B_CLARIFY_LIMIT),
                    "path_b_clarify_limit_override": route_meta.get("path_b_clarify_limit_override"),
                    "path_b_budget_escalated": bool(route_meta.get("path_b_budget_escalated")),
                    "path_b_budget_reason": str(route_meta.get("path_b_budget_reason") or ""),
                    "route_quality_guard_status": _ops_status_to_severity(
                        str(route_meta.get("route_quality_guard_status") or "unknown")
                    ),
                    "route_quality_guard_applied": bool(route_meta.get("route_quality_guard_applied")),
                    "route_quality_guard_action": str(route_meta.get("route_quality_guard_action") or ""),
                    "route_quality_guard_reason": str(route_meta.get("route_quality_guard_reason") or ""),
                    "route_quality_guard_reason_codes": _sanitize_route_quality_reason_codes(
                        route_meta.get("route_quality_guard_reason_codes")
                    ),
                    "route_quality_guard_path_before": str(route_meta.get("route_quality_guard_path_before") or ""),
                    "route_quality_guard_path_after": str(route_meta.get("route_quality_guard_path_after") or ""),
                    "router_arbiter_status": _ops_status_to_severity(
                        str(route_meta.get("router_arbiter_status") or "unknown")
                    ),
                    "router_arbiter_applied": bool(route_meta.get("router_arbiter_applied")),
                    "router_arbiter_action": str(route_meta.get("router_arbiter_action") or ""),
                    "router_arbiter_reason": str(route_meta.get("router_arbiter_reason") or ""),
                    "router_arbiter_reason_codes": _sanitize_router_arbiter_reason_codes(
                        route_meta.get("router_arbiter_reason_codes")
                    ),
                    "router_arbiter_path_before": str(route_meta.get("router_arbiter_path_before") or ""),
                    "router_arbiter_path_after": str(route_meta.get("router_arbiter_path_after") or ""),
                    "router_arbiter_delegate_turns": int(route_meta.get("router_arbiter_delegate_turns") or 0),
                    "router_arbiter_max_delegate_turns": int(
                        route_meta.get("router_arbiter_max_delegate_turns") or _CHAT_ROUTE_ARBITER_GUARD.max_delegate_turns
                    ),
                    "router_arbiter_conflict_ticket": str(route_meta.get("router_arbiter_conflict_ticket") or ""),
                    "router_arbiter_freeze": bool(route_meta.get("router_arbiter_freeze")),
                    "router_arbiter_hitl": bool(route_meta.get("router_arbiter_hitl")),
                    "router_arbiter_escalated": bool(route_meta.get("router_arbiter_escalated")),
                    "outer_session_id": str(route_meta.get("outer_session_id") or ""),
                    "core_session_id": str(route_meta.get("core_session_id") or ""),
                    "execution_session_id": execution_session_id,
                    "core_session_created": bool(route_meta.get("core_session_created")),
                    "selected_slice_count": int(route_meta.get("_slice_selected_count") or 0),
                    "dropped_slice_count": int(route_meta.get("_slice_dropped_count") or 0),
                    "prefix_hash": str(route_meta.get("_slice_prefix_hash") or ""),
                    "tail_hash": str(route_meta.get("_slice_tail_hash") or ""),
                },
                protocol=stream_protocol,
            )
            logger.info(
                "[API Server] chat route decided outer_session=%s execution_session=%s path=%s intent=%s profile=%s guard=%s action=%s arbiter=%s arbiter_action=%s",
                session_id,
                execution_session_id,
                path,
                route_decision.get("delegation_intent", ""),
                route_decision.get("prompt_profile", ""),
                route_meta.get("route_quality_guard_status", "unknown"),
                route_meta.get("route_quality_guard_action", ""),
                route_meta.get("router_arbiter_status", "unknown"),
                route_meta.get("router_arbiter_action", ""),
            )

            # pipeline handles system prompt construction internally

            # ====== RAG 记忆召回 ======

            # 用户消息
            effective_message = request.message

            current_round_text = ""
            receipt_fallback_text = ""
            session_store, agent_mailbox, task_board_engine = _get_pipeline_runtime_handles()
            child_loop_llm_service = get_llm_service()
            child_loop_model_override = _build_path_model_override("path-c")
            native_tool_executor = get_native_tool_executor()

            async def _pipeline_child_llm_call(
                messages: List[Dict[str, Any]],
                tools: List[Dict[str, Any]],
                model_name: str,
            ) -> Dict[str, Any]:
                del model_name  # model tier is already encoded in route-level override
                content_parts: List[str] = []
                collected_tool_calls: List[Dict[str, Any]] = []
                stream_source = child_loop_llm_service.stream_chat_with_context(
                    messages,
                    get_config().api.temperature,
                    model_override=child_loop_model_override,
                    tools=tools,
                    tool_choice="auto",
                )
                async for chunk in stream_source:
                    if not isinstance(chunk, str) or not chunk.startswith("data: "):
                        continue
                    data_str = chunk[6:].strip()
                    if not data_str or data_str == "[DONE]":
                        continue
                    try:
                        payload = json.loads(data_str)
                    except Exception:
                        continue
                    payload_type = str(payload.get("type", ""))
                    payload_text = payload.get("text")
                    if payload_type == "content":
                        content_parts.append(str(payload_text or ""))
                    elif payload_type == "tool_calls" and isinstance(payload_text, list):
                        collected_tool_calls = [dict(item) for item in payload_text if isinstance(item, dict)]
                return {
                    "content": "".join(content_parts),
                    "tool_calls": collected_tool_calls,
                }

            async def _pipeline_child_tool_executor(
                tool_name: str,
                arguments: Dict[str, Any],
                child_session_id: str,
            ) -> Dict[str, Any]:
                call_payload = dict(arguments) if isinstance(arguments, dict) else {}
                call_payload["tool_name"] = str(tool_name or "")
                call_payload["_session_id"] = child_session_id
                call_payload["session_id"] = child_session_id
                return await native_tool_executor.execute(call_payload, session_id=child_session_id)

            # ── Unified Multi-Agent Pipeline ──
            async for event in run_multi_agent_pipeline(
                message=effective_message,
                session_id=execution_session_id,
                risk_level=str(route_meta.get("risk_level") or ""),
                route_decision=route_decision,
                forced_path=path,
                core_session_id=str(route_meta.get("core_session_id") or execution_session_id),
                child_llm_call=_pipeline_child_llm_call,
                child_tool_executor=_pipeline_child_tool_executor,
                enable_child_execution=True,
                store=session_store,
                mailbox=agent_mailbox,
                task_board_engine=task_board_engine,
            ):
                if not isinstance(event, dict):
                    continue
                chunk_type = str(event.get("type", "content"))
                chunk_text = str(event.get("text", ""))

                if chunk_type == "shell_direct":
                    # Shell decided to handle directly — run a read-only tool loop.
                    shell_prompt = str(event.get("system_prompt", ""))
                    shell_msg = str(event.get("user_message", effective_message))
                    # Inject RAG memory if available
                    try:
                        mem_lines = await _recall_memory_lines(shell_msg, limit=5)
                        if mem_lines:
                            shell_prompt += "\n\n## 相关记忆\n" + "\n".join(mem_lines)
                    except Exception:
                        pass
                    shell_prompt += "\n\n" + _build_chat_route_prompt_hints(route_meta)

                    # Build conversation messages
                    shell_messages = message_manager.build_conversation_messages(
                        session_id=session_id, system_prompt=shell_prompt, current_message=shell_msg,
                    )

                    # Handle images
                    if request.images:
                        last_msg = shell_messages[-1]
                        content_parts = [{"type": "text", "text": last_msg["content"]}]
                        for img_data in request.images:
                            content_parts.append({"type": "image_url", "image_url": {"url": img_data}})
                        shell_messages[-1] = {"role": "user", "content": content_parts}
                        _vlm_sessions.add(session_id)

                    # Model override for VLM
                    model_override = None
                    use_vlm = session_id in _vlm_sessions
                    cc = get_config().computer_control
                    if use_vlm and cc.enabled and (cc.api_key or naga_auth.is_authenticated()):
                        model_override = {"model": cc.model, "api_base": cc.model_url, "api_key": cc.api_key}

                    shell_agent = ShellAgent()
                    shell_tool_defs = shell_agent.get_tool_definitions()

                    # Stream Shell reply from LLM with tool support.
                    llm_service = get_llm_service()
                    shell_max_rounds = 4
                    shell_round = 0
                    while shell_round < shell_max_rounds:
                        pending_tool_calls: List[Dict[str, Any]] = []
                        assistant_content_parts: List[str] = []
                        stream_source = llm_service.stream_chat_with_context(
                            shell_messages,
                            get_config().api.temperature,
                            model_override=model_override,
                            tools=shell_tool_defs,
                            tool_choice="auto",
                        )
                        async for chunk in stream_source:
                            if chunk.startswith("data: "):
                                try:
                                    data_str = chunk[6:].strip()
                                    if data_str and data_str != "[DONE]":
                                        chunk_data = json.loads(data_str)
                                        ct = str(chunk_data.get("type", "content"))
                                        ct_text = chunk_data.get("text", "")
                                        if ct == "content":
                                            text_piece = str(ct_text or "")
                                            assistant_content_parts.append(text_piece)
                                            current_round_text += text_piece
                                            complete_response_parts.append(text_piece)
                                        elif ct == "tool_calls" and isinstance(ct_text, list):
                                            pending_tool_calls = [dict(item) for item in ct_text if isinstance(item, dict)]
                                        yield _format_stream_payload_chunk(chunk_data, protocol=stream_protocol)
                                        continue
                                except Exception as e:
                                    logger.error(f"[API Server] Shell stream parse error: {e}")
                            yield chunk

                        if not pending_tool_calls:
                            break

                        assistant_msg: Dict[str, Any] = {
                            "role": "assistant",
                            "content": "".join(assistant_content_parts),
                        }
                        assistant_tool_calls: List[Dict[str, Any]] = []
                        for idx, call in enumerate(pending_tool_calls):
                            call_id = str(call.get("id") or f"shell_call_{shell_round}_{idx}")
                            tool_name = str(call.get("name") or "")
                            tool_args = call.get("arguments")
                            if not isinstance(tool_args, dict):
                                tool_args = {}
                            assistant_tool_calls.append(
                                {
                                    "id": call_id,
                                    "type": "function",
                                    "function": {
                                        "name": tool_name,
                                        "arguments": json.dumps(tool_args, ensure_ascii=False),
                                    },
                                }
                            )
                        assistant_msg["tool_calls"] = assistant_tool_calls
                        shell_messages.append(assistant_msg)

                        for idx, call in enumerate(pending_tool_calls):
                            call_id = str(call.get("id") or f"shell_call_{shell_round}_{idx}")
                            tool_name = str(call.get("name") or "")
                            tool_args = call.get("arguments")
                            if not isinstance(tool_args, dict):
                                tool_args = {}
                            tool_result = shell_agent.execute_tool(
                                tool_name,
                                tool_args,
                                session_id=session_id,
                            )
                            shell_messages.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": call_id,
                                    "content": json.dumps(tool_result, ensure_ascii=False, default=str),
                                }
                            )
                            yield _format_stream_payload_chunk(
                                {
                                    "type": "tool_result",
                                    "tool_name": tool_name,
                                    "tool_call_id": call_id,
                                    "result": tool_result,
                                },
                                protocol=stream_protocol,
                            )
                        shell_round += 1

                    if shell_round >= shell_max_rounds:
                        yield _format_stream_payload_chunk(
                            {
                                "type": "warning",
                                "text": "shell_tool_loop_max_rounds_reached",
                                "max_rounds": shell_max_rounds,
                            },
                            protocol=stream_protocol,
                        )
                    continue

                if chunk_type == "content":
                    current_round_text += chunk_text
                    complete_response_parts.append(chunk_text)
                elif chunk_type == "reasoning":
                    pass
                elif chunk_type == "tool_stage":
                    _emit_agentic_loop_completion_event(
                        session_id=session_id,
                        execution_session_id=execution_session_id,
                        route_meta=route_meta,
                        chunk_data=event,
                    )
                elif chunk_type == "execution_receipt":
                    receipt_text = _extract_agentic_execution_receipt_text(event)
                    if receipt_text:
                        receipt_fallback_text = receipt_text
                elif chunk_type == "round_end":
                    current_round_text = ""

                yield _format_stream_payload_chunk(event, protocol=stream_protocol)

            # ====== 流式处理完成 ======

            # 获取完整文本用于保存
            complete_response = "".join(complete_response_parts)

            # fallback: 如果没有累积到文本，使用最后一轮的 current_round_text
            if not complete_response and current_round_text:
                complete_response = current_round_text

            # Path-C fallback: some models finish via SubmitResult_Tool without emitting plain content tokens.
            if path == "path-c" and not complete_response and receipt_fallback_text:
                complete_response = receipt_fallback_text
                yield _format_stream_payload_chunk(
                    {
                        "type": "content",
                        "text": receipt_fallback_text,
                        "source": "execution_receipt_fallback",
                    },
                    protocol=stream_protocol,
                )

            # 统一保存对话历史与日志
            _save_conversation_and_logs(session_id, user_message, complete_response)

            # Agentic loop 模式下跳过后台意图分析（工具调用已在loop中处理）
            # 仅在非 agentic 模式或明确需要时触发后台分析
            if not request.skip_intent_analysis:
                # 预留后台分析入口（当前流式主链不在此处分发额外UI动作）
                pass

            # [DONE] 信号已由 llm_service.stream_chat_with_context 发送，无需重复

        except Exception as e:
            print(f"流式对话处理错误: {e}")
            traceback.print_exc()
            yield _format_stream_payload_chunk(
                {"type": "error", "text": str(e)},
                protocol=stream_protocol,
            )

    return StreamingResponse(
        generate_response(),
        media_type="text/event-stream",
        headers=_build_stream_response_headers(protocol=stream_protocol),
    )


@app.post("/v1/chat/stream")
async def chat_stream_v1(request: ChatRequest):
    return await chat_stream(request)


@app.api_route("/tools/search", methods=["GET", "POST"])
async def proxy_search(request: Request):
    """Remote proxy disabled in local-only mode."""
    raise HTTPException(status_code=410, detail="Remote tool search proxy is disabled in local-only mode")


@app.get("/memory/stats")
async def get_memory_stats():
    """获取记忆统计信息"""

    try:
        # 优先使用远程 NagaMemory 服务
        from summer_memory.memory_client import get_remote_memory_client

        remote = get_remote_memory_client()
        if remote is not None:
            stats = await remote.get_stats()
            return {"status": "success", "memory_stats": stats}

        # 回退到本地 summer_memory
        try:
            from summer_memory.memory_manager import memory_manager

            if memory_manager and memory_manager.enabled:
                stats = memory_manager.get_memory_stats()
                return {"status": "success", "memory_stats": stats}
            else:
                return {"status": "success", "memory_stats": {"enabled": False, "message": "记忆系统未启用"}}
        except ImportError:
            return {"status": "success", "memory_stats": {"enabled": False, "message": "记忆系统模块未找到"}}
    except Exception as e:
        print(f"获取记忆统计错误: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"获取记忆统计失败: {str(e)}")


# ============ MCP Server 代理 ============
# [已禁用] MCP Server 已从 main.py 启动流程中移除，旧代理端点调用 _call_mcpserver 必定 503
# @app.get("/mcp/status")
# async def get_mcp_status_proxy():
#     """代理 MCP Server 状态查询"""
#     return await _call_mcpserver("GET", "/status")
#
# @app.get("/mcp/tasks")
# async def get_mcp_tasks_proxy(status: Optional[str] = None):
#     """代理 MCP 任务列表"""
#     params = {"status": status} if status else None
#     return await _call_mcpserver("GET", "/tasks", params=params)


def _build_mcp_runtime_snapshot(
    *,
    registry_status: Optional[Dict[str, Any]] = None,
    external_services: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """构建 MCP 运行时状态快照（供 /mcp/status 与 /mcp/tasks 复用）。"""
    from datetime import datetime

    if registry_status is None:
        try:
            from mcpserver.mcp_registry import auto_register_mcp, get_registry_status

            auto_register_mcp()
            registry_status = get_registry_status()
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.warning(f"构建 MCP registry 状态失败: {exc}")
            registry_status = {"registered_services": 0, "service_names": []}

    if external_services is None:
        cfg = _load_mcporter_config()
        external_cfg = cfg.get("mcpServers", {}) if isinstance(cfg, dict) else {}
        external_services = list(external_cfg.keys()) if isinstance(external_cfg, dict) else []

    builtin_names = [str(x) for x in (registry_status.get("service_names") or []) if str(x).strip()]
    external_names = [str(x) for x in (external_services or []) if str(x).strip() and str(x) not in builtin_names]
    service_total = len(builtin_names) + len(external_names)

    return {
        "server": "online" if service_total > 0 else "offline",
        "timestamp": datetime.now().isoformat(),
        "tasks": {
            "total": service_total,
            "active": 0,
            "completed": len(builtin_names),
            "failed": 0,
        },
        "registry": {
            "registered_services": int(registry_status.get("registered_services") or 0),
            "cached_manifests": int(registry_status.get("cached_manifests") or 0),
            "service_names": builtin_names,
            "external_service_names": external_names,
        },
        "scheduler": {
            "source": "registry_snapshot",
            "tracked_tasks": service_total,
        },
    }


def _build_mcp_task_snapshot(
    status: Optional[str] = None,
    *,
    snapshot: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if snapshot is None:
        snapshot = _build_mcp_runtime_snapshot()
    registry = snapshot.get("registry", {}) if isinstance(snapshot, dict) else {}

    tasks: List[Dict[str, Any]] = []
    for name in registry.get("service_names", []) or []:
        tasks.append(
            {
                "task_id": f"builtin:{name}",
                "service_name": str(name),
                "status": "registered",
                "source": "builtin",
            }
        )
    for name in registry.get("external_service_names", []) or []:
        tasks.append(
            {
                "task_id": f"mcporter:{name}",
                "service_name": str(name),
                "status": "configured",
                "source": "mcporter",
            }
        )

    normalized_filter = str(status or "").strip().lower()
    if normalized_filter:
        tasks = [item for item in tasks if str(item.get("status", "")).lower() == normalized_filter]

    return {"tasks": tasks, "total": len(tasks)}


# ── Ops routes (extracted to routes_ops.py) ───────────────────
from apiserver.routes_ops import router as _ops_router
app.include_router(_ops_router)

# Re-export shared utilities for backward compatibility with in-file callers
from apiserver._shared import (
    env_flag as _env_flag,
    env_float as _env_float,
    ops_utc_iso_now as _ops_utc_iso_now,
    ops_repo_root as _ops_repo_root,
    ops_unix_path as _ops_unix_path,
    ops_status_to_severity as _ops_status_to_severity,
    ops_max_status as _ops_max_status,
    ops_safe_int as _ops_safe_int,
    ops_read_json_file as _ops_read_json_file,
    ops_parse_iso_datetime as _ops_parse_iso_datetime,
)
from apiserver._shared import OPS_STATUS_RANK as _OPS_STATUS_RANK

class McpImportRequest(BaseModel):
    name: str
    config: Dict[str, Any]


@app.post("/mcp/import")
async def import_mcp_config(request: McpImportRequest):
    """将 MCP JSON 配置写入 ~/.mcporter/config.json"""
    MCPORTER_DIR.mkdir(parents=True, exist_ok=True)
    mcporter_config = _load_mcporter_config()
    servers = mcporter_config.setdefault("mcpServers", {})
    servers[request.name] = request.config
    mcporter_config["mcpServers"] = servers
    MCPORTER_CONFIG_PATH.write_text(
        json.dumps(mcporter_config, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"status": "success", "message": f"已添加 MCP 服务: {request.name}"}


class SkillImportRequest(BaseModel):
    name: str
    content: str


@app.post("/skills/import")
async def import_custom_skill(request: SkillImportRequest):
    """创建自定义技能 SKILL.md"""
    safe_skill_name = _normalize_skill_name(request.name)
    skill_content = f"""---
name: {safe_skill_name}
description: 用户自定义技能
version: 1.0.0
author: User
tags:
  - custom
enabled: true
---

{request.content}
"""
    skill_path = _write_skill_file(safe_skill_name, skill_content)
    return {"status": "success", "message": f"技能已创建: {skill_path}"}


@app.get("/memory/quintuples")
async def get_quintuples():
    """获取所有五元组 (用于知识图谱可视化)"""
    try:
        # 优先使用远程 NagaMemory 服务
        from summer_memory.memory_client import get_remote_memory_client

        remote = get_remote_memory_client()
        if remote is not None:
            result = await remote.get_quintuples(limit=500)
            quintuples_raw = result.get("quintuples") or result.get("results") or result.get("data") or []
            # 兼容 NagaMemory 返回格式：可能是 dict 列表或 tuple 列表
            quintuples = []
            for q in quintuples_raw:
                if isinstance(q, dict):
                    quintuples.append({
                        "subject": q.get("subject", ""),
                        "subject_type": q.get("subject_type", ""),
                        "predicate": q.get("predicate", q.get("relation", "")),
                        "object": q.get("object", ""),
                        "object_type": q.get("object_type", ""),
                    })
                elif isinstance(q, (list, tuple)) and len(q) >= 5:
                    quintuples.append({
                        "subject": q[0], "subject_type": q[1],
                        "predicate": q[2], "object": q[3], "object_type": q[4],
                    })
            return {"status": "success", "quintuples": quintuples, "count": len(quintuples)}

        # 回退到本地 summer_memory
        from summer_memory.quintuple_graph import get_all_quintuples

        quintuples = get_all_quintuples()  # returns set[tuple]
        return {
            "status": "success",
            "quintuples": [
                {"subject": q[0], "subject_type": q[1], "predicate": q[2], "object": q[3], "object_type": q[4]}
                for q in quintuples
            ],
            "count": len(quintuples),
        }
    except ImportError:
        return {"status": "success", "quintuples": [], "count": 0, "message": "记忆系统模块未找到"}
    except Exception as e:
        logger.error(f"获取五元组错误: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"获取五元组失败: {str(e)}")


@app.get("/memory/quintuples/search")
async def search_quintuples(keywords: str = ""):
    """按关键词搜索五元组"""
    try:
        keyword_list = [k.strip() for k in keywords.split(",") if k.strip()]
        if not keyword_list:
            raise HTTPException(status_code=400, detail="请提供搜索关键词")

        # 优先使用远程 NagaMemory 服务
        from summer_memory.memory_client import get_remote_memory_client

        remote = get_remote_memory_client()
        if remote is not None:
            result = await remote.query_by_keywords(keyword_list)
            quintuples_raw = result.get("quintuples") or result.get("results") or result.get("data") or []
            quintuples = []
            for q in quintuples_raw:
                if isinstance(q, dict):
                    quintuples.append({
                        "subject": q.get("subject", ""),
                        "subject_type": q.get("subject_type", ""),
                        "predicate": q.get("predicate", q.get("relation", "")),
                        "object": q.get("object", ""),
                        "object_type": q.get("object_type", ""),
                    })
                elif isinstance(q, (list, tuple)) and len(q) >= 5:
                    quintuples.append({
                        "subject": q[0], "subject_type": q[1],
                        "predicate": q[2], "object": q[3], "object_type": q[4],
                    })
            return {"status": "success", "quintuples": quintuples, "count": len(quintuples)}

        # 回退到本地 summer_memory
        from summer_memory.quintuple_graph import query_graph_by_keywords

        results = query_graph_by_keywords(keyword_list)
        return {
            "status": "success",
            "quintuples": [
                {"subject": q[0], "subject_type": q[1], "predicate": q[2], "object": q[3], "object_type": q[4]}
                for q in results
            ],
            "count": len(results),
        }
    except ImportError:
        return {"status": "success", "quintuples": [], "count": 0, "message": "记忆系统模块未找到"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"搜索五元组错误: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"搜索五元组失败: {str(e)}")


@app.get("/sessions")
async def get_sessions():
    """获取所有会话信息 - 委托给message_manager"""
    try:
        return message_manager.get_all_sessions_api()
    except Exception as e:
        print(f"获取会话信息错误: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/sessions/{session_id}")
async def get_session_detail(session_id: str):
    """获取指定会话的详细信息 - 委托给message_manager"""
    try:
        return message_manager.get_session_detail_api(session_id)
    except Exception as e:
        if "会话不存在" in str(e):
            raise HTTPException(status_code=404, detail=str(e))
        print(f"获取会话详情错误: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/chat/route_bridge/{session_id}")
async def get_chat_route_bridge(session_id: str, limit: int = 20):
    """获取 outer/core 会话桥接状态与最近路由事件。"""
    try:
        return _build_chat_route_bridge_payload(session_id, limit=limit)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取会话桥接状态失败: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/v1/chat/route_bridge/{session_id}")
async def get_chat_route_bridge_v1(session_id: str, limit: int = 20):
    return await get_chat_route_bridge(session_id=session_id, limit=limit)


@app.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """删除指定会话 - 委托给message_manager"""
    try:
        _vlm_sessions.discard(session_id)
        return message_manager.delete_session_api(session_id)
    except Exception as e:
        if "会话不存在" in str(e):
            raise HTTPException(status_code=404, detail=str(e))
        print(f"删除会话错误: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/sessions")
async def clear_all_sessions():
    """清空所有会话 - 委托给message_manager"""
    try:
        _vlm_sessions.clear()
        return message_manager.clear_all_sessions_api()
    except Exception as e:
        print(f"清空会话错误: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/upload/document", response_model=FileUploadResponse)
async def upload_document(file: UploadFile = File(...), description: str = Form(None)):
    """上传文档接口"""
    try:
        # 确保上传目录存在
        upload_dir = (_ops_repo_root() / "uploaded_documents").resolve(strict=False)
        upload_dir.mkdir(parents=True, exist_ok=True)

        # 统一保留安全文件名，拒绝空名与非法名。
        filename = _normalize_uploaded_filename(file.filename)
        file_path = _resolve_child_path_within_root(upload_dir, filename, field_label="文件名")

        # 保存文件
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # 获取文件信息
        stat = file_path.stat()

        return FileUploadResponse(
            filename=filename,
            file_path=str(file_path.absolute()),
            file_size=stat.st_size,
            file_type=file_path.suffix,
            upload_time=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"文件上传失败: {e}")
        raise HTTPException(status_code=500, detail=f"上传失败: {str(e)}")


@app.post("/upload/parse")
async def upload_parse(file: UploadFile = File(...)):
    """上传并解析文档内容（支持 .docx / .xlsx / .txt）"""
    import tempfile
    filename = file.filename or "unknown"
    suffix = Path(filename).suffix.lower()

    if suffix not in (".docx", ".xlsx", ".txt", ".csv", ".md"):
        raise HTTPException(status_code=400, detail=f"不支持的文件格式: {suffix}，支持 .docx / .xlsx / .txt / .csv / .md")

    # 写入临时文件
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = Path(tmp.name)

    try:
        if suffix == ".docx":
            import importlib.util
            _docx_spec = importlib.util.spec_from_file_location(
                "docx_extract", Path(__file__).parent / "skills_templates" / "office-docs" / "tools" / "docx_extract.py"
            )
            _docx_mod = importlib.util.module_from_spec(_docx_spec)
            _docx_spec.loader.exec_module(_docx_mod)
            lines = _docx_mod.extract_docx_text(tmp_path)
            content = "\n".join(lines)
        elif suffix == ".xlsx":
            import importlib.util
            import zipfile as _zf
            _xlsx_spec = importlib.util.spec_from_file_location(
                "xlsx_extract", Path(__file__).parent / "skills_templates" / "office-docs" / "tools" / "xlsx_extract.py"
            )
            _xlsx_mod = importlib.util.module_from_spec(_xlsx_spec)
            _xlsx_spec.loader.exec_module(_xlsx_mod)
            with _zf.ZipFile(tmp_path, "r") as archive:
                shared_strings = _xlsx_mod._load_shared_strings(archive)
                sheets = _xlsx_mod._load_sheet_targets(archive)
                parts = []
                for name, path in sheets:
                    rows = _xlsx_mod._parse_sheet(archive, path, shared_strings, max_rows=500)
                    parts.append(f"## Sheet: {name}\n{_xlsx_mod._format_sheet_csv(rows, ',')}")
                content = "\n".join(parts)
        else:
            # txt / csv / md 直接读取
            content = tmp_path.read_text(encoding="utf-8", errors="replace")

        # 截断过长内容
        max_chars = 50000
        truncated = len(content) > max_chars
        if truncated:
            content = content[:max_chars]

        return {
            "status": "success",
            "filename": filename,
            "content": content,
            "truncated": truncated,
            "char_count": len(content),
        }
    except Exception as e:
        logger.error(f"文档解析失败: {e}")
        raise HTTPException(status_code=500, detail=f"解析失败: {str(e)}")
    finally:
        tmp_path.unlink(missing_ok=True)


@app.get("/update/latest")
async def proxy_update_check(platform: str = "windows"):
    """Update check is disabled in local-only mode."""
    return {"has_update": False, "local_mode": True}


app.mount("/llm", llm_app)


# 新增：日志解析相关API接口
@app.get("/logs/context/statistics")
async def get_log_context_statistics(days: int = 7):
    """获取日志上下文统计信息"""
    try:
        statistics = message_manager.get_context_statistics(days)
        return {"status": "success", "statistics": statistics}
    except Exception as e:
        print(f"获取日志上下文统计错误: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"获取统计信息失败: {str(e)}")


@app.get("/logs/context/load")
async def load_log_context(days: int = 3, max_messages: int = None):
    """加载日志上下文"""
    try:
        messages = message_manager.load_recent_context(days=days, max_messages=max_messages)
        return {"status": "success", "messages": messages, "count": len(messages), "days": days}
    except Exception as e:
        print(f"加载日志上下文错误: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"加载上下文失败: {str(e)}")


# Web前端工具状态轮询存储
_tool_status_store: Dict[str, Dict] = {"current": {"message": "", "visible": False}}

@app.get("/tool_status")
async def get_tool_status():
    """获取当前工具调用状态（供Web前端轮询）"""
    return _tool_status_store.get("current", {"message": "", "visible": False})


@app.post("/tool_notification")
async def tool_notification(payload: Dict[str, Any]):
    """接收工具调用状态通知，只显示工具调用状态，不显示结果"""
    try:
        session_id = payload.get("session_id")
        tool_calls = payload.get("tool_calls", [])
        message = payload.get("message", "")
        stage = payload.get("stage", "")
        auto_hide_ms_raw = payload.get("auto_hide_ms", 0)

        try:
            auto_hide_ms = int(auto_hide_ms_raw)
        except (TypeError, ValueError):
            auto_hide_ms = 0

        if not session_id:
            raise HTTPException(400, "缺少session_id")

        # 记录工具调用状态（不处理结果，结果由tool_result_callback处理）
        for tool_call in tool_calls:
            tool_name = tool_call.get("tool_name", "未知工具")
            service_name = tool_call.get("service_name", "未知服务")
            status = tool_call.get("status", "starting")
            logger.info(f"工具调用状态: {tool_name} ({service_name}) - {status}")

        display_message = message
        if not display_message:
            if stage == "detecting":
                display_message = "正在检测工具调用"
            elif stage == "executing":
                display_message = f"检测到{len(tool_calls)}个工具调用，执行中"
            elif stage == "none":
                display_message = "未检测到工具调用"

        if stage == "hide":
            _hide_tool_status_in_ui()
        elif display_message:
            _emit_tool_status_to_ui(display_message, auto_hide_ms)

        return {
            "success": True,
            "message": "工具调用状态通知已接收",
            "tool_calls": tool_calls,
            "display_message": display_message,
            "stage": stage,
            "auto_hide_ms": auto_hide_ms,
        }

    except Exception as e:
        logger.error(f"工具调用通知处理失败: {e}")
        raise HTTPException(500, f"处理失败: {str(e)}")


@app.post("/tool_result_callback")
async def tool_result_callback(payload: Dict[str, Any]):
    """接收MCP工具执行结果回调，让主AI基于原始对话和工具结果重新生成回复"""
    try:
        session_id = payload.get("session_id")
        task_id = payload.get("task_id")
        result = payload.get("result", {})
        success = payload.get("success", False)

        if not session_id:
            raise HTTPException(400, "缺少session_id")

        _emit_tool_status_to_ui("生成工具回调", 0)

        logger.info(f"[工具回调] 开始处理工具回调，会话: {session_id}, 任务ID: {task_id}")
        logger.info(f"[工具回调] 回调内容: {result}")

        # 获取工具执行结果
        tool_result = result.get("result", "执行成功") if success else result.get("error", "未知错误")
        logger.info(f"[工具回调] 工具执行结果: {tool_result}")

        # 获取原始对话的最后一条用户消息（触发工具调用的消息）
        session_messages = message_manager.get_messages(session_id)
        original_user_message = ""
        for msg in reversed(session_messages):
            if msg.get("role") == "user":
                original_user_message = msg.get("content", "")
                break

        # 构建包含工具结果的用户消息
        enhanced_message = f"{original_user_message}\n\n[工具执行结果]: {tool_result}"
        logger.info(f"[工具回调] 构建增强消息: {enhanced_message[:200]}...")

        # 构建对话风格提示词和消息
        system_prompt = build_system_prompt(include_skills=True)
        messages = message_manager.build_conversation_messages(
            session_id=session_id, system_prompt=system_prompt, current_message=enhanced_message
        )

        logger.info("[工具回调] 开始生成工具后回复...")

        # 使用LLM服务基于原始对话和工具结果重新生成回复
        try:
            llm_service = get_llm_service()
            response_text = await llm_service.chat_with_context(messages, temperature=0.7)
            logger.info(f"[工具回调] 工具后回复生成成功，内容: {response_text[:200]}...")
        except Exception as e:
            logger.error(f"[工具回调] 调用LLM服务失败: {e}")
            response_text = f"处理工具结果时出错: {str(e)}"

        # 只保存AI回复到历史记录（用户消息已在正常对话流程中保存）
        message_manager.add_message(session_id, "assistant", response_text)
        logger.info("[工具回调] AI回复已保存到历史")

        # 保存对话日志到文件
        message_manager.save_conversation_log(original_user_message, response_text, dev_mode=False)
        logger.info("[工具回调] 对话日志已保存")

        # 工具结果后回复已写入会话历史，前端应通过标准会话读取链路更新。
        _hide_tool_status_in_ui()

        logger.info("[工具回调] 工具结果处理完成，回复已发送到UI")

        return {
            "success": True,
            "message": "工具结果已通过主AI处理并返回给UI",
            "response": response_text,
            "task_id": task_id,
            "session_id": session_id,
        }

    except Exception as e:
        _hide_tool_status_in_ui()
        logger.error(f"[工具回调] 工具结果回调处理失败: {e}")
        raise HTTPException(500, f"处理失败: {str(e)}")


@app.post("/tool_result")
async def tool_result(payload: Dict[str, Any]):
    """接收工具执行结果并显示在UI上"""
    try:
        session_id = payload.get("session_id")
        result = payload.get("result", "")
        notification_type = payload.get("type", "")
        ai_response = payload.get("ai_response", "")

        if not session_id:
            raise HTTPException(400, "缺少session_id")

        logger.info(f"工具执行结果: {result}")

        # AgentServer 轮询队列已退役：仅记录结果，不再排队推送旧前端通道。
        if notification_type == "tool_completed_with_ai_response" and ai_response:
            logger.info(f"[UI] 收到 tool_completed_with_ai_response（legacy queue retired），长度: {len(ai_response)}")

        return {"success": True, "message": "工具结果已接收", "result": result, "session_id": session_id}

    except Exception as e:
        logger.error(f"处理工具结果失败: {e}")
        raise HTTPException(500, f"处理失败: {str(e)}")


@app.post("/save_tool_conversation")
async def save_tool_conversation(payload: Dict[str, Any]):
    """保存工具对话历史"""
    try:
        session_id = payload.get("session_id")
        user_message = payload.get("user_message", "")
        assistant_response = payload.get("assistant_response", "")

        if not session_id:
            raise HTTPException(400, "缺少session_id")

        logger.info(f"[保存工具对话] 开始保存工具对话历史，会话: {session_id}")

        # 保存用户消息（工具执行结果）
        if user_message:
            message_manager.add_message(session_id, "user", user_message)

        # 保存AI回复
        if assistant_response:
            message_manager.add_message(session_id, "assistant", assistant_response)

        logger.info(f"[保存工具对话] 工具对话历史已保存，会话: {session_id}")

        return {"success": True, "message": "工具对话历史已保存", "session_id": session_id}

    except Exception as e:
        logger.error(f"[保存工具对话] 保存工具对话历史失败: {e}")
        raise HTTPException(500, f"保存失败: {str(e)}")


@app.post("/ui_notification")
async def ui_notification(payload: Dict[str, Any]):
    """UI通知接口 - 用于直接控制UI显示"""
    try:
        session_id = payload.get("session_id")
        action = payload.get("action", "")
        status_text = payload.get("status_text", "")
        auto_hide_ms_raw = payload.get("auto_hide_ms", 0)

        try:
            auto_hide_ms = int(auto_hide_ms_raw)
        except (TypeError, ValueError):
            auto_hide_ms = 0

        if not session_id:
            raise HTTPException(400, "缺少session_id")

        logger.info(f"UI通知: {action}, 会话: {session_id}")

        if action == "show_tool_status" and status_text:
            _emit_tool_status_to_ui(status_text, auto_hide_ms)
            return {"success": True, "message": "工具状态已显示"}

        if action == "hide_tool_status":
            _hide_tool_status_in_ui()
            return {"success": True, "message": "工具状态已隐藏"}

        return {"success": True, "message": "UI通知已处理"}

    except Exception as e:
        logger.error(f"处理UI通知失败: {e}")
        raise HTTPException(500, f"处理失败: {str(e)}")


async def _trigger_chat_stream_no_intent(session_id: str, response_text: str):
    """触发聊天流式响应但不触发意图分析 - 发送纯粹的AI回复到UI"""
    try:
        logger.info(f"[UI发送] 开始发送AI回复到UI，会话: {session_id}")
        logger.info(f"[UI发送] 发送内容: {response_text[:200]}...")

        # 直接调用现有的流式对话接口，但跳过意图分析
        import httpx

        # 构建请求数据 - 使用纯粹的AI回复内容，并跳过意图分析
        chat_request = {
            "message": response_text,  # 直接使用AI回复内容，不加标记
            "stream": True,
            "session_id": session_id,
            "skip_intent_analysis": True,  # 关键：跳过意图分析
            "stream_protocol": "sse_json_v1",
        }

        # 调用现有的流式对话接口
        from system.config import get_server_port

        api_url = f"http://localhost:{get_server_port('api_server')}/chat/stream"

        async with httpx.AsyncClient() as client:
            async with client.stream("POST", api_url, json=chat_request) as response:
                if response.status_code == 200:
                    # 处理流式响应
                    async for chunk in response.aiter_text():
                        if chunk.strip():
                            # 这里可以进一步处理流式响应
                            # 或者直接让UI处理流式响应
                            pass

                    logger.info(f"[UI发送] AI回复已成功发送到UI: {session_id}")
                    logger.info("[UI发送] 成功显示到UI")
                else:
                    logger.error(f"[UI发送] 调用流式对话接口失败: {response.status_code}")

    except Exception as e:
        logger.error(f"[UI发送] 触发聊天流式响应失败: {e}")


def _emit_tool_status_to_ui(status_text: str, auto_hide_ms: int = 0) -> None:
    """更新工具状态存储，前端通过轮询获取"""
    _tool_status_store["current"] = {"message": status_text, "visible": True}


def _hide_tool_status_in_ui() -> None:
    """隐藏工具状态，前端通过轮询获取"""
    _tool_status_store["current"] = {"message": "", "visible": False}


async def _send_ai_response_directly(session_id: str, response_text: str):
    """直接发送AI回复到UI"""
    try:
        import httpx

        # 使用非流式接口发送AI回复
        chat_request = {
            "message": f"[工具结果] {response_text}",  # 添加标记让UI知道这是工具结果
            "stream": False,
            "session_id": session_id,
            "skip_intent_analysis": True,
        }

        from system.config import get_server_port

        api_url = f"http://localhost:{get_server_port('api_server')}/chat"

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(api_url, json=chat_request)
            if response.status_code == 200:
                logger.info(f"[直接发送] AI回复已通过非流式接口发送到UI: {session_id}")
            else:
                logger.error(f"[直接发送] 非流式接口发送失败: {response.status_code}")

    except Exception as e:
        logger.error(f"[直接发送] 直接发送AI回复失败: {e}")


# 工具执行结果已通过LLM总结并保存到对话历史中
# UI可以通过查询历史获取工具执行结果
