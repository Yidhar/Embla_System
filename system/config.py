# config.py - 简化配置系统
"""
Embla System 配置系统 - 基于 Pydantic 实现类型安全和验证
支持配置热更新和变更通知
"""

import os
import json
import copy
import logging
import fnmatch
from pathlib import Path
from types import UnionType
from typing import Optional, List, Dict, Any, Callable, get_args, get_origin, Union
from datetime import datetime

from pydantic import BaseModel, Field, field_validator
from charset_normalizer import from_path
import json5  # 支持带注释的JSON解析
from agents.prompt_engine import (
    PromptAssembler,
    PromptBlockNotFoundError,
    get_available_mcp_tools_summary,
    get_system_prompts_root,
)

try:
    import yaml
except Exception:  # pragma: no cover - graceful fallback when yaml dependency is unavailable
    yaml = None


logger = logging.getLogger(__name__)


# ========== 服务器端口配置 - 统一管理 ==========
class ServerPortsConfig(BaseModel):
    """服务器端口配置 - 统一管理所有服务器端口"""

    # 主API服务器
    api_server: int = Field(default=8000, ge=1, le=65535, description="API服务器端口")

    # 智能体服务器
    agent_server: int = Field(default=8001, ge=1, le=65535, description="智能体服务器端口")

    # MCP工具服务器
    mcp_server: int = Field(default=8003, ge=1, le=65535, description="MCP工具服务器端口")

# 全局服务器端口配置实例
server_ports = ServerPortsConfig()

_EMBLA_SYSTEM_CONFIG_ENV = "EMBLA_SYSTEM_CONFIG_PATH"
_EMBLA_SYSTEM_DEFAULT_FILE = "embla_system.yaml"
_EMBLA_SYSTEM_DEFAULT_SECURITY: Dict[str, Any] = {
    "enforce_dual_lane": True,
    "approval_required_scopes": ["core", "policy", "prompt_dna", "tools_registry"],
    "audit_ledger_file": "scratch/runtime/audit_ledger.jsonl",
    "audit_signing_key_env": "EMBLA_AUDIT_SIGNING_KEY",
    "immutable_dna_runtime_prompts": [
        "conversation_style_prompt",
        "agentic_tool_prompt",
    ],
    "immutable_agent_identity_prompts": [
        "shell_persona",
        "core_values",
    ],
}
_embla_system_config: Dict[str, Any] = {}


def get_server_port(server_name: str) -> int:
    """获取指定服务器的端口号"""
    return getattr(server_ports, server_name, None)


def get_all_server_ports() -> Dict[str, int]:
    """获取所有服务器端口配置"""
    return {
        "api_server": server_ports.api_server,
        "agent_server": server_ports.agent_server,
        "mcp_server": server_ports.mcp_server,
    }


