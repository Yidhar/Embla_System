#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenClaw 配置自动生成 + LLM 桥接

当 ~/.openclaw/openclaw.json 不存在时，自动生成最小可用配置，
并注入 Naga 的 LLM 设置（api_key / base_url / model）。
不再依赖 `openclaw onboard` 命令。
"""

import json
import logging
import secrets
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

OPENCLAW_CONFIG_DIR = Path.home() / ".openclaw"
OPENCLAW_CONFIG_FILE = OPENCLAW_CONFIG_DIR / "openclaw.json"


def _normalize_google_openai_base_url(raw_base_url: str) -> str:
    """
    OpenClaw 的 `openai-completions` 需要 OpenAI 兼容的 baseUrl。

    Gemini 的 OpenAI 兼容接口通常挂在 `/openai` 下，例如：
      - https://generativelanguage.googleapis.com/v1beta/openai

    用户有时会把原生 Gemini endpoint（`.../models/<id>:generateContent`）误填成 baseUrl，
    这会导致 OpenClaw 继续拼接 `/chat/completions`，最终变成 404。
    """
    base = (raw_base_url or "").strip().rstrip("/")
    if not base:
        return base

    # Strip accidental full native endpoints.
    models_idx = base.find("/models/")
    if models_idx != -1:
        base = base[:models_idx]

    # Normalize any existing /openai suffix.
    openai_idx = base.find("/openai")
    if openai_idx != -1:
        base = base[:openai_idx]

    return f"{base}/openai"


def _normalize_google_native_base_url(raw_base_url: str) -> str:
    """
    OpenClaw 的 `google-generative-ai` 需要原生 Gemini baseUrl。

    期望形态:
      - https://generativelanguage.googleapis.com/v1beta

    兼容用户误填的情况:
      - .../models/<id>:generateContent
      - .../openai
    """
    base = (raw_base_url or "").strip()
    if not base:
        return "https://generativelanguage.googleapis.com/v1beta"

    # Strip query/fragment and trailing slash.
    base = base.split("?", 1)[0].split("#", 1)[0].rstrip("/")

    # Strip accidental full native endpoints.
    models_idx = base.find("/models/")
    if models_idx != -1:
        base = base[:models_idx]

    # Strip OpenAI compatibility layer.
    openai_idx = base.find("/openai")
    if openai_idx != -1:
        base = base[:openai_idx]

    parsed = urlparse(base if "://" in base else f"https://{base}")
    scheme = parsed.scheme or "https"
    host = parsed.netloc or "generativelanguage.googleapis.com"
    path = (parsed.path or "").rstrip("/")
    lowered = path.lower()

    version_path = "/v1beta"
    if "/v1alpha" in lowered:
        version_path = "/v1alpha"
    elif "/v1beta" in lowered:
        version_path = "/v1beta"
    elif "/v1/" in lowered or lowered.endswith("/v1"):
        version_path = "/v1"

    return f"{scheme}://{host}{version_path}"


def _resolve_openclaw_provider_config(naga_api_cfg) -> tuple[str, str]:
    """
    根据 Naga 的 API 配置，推导 OpenClaw 侧可用的 (model_api, base_url)。
    """
    raw_base_url = getattr(naga_api_cfg, "base_url", "") or ""
    provider = (getattr(naga_api_cfg, "provider", "") or "").strip().lower()

    # Default: treat as OpenAI-compatible Chat Completions.
    model_api = "openai-completions"
    base_url = raw_base_url.strip().rstrip("/")

    # Gemini: prefer OpenClaw native API for better tool-calling compatibility.
    if provider in ("google", "gemini") or "generativelanguage.googleapis.com" in base_url:
        base_url = _normalize_google_native_base_url(base_url)
        model_api = "google-generative-ai"

    return model_api, base_url


def ensure_openclaw_config() -> bool:
    """
    确保 openclaw.json 存在，不存在则自动生成最小可用配置。

    Returns:
        是否成功（已存在或新建成功）
    """
    if OPENCLAW_CONFIG_FILE.exists():
        logger.debug("openclaw.json 已存在，跳过生成")
        return True

    try:
        OPENCLAW_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

        gateway_token = secrets.token_hex(32)
        hooks_token = secrets.token_hex(32)

        minimal_config = {
            "gateway": {
                "mode": "local",
                "port": 18789,
                "bind": "loopback",
                "auth": {"mode": "token", "token": gateway_token},
            },
            "hooks": {
                "enabled": True,
                "token": hooks_token,
                "allowRequestSessionKey": True,
            },
            "tools": {"allow": ["*"]},
            "agents": {
                "defaults": {
                    "workspace": str(OPENCLAW_CONFIG_DIR / "workspace"),
                    "maxConcurrent": 4,
                }
            },
        }

        OPENCLAW_CONFIG_FILE.write_text(
            json.dumps(minimal_config, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info(f"已自动生成 openclaw.json: {OPENCLAW_CONFIG_FILE}")
        return True

    except Exception as e:
        logger.error(f"自动生成 openclaw.json 失败: {e}")
        return False


def inject_naga_llm_config() -> bool:
    """
    将 Naga 的 LLM 配置注入 openclaw.json。

    读取 Naga 的 api_key / base_url / model，写入 openclaw.json 的
    models.providers 和 agents.defaults.model.primary。

    Returns:
        是否注入成功
    """
    if not OPENCLAW_CONFIG_FILE.exists():
        logger.warning("openclaw.json 不存在，无法注入 LLM 配置")
        return False

    try:
        from system.config import config as naga_config

        # Be tolerant to UTF-8 BOM written by some editors/PowerShell defaults.
        config_data = json.loads(OPENCLAW_CONFIG_FILE.read_text(encoding="utf-8-sig"))

        # 构建 naga provider
        provider_name = "naga"
        model_id = naga_config.api.model
        full_model_id = f"{provider_name}/{model_id}"
        model_api, base_url = _resolve_openclaw_provider_config(naga_config.api)

        models_config = config_data.setdefault("models", {})
        models_config["mode"] = "merge"
        providers = models_config.setdefault("providers", {})
        providers[provider_name] = {
            "baseUrl": base_url,
            "apiKey": naga_config.api.api_key,
            "auth": "api-key",
            "api": model_api,
            "models": [
                {
                    "id": model_id,
                    "name": model_id,
                    "reasoning": False,
                    "input": ["text"],
                    "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                    "contextWindow": 128000,
                    "maxTokens": naga_config.api.max_tokens,
                }
            ],
        }

        # 设置为默认模型
        agents = config_data.setdefault("agents", {})
        defaults = agents.setdefault("defaults", {})
        model = defaults.setdefault("model", {})
        # 不要强行覆盖用户已经选好的默认模型；除非它本来就指向我们管理的 provider。
        current_primary = model.get("primary") if isinstance(model, dict) else None
        if not current_primary or (isinstance(current_primary, str) and current_primary.startswith(f"{provider_name}/")):
            model["primary"] = full_model_id

        # 对历史配置做一次平滑补齐，避免 /hooks/agent 因 sessionKey 被拒绝
        hooks = config_data.setdefault("hooks", {})
        hooks.setdefault("allowRequestSessionKey", True)

        OPENCLAW_CONFIG_FILE.write_text(
            json.dumps(config_data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info(
            "已注入 Naga LLM 配置: provider=%s, model=%s, api=%s, baseUrl=%s",
            provider_name,
            full_model_id,
            model_api,
            base_url,
        )
        return True

    except Exception as e:
        logger.error(f"注入 LLM 配置失败: {e}")
        return False