def _deep_merge_dict(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    merged: Dict[str, Any] = copy.deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_dict(merged[key], value)
            continue
        merged[key] = copy.deepcopy(value)
    return merged


def _resolve_embla_system_config_path(config_path: str | Path | None = None) -> Path:
    base_dir = Path(__file__).parent.parent
    if config_path is not None:
        candidate = Path(config_path)
    else:
        raw = str(os.getenv(_EMBLA_SYSTEM_CONFIG_ENV, "")).strip()
        candidate = Path(raw) if raw else base_dir / _EMBLA_SYSTEM_DEFAULT_FILE
    if not candidate.is_absolute():
        candidate = base_dir / candidate
    return candidate


def _embla_system_default_payload() -> Dict[str, Any]:
    return {
        "version": 1,
        "profile": "pythonic-secure",
        "runtime": {
            "heartbeat_interval_seconds": 5,
            "max_rounds_default": 500,
            "max_task_cost_usd": 5.0,
            "child_session_cleanup": {
                "mode": "retain",
                "ttl_seconds": 86400,
            },
        },
        "security": copy.deepcopy(_EMBLA_SYSTEM_DEFAULT_SECURITY),
        "watchers": {
            "tools_registry_root": "workspace/tools_registry",
            "backend": "watchdog",
        },
        "ops": {
            "posture_endpoint": "/v1/ops/runtime/posture",
            "incidents_latest_endpoint": "/v1/ops/incidents/latest",
        },
    }


def _normalize_embla_system_payload(payload: Dict[str, Any], *, source: str, loaded: bool) -> Dict[str, Any]:
    merged = _deep_merge_dict(_embla_system_default_payload(), payload if isinstance(payload, dict) else {})
    runtime = merged.get("runtime") if isinstance(merged.get("runtime"), dict) else {}
    merged["runtime"] = runtime
    child_cleanup = runtime.get("child_session_cleanup") if isinstance(runtime.get("child_session_cleanup"), dict) else {}
    runtime["child_session_cleanup"] = child_cleanup
    mode = str(child_cleanup.get("mode") or "retain").strip().lower()
    mode_aliases = {
        "off": "retain",
        "none": "retain",
        "disabled": "retain",
        "destroy_on_end": "destroy",
        "immediate_destroy": "destroy",
    }
    mode = mode_aliases.get(mode, mode)
    if mode not in {"retain", "destroy", "ttl"}:
        mode = "retain"
    child_cleanup["mode"] = mode
    try:
        ttl_seconds = int(child_cleanup.get("ttl_seconds", 86400))
    except (TypeError, ValueError):
        ttl_seconds = 86400
    child_cleanup["ttl_seconds"] = max(0, min(2592000, ttl_seconds))

    security = merged.get("security") if isinstance(merged.get("security"), dict) else {}
    merged["security"] = security

    if not isinstance(security.get("approval_required_scopes"), list):
        security["approval_required_scopes"] = list(_EMBLA_SYSTEM_DEFAULT_SECURITY["approval_required_scopes"])
    else:
        normalized_scopes = []
        for scope in security.get("approval_required_scopes", []):
            text = str(scope or "").strip().lower()
            if text and text not in normalized_scopes:
                normalized_scopes.append(text)
        security["approval_required_scopes"] = normalized_scopes or list(_EMBLA_SYSTEM_DEFAULT_SECURITY["approval_required_scopes"])

    prompts_dir = get_system_prompts_root()
    if not isinstance(security.get("immutable_dna_runtime_prompts"), list):
        security["immutable_dna_runtime_prompts"] = list(_EMBLA_SYSTEM_DEFAULT_SECURITY["immutable_dna_runtime_prompts"])
    else:
        normalized_runtime_prompts = _normalize_embla_prompt_name_list(
            security.get("immutable_dna_runtime_prompts"),
            prompts_dir=prompts_dir,
        )
        security["immutable_dna_runtime_prompts"] = normalized_runtime_prompts or list(
            _EMBLA_SYSTEM_DEFAULT_SECURITY["immutable_dna_runtime_prompts"]
        )

    if not isinstance(security.get("immutable_agent_identity_prompts"), list):
        security["immutable_agent_identity_prompts"] = list(_EMBLA_SYSTEM_DEFAULT_SECURITY["immutable_agent_identity_prompts"])
    else:
        normalized_identity_prompts = _normalize_embla_prompt_name_list(
            security.get("immutable_agent_identity_prompts"),
            prompts_dir=prompts_dir,
        )
        security["immutable_agent_identity_prompts"] = normalized_identity_prompts or list(
            _EMBLA_SYSTEM_DEFAULT_SECURITY["immutable_agent_identity_prompts"]
        )

    audit_ledger_file = str(security.get("audit_ledger_file") or "").strip()
    if not audit_ledger_file:
        security["audit_ledger_file"] = str(_EMBLA_SYSTEM_DEFAULT_SECURITY["audit_ledger_file"])
    security["audit_signing_key_env"] = str(
        security.get("audit_signing_key_env") or _EMBLA_SYSTEM_DEFAULT_SECURITY["audit_signing_key_env"]
    ).strip() or str(_EMBLA_SYSTEM_DEFAULT_SECURITY["audit_signing_key_env"])
    security["enforce_dual_lane"] = bool(security.get("enforce_dual_lane", True))
    security.pop("immutable_paths", None)

    watchers = merged.get("watchers") if isinstance(merged.get("watchers"), dict) else {}
    merged["watchers"] = watchers
    watchers.pop("prompt_root", None)
    watchers["tools_registry_root"] = str(watchers.get("tools_registry_root") or "workspace/tools_registry").strip() or "workspace/tools_registry"
    watchers["backend"] = str(watchers.get("backend") or "watchdog").strip() or "watchdog"

    merged["config_source"] = str(source).replace("\\", "/")
    merged["config_loaded"] = bool(loaded)
    return merged


def load_embla_system_config(config_path: str | Path | None = None) -> Dict[str, Any]:
    """加载 Embla System 统一配置（embla_system.yaml），失败时回退到安全默认值。"""
    path = _resolve_embla_system_config_path(config_path)
    if not path.exists():
        return _normalize_embla_system_payload({}, source=str(path), loaded=False)

    parsed: Dict[str, Any] = {}
    try:
        text = path.read_text(encoding="utf-8")
        if yaml is not None:
            loaded = yaml.safe_load(text)
        else:
            # 降级模式：允许 JSON/JSON5 形态配置。
            loaded = json5.loads(text)
        if isinstance(loaded, dict):
            parsed = loaded
    except Exception as exc:
        logger.warning("load embla_system config failed %s: %s", path, exc)
    return _normalize_embla_system_payload(parsed, source=str(path), loaded=bool(parsed))


def _refresh_embla_system_config() -> Dict[str, Any]:
    global _embla_system_config
    _embla_system_config = load_embla_system_config()
    return _embla_system_config


def get_embla_system_config() -> Dict[str, Any]:
    if not isinstance(_embla_system_config, dict) or not _embla_system_config:
        _refresh_embla_system_config()
    return copy.deepcopy(_embla_system_config)


def _normalize_embla_prompt_name(name: Any, *, prompts_dir: Optional[Path] = None) -> str:
    text = str(name or "").strip().replace("\\", "/")
    if not text:
        return ""
    resolved_prompts_dir = _resolve_prompts_dir(prompts_dir)
    candidate_names: List[str] = [text]
    basename = Path(text).name.strip()
    if basename and basename not in candidate_names:
        candidate_names.append(basename)
    for candidate_name in candidate_names:
        try:
            resolved = resolve_prompt_registry_entry(prompt_name=candidate_name, prompts_dir=resolved_prompts_dir)
            canonical_name = str(resolved.get("canonical_name") or "").strip()
            if canonical_name and "/" not in canonical_name.replace("\\", "/"):
                return canonical_name
        except Exception:
            logger.debug("normalize embla prompt name fallback: %s", candidate_name, exc_info=True)
    lowered = text.lower()
    if lowered.endswith(".md"):
        return text[:-3]
    if lowered.endswith(".spec"):
        return text[:-5]
    return text


def _normalize_embla_prompt_name_list(value: Any, *, prompts_dir: Optional[Path] = None) -> List[str]:
    if not isinstance(value, list):
        return []
    normalized: List[str] = []
    for item in value:
        text = _normalize_embla_prompt_name(item, prompts_dir=prompts_dir)
        if text and text not in normalized:
            normalized.append(text)
    return normalized


def get_immutable_dna_runtime_prompts() -> List[str]:
    payload = get_embla_system_config()
    security = payload.get("security") if isinstance(payload.get("security"), dict) else {}
    rows = _normalize_embla_prompt_name_list(security.get("immutable_dna_runtime_prompts"), prompts_dir=get_system_prompts_root())
    if rows:
        return rows
    return list(_EMBLA_SYSTEM_DEFAULT_SECURITY["immutable_dna_runtime_prompts"])


def get_immutable_agent_identity_prompts() -> List[str]:
    payload = get_embla_system_config()
    security = payload.get("security") if isinstance(payload.get("security"), dict) else {}
    rows = _normalize_embla_prompt_name_list(
        security.get("immutable_agent_identity_prompts"),
        prompts_dir=get_system_prompts_root(),
    )
    if rows:
        return rows
    return list(_EMBLA_SYSTEM_DEFAULT_SECURITY["immutable_agent_identity_prompts"])


def get_all_immutable_dna_prompts() -> List[str]:
    rows: List[str] = []
    for item in get_immutable_dna_runtime_prompts() + get_immutable_agent_identity_prompts():
        text = str(item or "").strip()
        if text and text not in rows:
            rows.append(text)
    return rows


def save_embla_system_config(payload: Dict[str, Any], config_path: str | Path | None = None) -> Dict[str, Any]:
    """保存 Embla System 统一配置并刷新进程内缓存。"""
    if not isinstance(payload, dict):
        raise ValueError("embla_system payload must be a dict")
    path = _resolve_embla_system_config_path(config_path)
    normalized = _normalize_embla_system_payload(payload, source=str(path), loaded=True)
    to_persist = {k: v for k, v in normalized.items() if k not in {"config_source", "config_loaded"}}
    path.parent.mkdir(parents=True, exist_ok=True)
    if yaml is not None:
        text = yaml.safe_dump(to_persist, allow_unicode=True, sort_keys=False)
    else:
        text = json.dumps(to_persist, ensure_ascii=False, indent=2)
    path.write_text(text, encoding="utf-8")
    global _embla_system_config
    _embla_system_config = dict(normalized)
    return copy.deepcopy(_embla_system_config)


# 配置变更监听器
def _safe_int_port(value: Any) -> int | None:
    """Best-effort parse and validate a TCP port value."""
    try:
        port = int(value)
    except (TypeError, ValueError):
        return None
    if 1 <= port <= 65535:
        return port
    return None


def _sync_server_ports_from_config_data(config_data: Dict[str, Any]) -> None:
    """Synchronize global `server_ports` from raw config payload before model creation."""
    if not isinstance(config_data, dict):
        return

    candidates = {
        "api_server": (
            config_data.get("api_server", {}).get("port"),
            config_data.get("server_ports", {}).get("api_server"),
        ),
        "agent_server": (
            config_data.get("agent_server", {}).get("port"),
            config_data.get("server_ports", {}).get("agent_server"),
        ),
        "mcp_server": (
            config_data.get("mcpserver", {}).get("port"),
            config_data.get("mcp_server", {}).get("port"),
            config_data.get("server_ports", {}).get("mcp_server"),
        ),
    }

    for server_name, values in candidates.items():
        for value in values:
            port = _safe_int_port(value)
            if port is not None:
                setattr(server_ports, server_name, port)
                break


_config_listeners: List[Callable] = []


# 为了向后兼容，提供AI_NAME常量
def get_ai_name() -> str:
    """获取AI名称"""
    return config.system.ai_name


def add_config_listener(callback: Callable):
    """添加配置变更监听器"""
    _config_listeners.append(callback)


def remove_config_listener(callback: Callable):
    """移除配置变更监听器"""
    if callback in _config_listeners:
        _config_listeners.remove(callback)


def notify_config_changed():
    """通知所有监听器配置已变更"""
    for listener in _config_listeners:
        try:
            listener()
        except Exception:
            logger.exception("config listener execution failed")


def setup_environment():
    """设置环境变量解决兼容性问题"""
    env_vars = {
        "OMP_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "VECLIB_MAXIMUM_THREADS": "1",
        "NUMEXPR_NUM_THREADS": "1",
        "TOKENIZERS_PARALLELISM": "false",
        "PYTORCH_MPS_HIGH_WATERMARK_RATIO": "0.0",
        "PYTORCH_ENABLE_MPS_FALLBACK": "1",
        "LITELLM_LOG": "ERROR",
    }
    for key, value in env_vars.items():
        os.environ.setdefault(key, value)


def detect_file_encoding(file_path: str) -> str:
    """检测文本文件编码，失败时回退到utf-8"""
    try:
        charset_results = from_path(file_path)
        if charset_results:
            best_match = charset_results.best()
            if best_match and best_match.encoding:
                return best_match.encoding
    except Exception as exc:
        logger.warning("detect file encoding failed %s: %s", file_path, exc)
    return "utf-8"


def bootstrap_config_from_example(config_path: str) -> None:
    """当config.json缺失时，从config.json.example读取并写入utf-8版本"""
    if os.path.exists(config_path):
        return

    example_path = str(Path(config_path).with_name("config.json.example"))
    if not os.path.exists(example_path):
        return

    try:
        detected_encoding = detect_file_encoding(example_path)
        logger.info("detected config template encoding: %s (%s)", detected_encoding, example_path)
        with open(example_path, "r", encoding=detected_encoding) as example_file:
            example_content = example_file.read()

        with open(config_path, "w", encoding="utf-8") as config_file:
            config_file.write(example_content)

        logger.info("bootstrapped config.json from config.json.example using utf-8")
    except Exception as exc:
        logger.warning("bootstrap config.json from example failed: %s", exc)


def _normalize_annotation_payload(annotation: Any, value: Any) -> Any:
    if value is None:
        return None

    origin = get_origin(annotation)
    args = get_args(annotation)

    if origin is None:
        if isinstance(annotation, type) and issubclass(annotation, BaseModel) and isinstance(value, dict):
            return _normalize_model_payload(annotation, value)
        return copy.deepcopy(value)

    if origin in (list, List):
        item_annotation = args[0] if args else Any
        if isinstance(value, list):
            return [_normalize_annotation_payload(item_annotation, item) for item in value]
        return copy.deepcopy(value)

    if origin in (dict, Dict):
        value_annotation = args[1] if len(args) > 1 else Any
        if isinstance(value, dict):
            return {copy.deepcopy(key): _normalize_annotation_payload(value_annotation, item) for key, item in value.items()}
        return copy.deepcopy(value)

    if origin in (Union, UnionType):
        for candidate in args:
            if candidate is type(None):
                continue
            if isinstance(candidate, type) and issubclass(candidate, BaseModel) and isinstance(value, dict):
                return _normalize_model_payload(candidate, value)
        return copy.deepcopy(value)

    return copy.deepcopy(value)


def _normalize_model_payload(model_cls: type[BaseModel], payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {}

    normalized: Dict[str, Any] = {}
    for field_name, field_info in model_cls.model_fields.items():
        if field_name not in payload:
            continue
        normalized[field_name] = _normalize_annotation_payload(field_info.annotation, payload[field_name])
    return normalized


def normalize_runtime_config_payload(config_data: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize config payload to canonical Embla System keys."""
    if not isinstance(config_data, dict):
        return {}

    return _normalize_model_payload(EmblaSystemConfig, copy.deepcopy(config_data))


class SystemConfig(BaseModel):
    """系统基础配置"""

    version: str = Field(default="5.0.0", description="系统版本号")
    config_schema_version: int = Field(default=1, ge=1, description="配置结构版本号")
    ai_name: str = Field(default="Embla", description="AI助手名称")
    base_dir: Path = Field(default_factory=lambda: Path(__file__).parent.parent, description="项目根目录")
    log_dir: Path = Field(default_factory=lambda: Path(__file__).parent.parent / "logs", description="日志目录")
    stream_mode: bool = Field(default=True, description="是否启用流式响应")
    debug: bool = Field(default=False, description="是否启用调试模式")
    log_level: str = Field(default="INFO", description="日志级别")
    save_prompts: bool = Field(default=True, description="是否保存提示词")

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v):
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if v.upper() not in valid_levels:
            raise ValueError(f"日志级别必须是以下之一: {valid_levels}")
        return v.upper()


class APIRouteTargetConfig(BaseModel):
    """按路由分层覆盖 LLM 连接参数（留空回退到 api.*）。"""

    api_key: str = Field(default="", description="路由专用API密钥（留空回退到 api.api_key）")
    base_url: str = Field(default="", description="路由专用API地址（留空回退到 api.base_url）")
    model: str = Field(default="", description="路由专用模型名（留空回退到 api.model）")
    provider: str = Field(default="", description="路由专用provider（留空回退到 api.provider）")
    protocol: str = Field(default="", description="路由专用协议（留空回退到 api.protocol）")
    reasoning_effort: str = Field(default="", description="路由专用 reasoning_effort（low/medium/high/xhigh）")
    thinking_intensity: str = Field(default="", description="兼容字段：等价于 reasoning_effort")

    @field_validator("reasoning_effort", "thinking_intensity")
    @classmethod
    def validate_reasoning_effort(cls, value: str) -> str:
        normalized = str(value or "").strip().lower()
        if normalized in {"", "auto", "default"}:
            return ""
        valid_values = {"low", "medium", "high", "xhigh"}
        if normalized not in valid_values:
            raise ValueError(f"reasoning_effort 必须是以下之一: {sorted(valid_values)}")
        return normalized


class APIRoutingConfig(BaseModel):
    """Shell/Core 路由 LLM 覆盖配置。"""

    shell: APIRouteTargetConfig = Field(
        default_factory=APIRouteTargetConfig,
        description="Shell 对话路径（shell_readonly/shell_clarify）LLM 覆盖配置",
    )
    core: APIRouteTargetConfig = Field(
        default_factory=APIRouteTargetConfig,
        description="Core 执行路径（core_execution）LLM 覆盖配置",
    )


class APIShellLoopConfig(BaseModel):
    """Shell 只读工具循环的停止条件配置。"""

    max_rounds: int = Field(default=12, ge=1, le=64, description="Shell 只读工具循环的兜底最大轮次")
    repeated_tool_pattern_rounds: int = Field(
        default=3,
        ge=2,
        le=16,
        description="连续重复相同工具调用模式达到该轮次后停止继续工具循环",
    )
    no_new_fact_rounds: int = Field(
        default=3,
        ge=1,
        le=16,
        description="连续未获得新增事实达到该轮次后停止继续工具循环",
    )


class APIConfig(BaseModel):
    """API服务配置"""

    api_key: str = Field(default="sk-placeholder-key-not-set", description="API密钥")
    base_url: str = Field(default="https://api.deepseek.com/v1", description="API基础URL")
    model: str = Field(default="deepseek-v3.2", description="使用的模型名称")
    provider: str = Field(default="openai_compatible", description="API提供商类型")
    protocol: str = Field(default="auto", description="API协议类型")
    reasoning_effort: str = Field(default="medium", description="OpenAI兼容推理强度（low/medium/high/xhigh）")
    thinking_intensity: str = Field(default="medium", description="思维强度（low/medium/high/xhigh）")
    google_live_api: bool = Field(default=False, description="Google Live API（BidiGenerateContent）开关")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="温度参数")
    max_tokens: int = Field(default=10000, ge=1, le=32768, description="最大token数")
    max_history_rounds: int = Field(default=100, ge=1, le=200, description="最大历史轮数")
    persistent_context: bool = Field(default=True, description="是否启用持久化上下文")
    context_load_days: int = Field(default=3, ge=1, le=30, description="加载历史上下文的天数")
    context_parse_logs: bool = Field(default=True, description="是否从日志文件解析上下文")
    applied_proxy: bool = Field(default=False, description="是否使用系统代理环境变量（HTTP_PROXY/HTTPS_PROXY）")
    request_timeout: int = Field(default=120, ge=1, le=600, description="模型请求超时时间（秒）")
    extra_headers: Dict[str, Any] = Field(default_factory=dict, description="附加HTTP请求头")
    extra_body: Dict[str, Any] = Field(default_factory=dict, description="附加请求体参数")
    routing: APIRoutingConfig = Field(
        default_factory=APIRoutingConfig,
        description="按路由（shell/core）覆盖 LLM API 地址与模型",
    )
    shell_loop: APIShellLoopConfig = Field(
        default_factory=APIShellLoopConfig,
        description="Shell 只读工具循环停止条件",
    )

    @field_validator("reasoning_effort", "thinking_intensity")
    @classmethod
    def validate_reasoning_effort(cls, value: str) -> str:
        normalized = str(value or "").strip().lower()
        if normalized in {"", "auto", "default"}:
            return "medium"
        valid_values = {"low", "medium", "high", "xhigh"}
        if normalized not in valid_values:
            raise ValueError(f"reasoning_effort 必须是以下之一: {sorted(valid_values)}")
        return normalized


class APIServerConfig(BaseModel):
    """API服务器配置"""

    enabled: bool = Field(default=True, description="是否启用API服务器")
    host: str = Field(default="127.0.0.1", description="API服务器主机")
    port: int = Field(default_factory=lambda: server_ports.api_server, description="API服务器端口")
    auto_start: bool = Field(default=True, description="启动时自动启动API服务器")
    docs_enabled: bool = Field(default=True, description="是否启用API文档")


class GRAGConfig(BaseModel):
    """GRAG知识图谱记忆系统配置"""

    enabled: bool = Field(default=False, description="是否启用GRAG记忆系统")
    auto_extract: bool = Field(default=False, description="是否自动提取对话中的五元组")
    context_length: int = Field(default=5, ge=1, le=20, description="记忆上下文长度")
    similarity_threshold: float = Field(default=0.6, ge=0.0, le=1.0, description="记忆检索相似度阈值")
    neo4j_uri: str = Field(default="neo4j://127.0.0.1:7687", description="Neo4j连接URI")
    neo4j_user: str = Field(default="neo4j", description="Neo4j用户名")
    neo4j_password: str = Field(default="your_password", description="Neo4j密码")
    neo4j_database: str = Field(default="neo4j", description="Neo4j数据库名")
    vector_index_enabled: bool = Field(default=True, description="是否启用Neo4j向量索引检索")
    vector_index_name: str = Field(default="entity_embedding_index", description="Neo4j向量索引名称")
    vector_query_top_k: int = Field(default=8, ge=1, le=200, description="向量检索Top-K")
    vector_similarity_function: str = Field(default="cosine", description="向量相似度函数（cosine/euclidean）")
    vector_upsert_on_write: bool = Field(default=True, description="写入五元组时是否同步更新实体向量")
    extraction_timeout: int = Field(default=12, ge=1, le=60, description="知识提取超时时间（秒）")
    extraction_retries: int = Field(default=2, ge=0, le=5, description="知识提取重试次数")
    base_timeout: int = Field(default=15, ge=5, le=120, description="基础操作超时时间（秒）")


class HandoffConfig(BaseModel):
    """工具调用循环配置"""

    max_loop_stream: int = Field(default=500, ge=1, le=2000, description="流式模式最大工具调用循环次数")
    max_loop_non_stream: int = Field(default=500, ge=1, le=2000, description="非流式模式最大工具调用循环次数")
    show_output: bool = Field(default=False, description="是否显示工具调用输出")


class AgenticLoopConfig(BaseModel):
    """Agentic Tool Loop 编排与控制配置"""

    max_rounds_stream: int = Field(default=500, ge=1, le=5000, description="流式模式最大循环轮次")
    max_rounds_non_stream: int = Field(default=500, ge=1, le=5000, description="非流式模式最大循环轮次")
    enable_summary_round: bool = Field(default=True, description="循环结束时是否执行总结轮")

    max_consecutive_tool_failures: int = Field(default=2, ge=1, le=20, description="连续工具执行失败阈值")
    max_consecutive_validation_failures: int = Field(default=2, ge=1, le=20, description="连续参数校验失败阈值")
    max_consecutive_no_tool_rounds: int = Field(default=2, ge=1, le=20, description="连续无工具调用阈值")

    inject_no_tool_feedback: bool = Field(default=False, description="无工具调用时是否注入纠偏反馈继续下一轮")
    tool_result_preview_chars: int = Field(default=500, ge=120, le=20000, description="前端工具结果预览长度")
    emit_workflow_stage_events: bool = Field(
        default=True, description="是否输出 plan/execute/verify/repair 阶段事件（SSE可视化）"
    )

    max_parallel_tool_calls: int = Field(default=8, ge=1, le=64, description="单轮最大并行工具调用数")
    retry_failed_tool_calls: bool = Field(default=True, description="是否自动重试失败工具调用")
    max_tool_retries: int = Field(default=1, ge=0, le=5, description="失败工具调用最大重试次数")
    retry_backoff_seconds: float = Field(default=0.8, ge=0.0, le=10.0, description="重试退避秒数")
    watchdog_guard_enabled: bool = Field(default=True, description="是否启用 agentic loop watchdog 观测/门禁")
    watchdog_warn_only: bool = Field(default=True, description="watchdog 是否仅告警不阻断")
    watchdog_sample_per_round: bool = Field(default=True, description="每轮执行后是否采样资源并评估阈值")
    watchdog_consecutive_error_limit: int = Field(default=5, ge=1, le=200, description="连续错误工具调用阈值")
    watchdog_tool_call_limit_per_minute: int = Field(default=10, ge=1, le=2000, description="每分钟工具调用阈值")
    watchdog_task_cost_limit: float = Field(default=5.0, ge=0.0, le=100000.0, description="单任务成本阈值")
    watchdog_daily_cost_limit: float = Field(default=50.0, ge=0.0, le=1000000.0, description="日成本阈值")
    watchdog_loop_window_seconds: int = Field(default=60, ge=1, le=3600, description="循环检测时间窗口（秒）")


class ToolContractRolloutConfig(BaseModel):
    """Structured tool-contract observability configuration."""

    emit_observability_metadata: bool = Field(
        default=True,
        description="是否输出结构化工具契约观测元数据",
    )

    def snapshot(self) -> Dict[str, Any]:
        return {
            "contract_mode": "structured_only",
            "emit_observability_metadata": bool(self.emit_observability_metadata),
        }


class AutonomousCliToolsConfig(BaseModel):
    """CLI tool preferences for system agent."""

    preferred: str = Field(default="claude", description="首选CLI")
    fallback_order: List[str] = Field(default_factory=lambda: ["claude", "gemini"], description="CLI降级顺序")
    max_retries: int = Field(default=2, ge=0, le=10, description="CLI重试次数")

class AutonomousLeaseConfig(BaseModel):
    """Single-active lease and fencing policy."""

    enabled: bool = Field(default=True, description="是否启用lease/fencing单活抢占")
    lease_name: str = Field(default="global_orchestrator", description="单活lease名称")
    owner_id: str = Field(default="", description="可选固定owner_id，留空则自动生成")
    renew_interval_seconds: int = Field(default=2, ge=1, le=60, description="lease续租间隔（秒）")
    ttl_seconds: int = Field(default=10, ge=2, le=300, description="lease有效期（秒）")
    standby_poll_interval_seconds: int = Field(default=2, ge=1, le=60, description="standby轮询间隔（秒）")


class AutonomousOutboxDispatchConfig(BaseModel):
    """Outbox async dispatcher settings."""

    enabled: bool = Field(default=True, description="是否启用outbox异步消费")
    consumer_name: str = Field(default="release-controller", description="inbox_dedup消费者名称")
    poll_interval_seconds: int = Field(default=2, ge=1, le=60, description="outbox轮询间隔（秒）")
    batch_size: int = Field(default=50, ge=1, le=1000, description="每批次最大出站事件数")


class AutonomousReleaseConfig(BaseModel):
    """Canary evaluation and rollback automation config."""

    enabled: bool = Field(default=True, description="是否启用canary/rollback自动化")
    gate_policy_path: str = Field(default="policy/gate_policy.yaml", description="gate策略文件路径")
    max_error_rate: float = Field(default=0.02, ge=0.0, le=1.0, description="canary最大允许错误率")
    max_latency_p95_ms: float = Field(default=1500.0, ge=1.0, le=60000.0, description="canary p95延迟阈值(ms)")
    min_kpi_ratio: float = Field(default=0.95, ge=0.0, le=1.0, description="canary KPI最低比例")
    auto_rollback_enabled: bool = Field(default=True, description="达到回滚条件时自动执行回滚命令")
    rollback_command: str = Field(default="", description="可选回滚命令")


class AutonomousConfig(BaseModel):
    """System Agent autonomous configuration."""

    enabled: bool = Field(default=False, description="是否启用自治循环")
    cycle_interval_seconds: int = Field(default=3600, ge=60, le=86400, description="自治循环间隔（秒）")
    cli_tools: AutonomousCliToolsConfig = Field(default_factory=AutonomousCliToolsConfig)
    run_quality_checks: bool = Field(default=False, description="是否在评估阶段运行lint/test")
    fixed_timeout_seconds: int = Field(default=3600, ge=60, le=14400, description="CLI执行超时（秒）")
    lease: AutonomousLeaseConfig = Field(default_factory=AutonomousLeaseConfig)
    outbox_dispatch: AutonomousOutboxDispatchConfig = Field(default_factory=AutonomousOutboxDispatchConfig)
    release: AutonomousReleaseConfig = Field(default_factory=AutonomousReleaseConfig)


class SandboxBoxLiteRuntimeProfileConfig(BaseModel):
    """Named BoxLite runtime profile used by execution sessions."""

    asset_name: str = Field(default="embla_py311_default", description="Embla 维护的运行时资产名")
    image: str = Field(default="embla/boxlite-runtime:py311", description="该 profile 优先使用的 OCI 镜像")
    image_candidates: List[str] = Field(
        default_factory=lambda: ["embla/boxlite-runtime:py311", "python:slim"],
        description="按顺序尝试的 OCI 镜像列表；用于本地 Embla 镜像优先、公共镜像兜底",
    )
    working_dir: str = Field(default="/workspace", description="box 内工作目录")
    cpus: int = Field(default=2, ge=1, le=64, description="默认 CPU 配额")
    memory_mib: int = Field(default=1024, ge=128, le=65536, description="默认内存配额(MiB)")
    security_preset: str = Field(default="maximum", description="development/standard/maximum")
    network_enabled: bool = Field(default=False, description="是否允许该 profile 访问网络")
    python_cmd: str = Field(default="python", description="guest helper 默认解释器命令")
    prewarm_command: List[str] = Field(
        default_factory=lambda: ["python", "-V"],
        description="用于 runtime 预热/校验的 guest 命令",
    )


def _default_boxlite_runtime_profiles() -> Dict[str, SandboxBoxLiteRuntimeProfileConfig]:
    return {
        "default": SandboxBoxLiteRuntimeProfileConfig(),
    }


class SandboxBoxLiteConfig(BaseModel):
    """BoxLite runtime configuration for execution backend selection."""

    enabled: bool = Field(default=True, description="是否启用 BoxLite execution backend")
    mode: str = Field(default="required", description="disabled/preferred/required")
    provider: str = Field(default="sdk", description="sdk/rest")
    base_url: str = Field(default="", description="REST provider base URL")
    runtime_profile: str = Field(default="default", description="默认 execution profile 对应的 BoxLite runtime profile")
    runtime_profiles: Dict[str, SandboxBoxLiteRuntimeProfileConfig] = Field(
        default_factory=_default_boxlite_runtime_profiles,
        description="命名 BoxLite runtime profile 注册表",
    )
    runtime_state_file: str = Field(default="scratch/runtime/boxlite_runtime_assets.json", description="运行时资产状态文件")
    install_prefetch_enabled: bool = Field(default=True, description="首次安装/显式 prepare 时是否预取默认 runtime profile")
    local_image_build_enabled: bool = Field(default=True, description="是否允许本地构建 Embla runtime 镜像")
    local_image_builder: str = Field(default="auto", description="本地镜像构建器：auto/docker/podman")
    local_image_context_dir: str = Field(default="system/boxlite/runtime_image", description="本地 runtime 镜像构建上下文目录")
    local_image_dockerfile: str = Field(default="Dockerfile", description="runtime 镜像 Dockerfile 文件名")
    auto_reconcile_enabled: bool = Field(default=True, description="是否启用空闲 runtime reconcile")
    reconcile_interval_seconds: int = Field(default=900, ge=60, le=86400, description="空闲 reconcile 间隔（秒）")
    reconcile_stale_after_seconds: int = Field(default=43200, ge=300, le=604800, description="运行时资产视为 stale 的阈值（秒）")
    core_ensure_before_spawn_enabled: bool = Field(default=True, description="spawn child 前是否主动 ensure 所需 runtime profile")
    image: str = Field(default="embla/boxlite-runtime:py311", description="legacy fallback：默认 BoxLite OCI 镜像")
    working_dir: str = Field(default="/workspace", description="legacy fallback：box 内工作目录")
    cpus: int = Field(default=2, ge=1, le=64, description="legacy fallback：默认 CPU 配额")
    memory_mib: int = Field(default=1024, ge=128, le=65536, description="legacy fallback：默认内存配额(MiB)")
    auto_remove: bool = Field(default=True, description="box 停止后是否自动清理")
    security_preset: str = Field(default="maximum", description="legacy fallback：development/standard/maximum")
    network_enabled: bool = Field(default=False, description="legacy fallback：是否允许 box 访问网络")
    auto_install_sdk: bool = Field(default=True, description="缺少 BoxLite SDK 时是否自动安装")
    install_timeout_seconds: int = Field(default=300, ge=10, le=3600, description="BoxLite SDK 自动安装超时（秒）")
    sdk_package_spec: str = Field(default="boxlite", description="自动安装使用的 pip 包规格")
    ensure_timeout_seconds: int = Field(default=45, ge=5, le=600, description="首次建箱/启动 helper 超时（秒）")
    startup_prewarm_enabled: bool = Field(default=True, description="启动时是否预热 BoxLite 运行时与镜像")
    startup_prewarm_timeout_seconds: int = Field(default=45, ge=5, le=600, description="启动预热超时（秒）")


class SandboxConfig(BaseModel):
    """Unified sandbox and execution backend configuration."""

    default_execution_backend: str = Field(default="boxlite", description="默认执行后端：native/boxlite")
    self_repo_execution_backend: str = Field(default="boxlite", description="self 仓库默认执行后端：native/boxlite（当前与全局默认一致）")
    boxlite: SandboxBoxLiteConfig = Field(default_factory=SandboxBoxLiteConfig)


class BrowserConfig(BaseModel):
    """浏览器配置"""

    playwright_headless: bool = Field(default=False, description="Playwright浏览器是否无头模式")
    edge_lnk_path: str = Field(
        default=r"C:\Users\DREEM\Desktop\Microsoft Edge.lnk", description="Edge浏览器快捷方式路径"
    )
    edge_common_paths: List[str] = Field(
        default=[
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            os.path.expanduser(r"~\AppData\Local\Microsoft\Edge\Application\msedge.exe"),
        ],
        description="Edge浏览器常见安装路径",
    )


class FilterConfig(BaseModel):
    """输出过滤配置"""

    filter_think_tags: bool = Field(default=True, description="过滤思考标签内容")
    filter_patterns: List[str] = Field(
        default=[
            r"<think>.*?</think>",
            r"<reflection>.*?</reflection>",
            r"<internal>.*?</internal>",
        ],
        description="过滤正则表达式模式",
    )
    clean_output: bool = Field(default=True, description="清理多余空白字符")


class DifficultyConfig(BaseModel):
    """问题难度判断配置"""

    enabled: bool = Field(default=False, description="是否启用难度判断")
    use_small_model: bool = Field(default=False, description="使用小模型进行难度判断")
    pre_assessment: bool = Field(default=False, description="是否启用前置难度判断")
    assessment_timeout: float = Field(default=1.0, ge=0.1, le=5.0, description="难度判断超时时间（秒）")
    difficulty_levels: List[str] = Field(default=["简单", "中等", "困难", "极难"], description="难度级别")
    factors: List[str] = Field(
        default=["概念复杂度", "推理深度", "知识广度", "计算复杂度", "创新要求"], description="难度评估因素"
    )
    threshold_simple: int = Field(default=2, ge=1, le=10, description="简单问题阈值")
    threshold_medium: int = Field(default=4, ge=1, le=10, description="中等问题阈值")
    threshold_hard: int = Field(default=6, ge=1, le=10, description="困难问题阈值")


class ScoringConfig(BaseModel):
    """黑白名单打分系统配置"""

    enabled: bool = Field(default=False, description="是否启用打分系统")
    score_range: List[int] = Field(default=[1, 5], description="评分范围")
    score_threshold: int = Field(default=2, ge=1, le=5, description="结果保留阈值")
    similarity_threshold: float = Field(default=0.85, ge=0.0, le=1.0, description="相似结果识别阈值")
    max_user_preferences: int = Field(default=3, ge=1, le=10, description="用户最多选择偏好数")
    default_preferences: List[str] = Field(default=["逻辑清晰准确", "实用性强", "创新思维"], description="默认偏好设置")
    penalty_for_similar: int = Field(default=1, ge=0, le=3, description="相似结果的惩罚分数")
    min_results_required: int = Field(default=2, ge=1, le=10, description="最少保留结果数量")
    strict_filtering: bool = Field(default=True, description="严格过滤模式")


# ========== 新增：电脑控制配置 ==========
class ComputerControlConfig(BaseModel):
    """电脑控制配置"""

    enabled: bool = Field(default=True, description="是否启用电脑控制功能")
    model: str = Field(default="gemini-2.5-flash", description="视觉/坐标识别模型")
    model_url: str = Field(default="https://open.bigmodel.cn/api/paas/v4", description="模型API地址")
    api_key: str = Field(default="", description="模型API密钥")
    grounding_model: str = Field(default="gemini-2.5-flash", description="元素定位/grounding模型")
    grounding_url: str = Field(default="https://open.bigmodel.cn/api/paas/v4", description="grounding模型API地址")
    grounding_api_key: str = Field(default="", description="grounding模型API密钥")
    screen_width: int = Field(default=1920, description="逻辑屏幕宽度（用于缩放体系）")
    screen_height: int = Field(default=1080, description="逻辑屏幕高度（用于缩放体系）")
    max_dim_size: int = Field(default=1920, description="逻辑空间最大边尺寸")
    dpi_awareness: bool = Field(default=True, description="是否启用DPI感知（Windows）")
    safe_mode: bool = Field(default=True, description="是否启用安全模式（限制高风险操作）")


class MemoryServerConfig(BaseModel):
    """记忆微服务配置。"""

    url: str = Field(default="http://localhost:8004", description="远程记忆服务地址")
    token: Optional[str] = Field(default=None, description="认证 Token（Bearer），留空则不携带认证头")


class EmbeddingConfig(BaseModel):
    """嵌入模型配置"""

    model: str = Field(default="text-embedding-v4", description="嵌入模型名称")
    api_base: str = Field(default="", description="嵌入模型API地址（留空回退到api.base_url）")
    api_key: str = Field(default="", description="嵌入模型API密钥（留空回退到api.api_key）")
    dimensions: int = Field(default=1024, ge=0, le=8192, description="向量维度（0表示由模型默认）")
    encoding_format: str = Field(default="float", description="编码格式（推荐 float）")
    max_input_tokens: int = Field(default=8192, ge=1, le=65536, description="单条输入最大Token预算")
    request_timeout_seconds: int = Field(default=30, ge=1, le=600, description="嵌入请求超时时间（秒）")


# 天气服务使用免费API，无需配置


class MQTTConfig(BaseModel):
    """MQTT配置"""

    enabled: bool = Field(default=False, description="是否启用MQTT功能")
    broker: str = Field(default="localhost", description="MQTT代理服务器地址")
    port: int = Field(default=1883, ge=1, le=65535, description="MQTT代理服务器端口")
    topic: str = Field(default="/test/topic", description="MQTT主题")
    client_id: str = Field(default="embla_mqtt_client", description="MQTT客户端ID")
    username: str = Field(default="", description="MQTT用户名")
    password: str = Field(default="", description="MQTT密码")
    keepalive: int = Field(default=60, ge=1, le=3600, description="保持连接时间（秒）")
    qos: int = Field(default=1, ge=0, le=2, description="服务质量等级")


class UIConfig(BaseModel):
    """用户界面配置"""

    user_name: str = Field(default="用户", description="默认用户名")
    bg_alpha: float = Field(default=0.5, ge=0.0, le=1.0, description="聊天背景透明度")
    window_bg_alpha: int = Field(default=110, ge=0, le=255, description="主窗口背景透明度")
    mac_btn_size: int = Field(default=36, ge=10, le=100, description="Mac按钮大小")
    mac_btn_margin: int = Field(default=16, ge=0, le=50, description="Mac按钮边距")
    mac_btn_gap: int = Field(default=12, ge=0, le=30, description="Mac按钮间距")
    animation_duration: int = Field(default=600, ge=100, le=2000, description="动画时长（毫秒）")


class FloatingConfig(BaseModel):
    """悬浮球模式配置"""
    enabled: bool = Field(default=False, description="是否启用悬浮球模式")

class EmblaPortalConfig(BaseModel):
    """Embla 门户账户配置。"""

    portal_url: str = Field(default="", description="Embla 门户地址")
    username: str = Field(default="", description="Embla 门户用户名")
    password: str = Field(default="", description="Embla 门户密码")
    request_timeout: int = Field(default=30, ge=5, le=120, description="请求超时时间（秒）")
    login_path: str = Field(default="/api/user/login", description="登录API路径")
    turnstile_param: str = Field(default="", description="Turnstile验证参数")
    login_username_key: str = Field(default="username", description="登录请求中用户名的键名")
    login_password_key: str = Field(default="password", description="登录请求中密码的键名")
    login_payload_mode: str = Field(default="json", description="登录请求载荷模式：json或form")
    default_headers: Dict[str, str] = Field(
        default={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Content-Type": "application/json",
        },
        description="默认HTTP请求头",
    )


class OnlineSearchConfig(BaseModel):
    """在线搜索配置"""

    searxng_url: str = Field(default="http://localhost:8080", description="SearXNG实例URL")
    engines: List[str] = Field(default=["google"], description="默认搜索引擎列表")
    num_results: int = Field(default=5, ge=1, le=20, description="搜索结果数量")


class Crawl4AIConfig(BaseModel):
    """网页抓取配置"""

    headless: bool = Field(default=True, description="抓取时是否使用无头模式（保留字段）")
    timeout: int = Field(default=30000, ge=1000, le=300000, description="抓取超时时间（毫秒）")
    user_agent: str = Field(
        default=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        ),
        description="抓取请求默认 User-Agent",
    )
    viewport_width: int = Field(default=1280, ge=320, le=8192, description="默认视口宽度")
    viewport_height: int = Field(default=720, ge=240, le=8192, description="默认视口高度")


class SystemCheckConfig(BaseModel):
    """系统检测状态配置"""

    passed: bool = Field(default=False, description="系统检测是否通过")
    timestamp: str = Field(default="", description="检测时间戳")
    python_version: str = Field(default="", description="Python版本")
    project_path: str = Field(default="", description="项目路径")


# 提示词管理功能已集成到config.py中


def get_prompt_assets_root(prompts_dir: str | Path | None = None) -> Path:
    """Return the effective prompt asset root.

    Resolution order:
      1. Explicit `prompts_dir`
      2. Canonical system prompt root
    """
    return _resolve_prompts_dir(Path(prompts_dir) if prompts_dir is not None else None)


def resolve_prompt_template_path(name: str, *, prompts_dir: str | Path | None = None) -> Path:
    resolved_prompts_dir = get_prompt_assets_root(prompts_dir)
    resolved = resolve_prompt_registry_entry(prompt_name=name, prompts_dir=resolved_prompts_dir)
    return Path(resolved["path"])


def read_prompt_template(name: str, *, prompts_dir: str | Path | None = None) -> Optional[str]:
    prompt_file = resolve_prompt_template_path(name, prompts_dir=prompts_dir)
    if not prompt_file.exists():
        return None
    return prompt_file.read_text(encoding="utf-8")


def write_prompt_template(name: str, content: str, *, prompts_dir: str | Path | None = None) -> Dict[str, Any]:
    resolved_prompts_dir = get_prompt_assets_root(prompts_dir)
    resolved = resolve_prompt_registry_entry(prompt_name=name, prompts_dir=resolved_prompts_dir)
    prompt_file = Path(resolved["path"])
    prompt_file.parent.mkdir(parents=True, exist_ok=True)
    prompt_file.write_text(content, encoding="utf-8")
    return {
        "canonical_name": str(resolved["canonical_name"]),
        "prompt_file": prompt_file,
        "relative_path": str(resolved["relative_path"]),
    }


def _resolve_prompts_dir(prompts_dir: Optional[Path] = None) -> Path:
    if prompts_dir is not None:
        return Path(prompts_dir)
    return get_system_prompts_root()


_DEFAULT_PROMPT_REGISTRY_SPEC: Dict[str, Any] = {
    "schema_version": "ws28-prompt-registry-v1",
    "entries": [
        {"prompt_name": "shell_persona", "path": "dna/shell_persona.md", "aliases": []},
        {"prompt_name": "core_values", "path": "dna/core_values.md", "aliases": []},
        {"prompt_name": "conversation_style_prompt", "path": "core/dna/conversation_style_prompt.md", "aliases": ["conversation_composition_prompt"]},
        {"prompt_name": "conversation_analyzer_prompt", "path": "core/routing/conversation_analyzer_prompt.md", "aliases": []},
        {"prompt_name": "tool_dispatch_prompt", "path": "core/routing/tool_dispatch_prompt.md", "aliases": []},
        {"prompt_name": "agentic_tool_prompt", "path": "core/dna/agentic_tool_prompt.md", "aliases": ["tool_call_contract_prompt"]},
        {"prompt_name": "immutable_dna_manifest", "path": "immutable_dna_manifest.spec", "aliases": ["immutable_dna_manifest_spec"]},
        {"prompt_name": "prompt_acl", "path": "specs/prompt_acl.spec", "aliases": []},
        {"prompt_name": "core_exec_base", "path": "agents/core_exec/core_exec_base.md", "aliases": ["core_exec_general"]},
        {"prompt_name": "core_exec_ops", "path": "agents/core_exec/core_exec_ops.md", "aliases": []},
        {"prompt_name": "core_exec_dev", "path": "agents/core_exec/core_exec_dev.md", "aliases": []},
        {"prompt_name": "shell_readonly_research", "path": "agents/shell/shell_readonly_research.md", "aliases": []},
        {"prompt_name": "shell_readonly_general", "path": "agents/shell/shell_readonly_general.md", "aliases": []},
        {"prompt_name": "explicit_role_delegate", "path": "agents/shell/explicit_role_delegate.md", "aliases": []},
        {"prompt_name": "shell_behavior_readonly_tools", "path": "agents/shell/blocks/shell_behavior_readonly_tools.md", "aliases": []},
        {"prompt_name": "shell_behavior_dispatch_to_core", "path": "agents/shell/blocks/shell_behavior_dispatch_to_core.md", "aliases": []},
        {"prompt_name": "shell_behavior_no_writes", "path": "agents/shell/blocks/shell_behavior_no_writes.md", "aliases": []},
        {"prompt_name": "shell_route_decision_base", "path": "agents/shell/blocks/shell_route_decision_base.md", "aliases": []},
        {"prompt_name": "shell_route_quality_guard", "path": "agents/shell/blocks/shell_route_quality_guard.md", "aliases": []},
        {"prompt_name": "shell_router_arbiter_guard", "path": "agents/shell/blocks/shell_router_arbiter_guard.md", "aliases": []},
        {"prompt_name": "shell_route_policy_readonly", "path": "agents/shell/blocks/shell_route_policy_readonly.md", "aliases": []},
        {"prompt_name": "shell_route_policy_clarify", "path": "agents/shell/blocks/shell_route_policy_clarify.md", "aliases": []},
        {"prompt_name": "shell_route_policy_core_execution", "path": "agents/shell/blocks/shell_route_policy_core_execution.md", "aliases": []},
        {"prompt_name": "core_orchestrator_duties", "path": "agents/core_exec/blocks/core_orchestrator_duties.md", "aliases": []},
        {"prompt_name": "core_lifecycle_orchestrator", "path": "agents/core_exec/blocks/core_lifecycle_orchestrator.md", "aliases": []},
        {"prompt_name": "dev_agent_behavior", "path": "agents/dev/dev_agent_behavior.md", "aliases": []},
        {"prompt_name": "dev_agent_self_verification", "path": "agents/dev/dev_agent_self_verification.md", "aliases": []},
        {"prompt_name": "review_agent_behavior", "path": "agents/review/review_agent_behavior.md", "aliases": []},
        {"prompt_name": "review_result_contract", "path": "agents/review/review_result_contract.md", "aliases": []},
        {"prompt_name": "quintuple_extractor_structured_system", "path": "memory/quintuple_extractor_structured_system.md", "aliases": []},
        {"prompt_name": "quintuple_extractor_structured_user", "path": "memory/quintuple_extractor_structured_user.md", "aliases": []},
        {"prompt_name": "quintuple_extractor_json_fallback", "path": "memory/quintuple_extractor_json_fallback.md", "aliases": []},
        {"prompt_name": "quintuple_rag_keyword_prompt", "path": "memory/quintuple_rag_keyword_prompt.md", "aliases": []},
        {"prompt_name": "quintuple_rag_keyword_prompt_ollama", "path": "memory/quintuple_rag_keyword_prompt_ollama.md", "aliases": []},
        {"prompt_name": "backend_expert", "path": "roles/backend_expert.md", "aliases": []},
        {"prompt_name": "frontend_expert", "path": "roles/frontend_expert.md", "aliases": []},
        {"prompt_name": "ops_expert", "path": "roles/ops_expert.md", "aliases": []},
        {"prompt_name": "testing_expert", "path": "roles/testing_expert.md", "aliases": []},
        {"prompt_name": "docs_expert", "path": "roles/docs_expert.md", "aliases": []},
        {"prompt_name": "file_analysis", "path": "skills/file_analysis.md", "aliases": []},
        {"prompt_name": "python_ast", "path": "skills/python_ast.md", "aliases": []},
        {"prompt_name": "skill_activation_wrapper", "path": "skills/skill_activation_wrapper.md", "aliases": []},
        {"prompt_name": "code_with_tests", "path": "styles/code_with_tests.md", "aliases": []},
        {"prompt_name": "conventional_commit", "path": "rules/conventional_commit.md", "aliases": []},
    ],
}


def _normalize_prompt_registry_name(name: str) -> str:
    normalized = str(name or "").strip()
    lower = normalized.lower()
    if lower.endswith(".md"):
        return normalized[:-3]
    if lower.endswith(".spec"):
        return normalized[:-5]
    return normalized


def _normalize_prompt_registry_entry(raw: Dict[str, Any]) -> Dict[str, Any]:
    prompt_name = _normalize_prompt_registry_name(str(raw.get("prompt_name") or raw.get("name") or ""))
    if not prompt_name:
        return {}

    relative_path = str(raw.get("path") or "").strip()
    if not relative_path:
        relative_path = f"{prompt_name}.md"

    aliases: List[str] = []
    alias_rows = raw.get("aliases")
    if isinstance(alias_rows, list):
        for alias_raw in alias_rows:
            alias = _normalize_prompt_registry_name(str(alias_raw or ""))
            if not alias or alias == prompt_name or alias in aliases:
                continue
            aliases.append(alias)

    return {
        "prompt_name": prompt_name,
        "path": relative_path.replace("\\", "/"),
        "aliases": aliases,
    }


def load_prompt_registry_spec(*, prompts_dir: Optional[Path] = None) -> Dict[str, Any]:
    resolved_prompts_dir = _resolve_prompts_dir(prompts_dir)
    candidate_paths = [
        resolved_prompts_dir / "specs" / "prompt_registry.spec",
    ]

    payload: Dict[str, Any] = {}
    selected_source = ""
    for candidate in candidate_paths:
        if not candidate.exists():
            continue
        try:
            loaded = json5.loads(candidate.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                payload = loaded
                selected_source = str(candidate).replace("\\", "/")
                break
        except Exception as e:
            logger.warning("load prompt_registry.spec failed: %s", e)

    if not payload:
        payload = dict(_DEFAULT_PROMPT_REGISTRY_SPEC)
        selected_source = "default"

    raw_entries = payload.get("entries")
    normalized_entries: List[Dict[str, Any]] = []
    if isinstance(raw_entries, list):
        for raw in raw_entries:
            if not isinstance(raw, dict):
                continue
            normalized = _normalize_prompt_registry_entry(raw)
            if normalized:
                normalized_entries.append(normalized)

    if not normalized_entries:
        normalized_entries = list(_DEFAULT_PROMPT_REGISTRY_SPEC["entries"])

    entries_map: Dict[str, Dict[str, Any]] = {}
    alias_to_name: Dict[str, str] = {}
    for entry in normalized_entries:
        prompt_name = str(entry["prompt_name"])
        if prompt_name in entries_map:
            continue
        entries_map[prompt_name] = entry
        alias_to_name[prompt_name] = prompt_name
        for alias in entry.get("aliases", []):
            alias_key = str(alias)
            if alias_key and alias_key not in alias_to_name:
                alias_to_name[alias_key] = prompt_name

    return {
        "schema_version": str(payload.get("schema_version") or "ws28-prompt-registry-v1"),
        "source": selected_source,
        "entries": normalized_entries,
        "entries_map": entries_map,
        "alias_to_name": alias_to_name,
    }


def resolve_prompt_registry_entry(*, prompt_name: str, prompts_dir: Optional[Path] = None) -> Dict[str, Any]:
    resolved_prompts_dir = _resolve_prompts_dir(prompts_dir)

    requested_name = _normalize_prompt_registry_name(str(prompt_name or ""))
    registry = load_prompt_registry_spec(prompts_dir=resolved_prompts_dir)
    alias_to_name = dict(registry.get("alias_to_name") or {})
    entries_map = dict(registry.get("entries_map") or {})

    canonical_name = alias_to_name.get(requested_name, requested_name)
    entry = entries_map.get(canonical_name)
    if entry is not None:
        relative_path = str(entry.get("path") or f"{canonical_name}.md")
        aliases = list(entry.get("aliases") or [])
    else:
        relative_path = f"{canonical_name}.md"
        aliases = []

    absolute_path = (resolved_prompts_dir / relative_path).resolve()
    return {
        "requested_name": requested_name,
        "canonical_name": canonical_name,
        "relative_path": relative_path.replace("\\", "/"),
        "filename": Path(relative_path).name,
        "aliases": aliases,
        "path": absolute_path,
    }


def resolve_prompt_file_reference(*, prompt_name: str, prompts_dir: Optional[Path] = None) -> str:
    resolved_prompts_dir = _resolve_prompts_dir(prompts_dir)
    raw_text = str(prompt_name or "").strip().replace("\\", "/")
    if not raw_text:
        return ""

    candidate_rows: List[str] = []

    def _add_candidate(candidate: str) -> None:
        normalized_candidate = str(candidate or "").strip().replace("\\", "/")
        if normalized_candidate and normalized_candidate not in candidate_rows:
            candidate_rows.append(normalized_candidate)

    try:
        resolved = resolve_prompt_registry_entry(prompt_name=raw_text, prompts_dir=resolved_prompts_dir)
        _add_candidate(str(resolved.get("relative_path") or ""))
        _add_candidate(str(resolved.get("filename") or ""))
    except Exception:
        logger.debug("resolve prompt file reference fallback: %s", raw_text, exc_info=True)

    canonical_name = _normalize_embla_prompt_name(raw_text, prompts_dir=resolved_prompts_dir)
    _add_candidate(raw_text)
    _add_candidate(canonical_name)
    if canonical_name and not canonical_name.lower().endswith(".md"):
        _add_candidate(f"{canonical_name}.md")

    for candidate in candidate_rows:
        candidate_path = (resolved_prompts_dir / candidate).resolve()
        if candidate_path.exists() and candidate_path.is_file():
            return candidate

    return candidate_rows[0] if candidate_rows else raw_text


_PROMPT_ACL_LEVELS = {"S0_LOCKED", "S1_CONTROLLED", "S2_FLEXIBLE"}

_DEFAULT_PROMPT_ACL_SPEC: Dict[str, Any] = {
    "enforcement_mode": "block",
    "rules": [
        {
            "path_pattern": "immutable_dna_manifest.spec",
            "level": "S0_LOCKED",
            "require_ticket": True,
            "require_manifest_refresh": True,
            "require_gate_verify": True,
            "allow_ai_direct_write": False,
        },
        {
            "path_pattern": "dna/shell_persona.md",
            "level": "S1_CONTROLLED",
            "require_ticket": True,
            "require_manifest_refresh": True,
            "require_gate_verify": True,
            "allow_ai_direct_write": False,
        },
        {
            "path_pattern": "dna/core_values.md",
            "level": "S1_CONTROLLED",
            "require_ticket": True,
            "require_manifest_refresh": True,
            "require_gate_verify": True,
            "allow_ai_direct_write": False,
        },
        {
            "path_pattern": "core/dna/conversation_style_prompt.md",
            "level": "S1_CONTROLLED",
            "require_ticket": True,
            "require_manifest_refresh": True,
            "require_gate_verify": True,
            "allow_ai_direct_write": False,
        },
        {
            "path_pattern": "core/routing/conversation_analyzer_prompt.md",
            "level": "S2_FLEXIBLE",
            "require_ticket": False,
            "require_manifest_refresh": False,
            "require_gate_verify": False,
            "allow_ai_direct_write": True,
        },
        {
            "path_pattern": "core/routing/tool_dispatch_prompt.md",
            "level": "S2_FLEXIBLE",
            "require_ticket": False,
            "require_manifest_refresh": False,
            "require_gate_verify": False,
            "allow_ai_direct_write": True,
        },
        {
            "path_pattern": "core/dna/agentic_tool_prompt.md",
            "level": "S1_CONTROLLED",
            "require_ticket": True,
            "require_manifest_refresh": True,
            "require_gate_verify": True,
            "allow_ai_direct_write": False,
        },
        {
            "path_pattern": "*.md",
            "level": "S2_FLEXIBLE",
            "require_ticket": False,
            "require_manifest_refresh": False,
            "require_gate_verify": False,
            "allow_ai_direct_write": True,
        },
    ],
}


def _normalize_prompt_acl_level(level: str) -> str:
    normalized = str(level or "").strip().upper()
    if normalized in _PROMPT_ACL_LEVELS:
        return normalized
    return "S2_FLEXIBLE"


def _normalize_prompt_acl_rule(raw: Dict[str, Any]) -> Dict[str, Any]:
    path_pattern = str(raw.get("path_pattern") or "").strip()
    if not path_pattern:
        return {}
    return {
        "path_pattern": path_pattern,
        "level": _normalize_prompt_acl_level(str(raw.get("level") or "S2_FLEXIBLE")),
        "require_ticket": bool(raw.get("require_ticket")),
        "require_manifest_refresh": bool(raw.get("require_manifest_refresh")),
        "require_gate_verify": bool(raw.get("require_gate_verify")),
        "allow_ai_direct_write": bool(raw.get("allow_ai_direct_write", True)),
    }


def load_prompt_acl_spec(*, prompts_dir: Optional[Path] = None) -> Dict[str, Any]:
    resolved_prompts_dir = _resolve_prompts_dir(prompts_dir)
    candidate_paths = [
        resolved_prompts_dir / "specs" / "prompt_acl.spec",
    ]
    payload: Dict[str, Any] = {}
    for spec_path in candidate_paths:
        if not spec_path.exists():
            continue
        try:
            loaded = json5.loads(spec_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                payload = loaded
                break
        except Exception as e:
            logger.warning("load prompt_acl.spec failed: %s", e)

    if not payload:
        return dict(_DEFAULT_PROMPT_ACL_SPEC)

    rules = []
    for raw in payload.get("rules", []) if isinstance(payload.get("rules"), list) else []:
        if not isinstance(raw, dict):
            continue
        normalized = _normalize_prompt_acl_rule(raw)
        if normalized:
            rules.append(normalized)

    if not rules:
        rules = list(_DEFAULT_PROMPT_ACL_SPEC["rules"])

    enforcement_mode = str(payload.get("enforcement_mode") or "block").strip().lower()
    if enforcement_mode not in {"shadow", "block"}:
        enforcement_mode = "block"
    return {
        "enforcement_mode": enforcement_mode,
        "rules": rules,
    }


def evaluate_prompt_acl(
    *,
    prompt_name: str,
    prompts_dir: Optional[Path] = None,
    approval_ticket: str = "",
    change_reason: str = "",
    enforcement_mode_override: str = "",
) -> Dict[str, Any]:
    requested_name = _normalize_prompt_registry_name(str(prompt_name or ""))
    resolved = resolve_prompt_registry_entry(prompt_name=requested_name, prompts_dir=prompts_dir)
    canonical_name = str(resolved["canonical_name"])
    filename = str(resolved["filename"])
    relative_path = str(resolved["relative_path"])

    spec = load_prompt_acl_spec(prompts_dir=prompts_dir)
    rules = list(spec.get("rules", [])) if isinstance(spec.get("rules"), list) else []
    matched_rule = {
        "path_pattern": "*.md",
        "level": "S2_FLEXIBLE",
        "require_ticket": False,
        "require_manifest_refresh": False,
        "require_gate_verify": False,
        "allow_ai_direct_write": True,
    }
    for rule in rules:
        path_pattern = str(rule.get("path_pattern") or "").strip()
        if path_pattern and (
            fnmatch.fnmatch(filename, path_pattern) or fnmatch.fnmatch(relative_path, path_pattern)
        ):
            matched_rule = {
                "path_pattern": path_pattern,
                "level": _normalize_prompt_acl_level(str(rule.get("level") or "S2_FLEXIBLE")),
                "require_ticket": bool(rule.get("require_ticket")),
                "require_manifest_refresh": bool(rule.get("require_manifest_refresh")),
                "require_gate_verify": bool(rule.get("require_gate_verify")),
                "allow_ai_direct_write": bool(rule.get("allow_ai_direct_write", True)),
            }
            break

    enforcement_mode = str(enforcement_mode_override or spec.get("enforcement_mode") or "block").strip().lower()
    if enforcement_mode not in {"shadow", "block"}:
        enforcement_mode = "block"

    approval_text = str(approval_ticket or "").strip()
    reason_text = str(change_reason or "").strip()
    level = str(matched_rule["level"])
    blocked = False
    reason_code = "OK"
    reason = "allowed"

    if level == "S0_LOCKED":
        blocked = True
        reason_code = "PROMPT_ACL_S0_LOCKED"
        reason = "S0_LOCKED prompt cannot be updated via API"
    elif bool(matched_rule["require_ticket"]) and not approval_text:
        blocked = True
        reason_code = "PROMPT_ACL_APPROVAL_TICKET_REQUIRED"
        reason = "approval_ticket is required for this prompt"
    elif level == "S1_CONTROLLED" and not reason_text:
        blocked = True
        reason_code = "PROMPT_ACL_CHANGE_REASON_REQUIRED"
        reason = "change_reason is required for S1_CONTROLLED prompt"

    shadow_blocked = bool(blocked and enforcement_mode == "shadow")
    return {
        "prompt_name": canonical_name,
        "requested_prompt_name": requested_name,
        "filename": filename,
        "relative_path": relative_path,
        "enforcement_mode": enforcement_mode,
        "matched_rule": matched_rule,
        "approval_ticket_present": bool(approval_text),
        "change_reason_present": bool(reason_text),
        "blocked": bool(blocked and enforcement_mode == "block"),
        "shadow_blocked": shadow_blocked,
        "allowed": not bool(blocked and enforcement_mode == "block"),
        "reason_code": reason_code,
        "reason": reason,
    }


def build_system_prompt(
    include_skills: bool = True,
    include_tool_instructions: bool = False, skill_name: Optional[str] = None,
) -> str:
    """
    构建完整的系统提示词

    将基础对话风格提示词与技能元数据组合。
    所有动态内容统一放在「附加知识」分隔符之后，便于后续扩展。

    Args:
        include_skills: 是否包含技能列表
        include_tool_instructions: 是否注入工具调用指令（agentic loop 模式）
        skill_name: 用户主动选择的技能名称，直接注入完整指令

    Returns:
        完整的系统提示词
    """
    parts: List[str] = []
    prompts_dir = _resolve_prompts_dir()
    assembler = PromptAssembler(prompts_root=str(prompts_dir))
    for prompt_name in ("shell_persona", "conversation_style_prompt", "shell_readonly_general"):
        try:
            resolved = resolve_prompt_registry_entry(prompt_name=prompt_name, prompts_dir=prompts_dir)
            rendered = assembler.render_block(str(resolved["relative_path"]), variables={"ai_name": config.system.ai_name}).strip()
            if rendered:
                parts.append(rendered)
        except PromptBlockNotFoundError:
            logging.getLogger(__name__).warning("prompt missing while building shell system prompt: %s", prompt_name)

    # ━━━ 附加知识分隔符 ━━━
    parts.append("\n\n━━━━━━━━━━ 以下是附加知识 ━━━━━━━━━━\n")

    # 始终添加时间信息（最先出现）
    current_time = datetime.now()
    time_info = (
        f"\n【当前时间信息】\n"
        f"当前日期：{current_time.strftime('%Y年%m月%d日')}\n"
        f"当前时间：{current_time.strftime('%H:%M:%S')}\n"
        f"当前星期：{current_time.strftime('%A')}"
    )
    parts.append(time_info)

    # 技能元数据列表（仅在未主动选择技能时注入）
    if not skill_name and include_skills:
        try:
            from system.skill_manager import get_skills_prompt

            skills_prompt = get_skills_prompt()
            if skills_prompt:
                parts.append("\n\n" + skills_prompt)
        except ImportError:
            pass  # 技能管理器不可用时忽略

    # 添加工具调用指令（不可被前端编辑，通过代码注入）
    if include_tool_instructions:
        try:
            resolved = resolve_prompt_registry_entry(prompt_name="agentic_tool_prompt", prompts_dir=prompts_dir)
            tool_prompt = assembler.render_block(
                str(resolved["relative_path"]),
                variables={"available_mcp_tools": get_available_mcp_tools_summary()},
            ).strip()
            if tool_prompt:
                parts.append("\n\n" + tool_prompt)
        except PromptBlockNotFoundError:
            logging.getLogger(__name__).warning("prompt missing while building tool instruction prompt: agentic_tool_prompt")

    # 指定技能的完整指令放在系统提示词末尾，确保最高优先级
    # LLM 对 system prompt 末尾指令的遵循度最高，避免被工具调用等大段内容"淹没"
    if skill_name:
        try:
            from system.skill_manager import load_skill

            skill_instructions = load_skill(skill_name)
            if skill_instructions:
                resolved = resolve_prompt_registry_entry(prompt_name="skill_activation_wrapper", prompts_dir=prompts_dir)
                parts.append(
                    "\n\n"
                    + assembler.render_block(
                        str(resolved["relative_path"]),
                        variables={"skill_name": skill_name, "skill_instructions": skill_instructions},
                    ).strip()
                )
        except ImportError:
            pass

    # 注意：收尾指令不在此处添加，由 api_server.py 在 RAG 记忆注入之后追加
    return "".join(parts)


def build_system_prompt_for_route_semantic(
    route_semantic: str,
    *,
    include_skills: bool = True,
    skill_name: Optional[str] = None,
) -> str:
    """
    按路由语义构建裁剪后的系统提示词。

    - shell_readonly: Shell 只读 — 完整对话风格 + 技能元数据；不注入通用 agentic tool DNA，但会注入只读工具曝光口径
    - shell_clarify: Shell 澄清 — 完整对话风格 + 技能元数据；不注入通用 agentic tool DNA
    - core_execution: Core 执行 — 使用精简 core_exec_base + 工具指令，不注入闲聊风格

    异常时降级到原始 build_system_prompt()。
    """
    normalized_route_semantic = str(route_semantic or "core_execution").strip().lower()
    try:
        prompts_dir = _resolve_prompts_dir()
        assembler = PromptAssembler(prompts_root=str(prompts_dir))
        if normalized_route_semantic in {"shell_readonly", "shell_clarify"}:
            shell_parts: List[str] = []
            for prompt_name in ("shell_persona", "conversation_style_prompt"):
                resolved = resolve_prompt_registry_entry(prompt_name=prompt_name, prompts_dir=prompts_dir)
                rendered = assembler.render_block(str(resolved["relative_path"]), variables={"ai_name": config.system.ai_name}).strip()
                if rendered:
                    shell_parts.append(rendered)
            shell_runtime_blocks = [
                "agents/shell/blocks/shell_behavior_readonly_tools.md",
                "agents/shell/blocks/shell_behavior_dispatch_to_core.md",
                "agents/shell/blocks/shell_behavior_no_writes.md",
            ]
            if normalized_route_semantic == "shell_clarify":
                shell_runtime_blocks.append("agents/shell/blocks/shell_route_policy_clarify.md")
            else:
                shell_runtime_blocks.append("agents/shell/blocks/shell_route_policy_readonly.md")
            shell_runtime = assembler.assemble(blocks=shell_runtime_blocks)
            if shell_runtime.strip():
                shell_parts.append(shell_runtime.strip())
            base_prompt = "\n\n".join(shell_parts).strip()
            parts = [base_prompt]
            parts.append("\n\n━━━━━━━━━━ 以下是附加知识 ━━━━━━━━━━\n")
            current_time = datetime.now()
            time_info = (
                f"\n【当前时间信息】\n"
                f"当前日期：{current_time.strftime('%Y年%m月%d日')}\n"
                f"当前时间：{current_time.strftime('%H:%M:%S')}\n"
                f"当前星期：{current_time.strftime('%A')}"
            )
            parts.append(time_info)
            if not skill_name and include_skills:
                try:
                    from system.skill_manager import get_skills_prompt

                    skills_prompt = get_skills_prompt()
                    if skills_prompt:
                        parts.append("\n\n" + skills_prompt)
                except ImportError:
                    pass
            if skill_name:
                try:
                    from system.skill_manager import load_skill

                    skill_instructions = load_skill(skill_name)
                    if skill_instructions:
                        resolved = resolve_prompt_registry_entry(prompt_name="skill_activation_wrapper", prompts_dir=prompts_dir)
                        parts.append(
                            "\n\n"
                            + assembler.render_block(
                                str(resolved["relative_path"]),
                                variables={"skill_name": skill_name, "skill_instructions": skill_instructions},
                            ).strip()
                        )
                except ImportError:
                    pass
            return "".join(parts)

        # core_execution: Core 执行路径
        core_parts: List[str] = []
        for prompt_name in ("core_values",):
            resolved = resolve_prompt_registry_entry(prompt_name=prompt_name, prompts_dir=prompts_dir)
            rendered = assembler.render_block(str(resolved["relative_path"]), variables={"ai_name": config.system.ai_name}).strip()
            if rendered:
                core_parts.append(rendered)
        core_runtime = assembler.assemble(
            blocks=[
                "agents/core_exec/core_exec_base.md",
                "agents/core_exec/blocks/core_orchestrator_duties.md",
            ]
        ).strip()
        if core_runtime:
            core_parts.append(core_runtime)
        resolved_tool = resolve_prompt_registry_entry(prompt_name="agentic_tool_prompt", prompts_dir=prompts_dir)
        tool_prompt = assembler.render_block(
            str(resolved_tool["relative_path"]),
            variables={"available_mcp_tools": get_available_mcp_tools_summary()},
        ).strip()
        if tool_prompt:
            core_parts.append(tool_prompt)

        parts = ["\n\n".join(part for part in core_parts if part).strip()]

        # 附加知识分隔符
        parts.append("\n\n━━━━━━━━━━ 以下是附加知识 ━━━━━━━━━━\n")

        # 时间信息（所有路径都需要）
        current_time = datetime.now()
        time_info = (
            f"\n【当前时间信息】\n"
            f"当前日期：{current_time.strftime('%Y年%m月%d日')}\n"
            f"当前时间：{current_time.strftime('%H:%M:%S')}\n"
            f"当前星期：{current_time.strftime('%A')}"
        )
        parts.append(time_info)

        return "".join(parts)

    except Exception as exc:
        logging.getLogger(__name__).warning(
            "build_system_prompt_for_route_semantic(%s) 降级到 build_system_prompt: %s", route_semantic, exc
        )
        return build_system_prompt(
            include_skills=include_skills,
            include_tool_instructions=(normalized_route_semantic == "core_execution"),
            skill_name=skill_name,
        )


class EmblaSystemConfig(BaseModel):
    """Embla System 主配置类。"""

    system: SystemConfig = Field(default_factory=SystemConfig)
    api: APIConfig = Field(default_factory=APIConfig)
    api_server: APIServerConfig = Field(default_factory=APIServerConfig)
    grag: GRAGConfig = Field(default_factory=GRAGConfig)
    handoff: HandoffConfig = Field(default_factory=HandoffConfig)
    agentic_loop: AgenticLoopConfig = Field(default_factory=AgenticLoopConfig)
    tool_contract_rollout: ToolContractRolloutConfig = Field(default_factory=ToolContractRolloutConfig)
    autonomous: AutonomousConfig = Field(default_factory=AutonomousConfig)
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)
    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    filter: FilterConfig = Field(default_factory=FilterConfig)
    difficulty: DifficultyConfig = Field(default_factory=DifficultyConfig)
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)
    # prompts: 提示词配置已迁移到 system/prompt_repository.py
    # weather: 天气服务使用免费API，无需配置
    mqtt: MQTTConfig = Field(default_factory=MQTTConfig)
    ui: UIConfig = Field(default_factory=UIConfig)
    floating: FloatingConfig = Field(default_factory=FloatingConfig)
    embla_portal: EmblaPortalConfig = Field(default_factory=EmblaPortalConfig)
    online_search: OnlineSearchConfig = Field(default_factory=OnlineSearchConfig)
    crawl4ai: Crawl4AIConfig = Field(default_factory=Crawl4AIConfig)
    system_check: SystemCheckConfig = Field(default_factory=SystemCheckConfig)
    computer_control: ComputerControlConfig = Field(default_factory=ComputerControlConfig)
    memory_server: MemoryServerConfig = Field(default_factory=MemoryServerConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    window: Any = Field(default=None)

    model_config = {
        "extra": "ignore",  # 保留原配置：忽略未定义的字段
        "json_schema_extra": {
            "exclude": ["window"]  # 序列化到 config.json 时排除 window 字段（避免报错）
        },
    }

    def __init__(self, **kwargs):
        setup_environment()
        super().__init__(**kwargs)
        self.system.log_dir.mkdir(parents=True, exist_ok=True)  # 确保递归创建日志目录


# 全局配置实例


def load_config():
    """加载配置"""
    _refresh_embla_system_config()
    config_path = str(Path(__file__).parent.parent / "config.json")

    bootstrap_config_from_example(config_path)

    if os.path.exists(config_path):
        try:
            # 使用Charset Normalizer自动检测编码
            charset_results = from_path(config_path)
            if charset_results:
                best_match = charset_results.best()
                if best_match:
                    detected_encoding = best_match.encoding
                    logger.debug("detected config encoding: %s (%s)", detected_encoding, config_path)

                    # 使用检测到的编码直接打开文件，然后使用json5读取
                    with open(config_path, "r", encoding=detected_encoding) as f:
                        # 使用json5解析支持注释的JSON
                        try:
                            config_data = normalize_runtime_config_payload(json5.load(f))
                        except Exception as json5_error:
                            logger.warning("json5 parse failed for %s: %s", config_path, json5_error)
                            logger.info("falling back to standard JSON parsing after stripping comments")
                            # 回退到标准JSON库，但需要先去除注释
                            f.seek(0)  # 重置文件指针
                            content = f.read()
                            # 去除注释行
                            lines = content.split("\n")
                            cleaned_lines = []
                            for line in lines:
                                # 移除行内注释（#后面的内容）
                                if "#" in line:
                                    line = line.split("#")[0].rstrip()
                                if line.strip():  # 只保留非空行
                                    cleaned_lines.append(line)
                            cleaned_content = "\n".join(cleaned_lines)
                            config_data = normalize_runtime_config_payload(json.loads(cleaned_content))
                    config_data = normalize_runtime_config_payload(config_data)
                    _sync_server_ports_from_config_data(config_data)
                    return EmblaSystemConfig(**config_data)
                else:
                    logger.warning("unable to detect encoding for %s", config_path)
            else:
                logger.warning("unable to detect encoding for %s", config_path)

            # 如果自动检测失败，回退到原来的方法
            logger.info("loading config via utf-8 fallback path")
            with open(config_path, "r", encoding="utf-8") as f:
                # 使用json5解析支持注释的JSON
                config_data = normalize_runtime_config_payload(json5.load(f))
            _sync_server_ports_from_config_data(config_data)
            return EmblaSystemConfig(**config_data)

        except Exception as exc:
            logger.warning("load config failed %s: %s", config_path, exc)
            logger.info("falling back to default config")
            return EmblaSystemConfig()
    else:
        logger.warning("config file missing %s, using defaults", config_path)

    return EmblaSystemConfig()


config = load_config()


def reload_config() -> EmblaSystemConfig:
    """重新加载配置"""
    global config
    config = load_config()
    notify_config_changed()
    return config


def hot_reload_config() -> EmblaSystemConfig:
    """热更新配置 - 重新加载配置并通知所有模块"""
    global config
    old_config = config
    config = load_config()
    notify_config_changed()
    logger.info("config hot reloaded: %s -> %s", old_config.system.version, config.system.version)
    return config


def get_config() -> EmblaSystemConfig:
    """获取当前配置"""
    return config


# 初始化时打印配置信息
if config.system.debug:
    logger.info("Embla System %s config loaded", config.system.version)
    logger.info(
        "API server: %s (%s:%s)",
        "enabled" if config.api_server.enabled else "disabled",
        config.api_server.host,
        config.api_server.port,
    )
    logger.info("GRAG memory: %s", "enabled" if config.grag.enabled else "disabled")

# 启动时设置用户显示名：优先config.json，其次系统用户名 #
try:
    # 检查 config.json 中的 user_name 是否为空白或未填写
    if not config.ui.user_name or not config.ui.user_name.strip():
        # 如果是，则尝试获取系统登录用户名并覆盖
        config.ui.user_name = os.getlogin()
except Exception:
    # 获取系统用户名失败时，将保留默认值 "用户" 或 config.json 中的空值
    pass

# 向后兼容的AI_NAME常量
AI_NAME = config.system.ai_name

logger = logging.getLogger(__name__)
