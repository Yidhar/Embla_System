#!/usr/bin/env python3
"""
LLM service module.

This module keeps backward compatibility for the existing OpenAI-compatible flow,
and adds native Google Generative Language API protocol support.
"""

import asyncio
import base64
import inspect
import json
import logging
import os
import re
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urlencode, urlparse

import httpx
import litellm
import websockets
from fastapi import FastAPI, HTTPException
from litellm import acompletion

# Add project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from system.config import get_config
from . import naga_auth

logger = logging.getLogger("LLMService")


@dataclass
class LLMResponse:
    """LLM response structure."""

    content: str
    reasoning_content: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        result = {"content": self.content}
        if self.reasoning_content:
            result["reasoning_content"] = self.reasoning_content
        return result


class LLMService:
    """Unified LLM service (OpenAI-compatible + Google native protocol)."""

    PROTOCOL_OPENAI_CHAT = "openai_chat_completions"
    PROTOCOL_GOOGLE_GENERATE = "google_generate_content"

    GOOGLE_DEFAULT_BASE = "https://generativelanguage.googleapis.com/v1beta"
    GOOGLE_LIVE_WS_PATH_TEMPLATE = "/ws/google.ai.generativelanguage.{version}.GenerativeService.BidiGenerateContent"
    OPENAI_HINTS = {"openai", "openai_compatible"}
    GOOGLE_HINTS = {"google", "gemini", "google_ai_studio", "google_genai"}
    DATA_URL_PATTERN = re.compile(r"^data:(?P<mime>[^;]+);base64,(?P<data>.+)$", re.IGNORECASE)
    GOOGLE_METHOD_PATTERN = re.compile(
        r"/models/(?P<model>[^:]+):(?P<method>generateContent|streamGenerateContent|BidiGenerateContent)$",
        re.IGNORECASE,
    )
    GOOGLE_URL_KEY_PATTERN = re.compile(r"([?&](?:key|api_key|x-goog-api-key)=)([^&]+)", re.IGNORECASE)

    def __init__(self):
        self._initialized = False
        self._initialize_client()

    def _initialize_client(self):
        """Initialize LiteLLM global configuration."""
        try:
            cfg = get_config()
            litellm.api_key = cfg.api.api_key
            # Reduce noisy provider/debug hints in production logs.
            if hasattr(litellm, "set_verbose"):
                litellm.set_verbose = False
            if hasattr(litellm, "suppress_debug_info"):
                litellm.suppress_debug_info = True

            protocol = self._resolve_protocol(api_base=cfg.api.base_url)
            if protocol != self.PROTOCOL_GOOGLE_GENERATE and cfg.api.base_url:
                # Keep existing behavior for OpenAI-compatible providers.
                if "openai.com" not in cfg.api.base_url:
                    litellm.api_base = cfg.api.base_url.rstrip("/") + "/"

            self._initialized = True
            logger.info("LLM service initialized")
        except Exception as e:
            logger.error("LLM service init failed: %s", e)
            self._initialized = False

    def _normalize_protocol(self, protocol: Optional[str]) -> str:
        value = (protocol or "").strip().lower()
        if value in {"openai_chat_completions", "openai", "openai_compatible"}:
            return self.PROTOCOL_OPENAI_CHAT
        if value in {"google", "gemini", "google_generate_content", "generativeai"}:
            return self.PROTOCOL_GOOGLE_GENERATE
        return self.PROTOCOL_OPENAI_CHAT

    def _is_auto_protocol(self, protocol: Optional[str]) -> bool:
        value = (protocol or "").strip().lower()
        return value in {"", "auto", "autodetect", "auto_detect"}

    def _resolve_protocol(
        self,
        provider_hint: Optional[str] = None,
        api_base: Optional[str] = None,
        protocol_override: Optional[str] = None,
    ) -> str:
        """Resolve protocol from explicit hint/config/base_url."""
        if protocol_override and not self._is_auto_protocol(protocol_override):
            return self._normalize_protocol(protocol_override)

        hint = (provider_hint or "").strip().lower()
        if hint in self.OPENAI_HINTS:
            return self.PROTOCOL_OPENAI_CHAT
        if hint in self.GOOGLE_HINTS:
            return self.PROTOCOL_GOOGLE_GENERATE

        cfg = get_config()
        configured_protocol = getattr(cfg.api, "protocol", "")
        if configured_protocol and not self._is_auto_protocol(configured_protocol):
            return self._normalize_protocol(configured_protocol)

        # In auto mode, base URL detection has higher priority than configured provider.
        # This avoids stale provider config (e.g. openai_compatible) forcing a wrong route.
        base = (api_base or cfg.api.base_url or "").strip().lower()
        if "generativelanguage.googleapis.com" in base:
            return self.PROTOCOL_GOOGLE_GENERATE

        configured_provider = getattr(cfg.api, "provider", "").strip().lower()
        if configured_provider in self.OPENAI_HINTS:
            return self.PROTOCOL_OPENAI_CHAT
        if configured_provider in self.GOOGLE_HINTS:
            return self.PROTOCOL_GOOGLE_GENERATE

        return self.PROTOCOL_OPENAI_CHAT

    def _get_model_name(self, model: Optional[str] = None, base_url: Optional[str] = None) -> str:
        """Get LiteLLM-style model identifier for OpenAI-compatible flow."""
        cfg = get_config()
        model = model or cfg.api.model
        base_url = (base_url or cfg.api.base_url or "").lower()

        # Keep existing gateway behavior
        if naga_auth.is_authenticated():
            return "openai/default"

        if "deepseek" in base_url and not model.startswith("deepseek/"):
            return f"deepseek/{model}"
        if "openrouter" in base_url and not model.startswith("openrouter/"):
            return f"openrouter/{model}"
        if "openai.com" in base_url:
            return model
        if not model.startswith("openai/"):
            return f"openai/{model}"
        return model

    def _normalize_openai_params_for_model(
        self,
        model_name: str,
        temperature: Optional[float],
    ) -> tuple[Optional[float], Dict[str, Any]]:
        """
        Normalize OpenAI-compatible params for model-specific constraints.

        Notes:
        - GPT-5 family (including gpt-5-codex) currently supports only temperature=1.
        - Enable LiteLLM drop_params for this family to avoid hard failures on other
          unsupported optional params forwarded by wrappers.
        """
        lowered = (model_name or "").lower()
        compat: Dict[str, Any] = {}
        normalized_temperature = temperature

        if "gpt-5" in lowered:
            if temperature is None or float(temperature) != 1.0:
                logger.info(
                    "[LLM] model=%s requires temperature=1, overriding from %s",
                    model_name,
                    temperature,
                )
            normalized_temperature = 1.0
            compat["drop_params"] = True

        return normalized_temperature, compat

    def _get_litellm_params(
        self,
        api_key: Optional[str],
        api_base: Optional[str],
        protocol: str,
    ) -> Dict[str, Any]:
        """Build LiteLLM params for OpenAI-compatible flow."""
        cfg = get_config()

        extra_body: Dict[str, Any] = {}
        if isinstance(getattr(cfg.api, "extra_body", None), dict):
            extra_body.update(cfg.api.extra_body)

        params: Dict[str, Any] = {}

        if naga_auth.is_authenticated() and protocol != self.PROTOCOL_GOOGLE_GENERATE:
            token = naga_auth.get_access_token()
            params["api_key"] = token
            params["api_base"] = naga_auth.NAGA_MODEL_URL + "/"
            extra_body["user_token"] = token
        else:
            params["api_key"] = api_key or cfg.api.api_key
            base = api_base or cfg.api.base_url
            params["api_base"] = base.rstrip("/") + "/" if base else None

        if extra_body:
            params["extra_body"] = extra_body

        if isinstance(getattr(cfg.api, "extra_headers", None), dict) and cfg.api.extra_headers:
            params["extra_headers"] = cfg.api.extra_headers

        return params

    def _build_google_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        cfg = get_config()
        if isinstance(getattr(cfg.api, "extra_headers", None), dict):
            headers.update(cfg.api.extra_headers)
        return headers

    def _build_google_ws_headers(self, api_key: Optional[str]) -> Dict[str, str]:
        headers: Dict[str, str] = {}
        if api_key:
            headers["x-goog-api-key"] = api_key

        cfg = get_config()
        if isinstance(getattr(cfg.api, "extra_headers", None), dict):
            for key, value in cfg.api.extra_headers.items():
                if isinstance(key, str):
                    headers[key] = str(value)
        return headers

    def _is_google_live_enabled(self) -> bool:
        cfg = get_config()
        return bool(getattr(cfg.api, "google_live_api", False))

    def _use_system_proxy(self) -> bool:
        cfg = get_config()
        return bool(getattr(cfg.api, "applied_proxy", False))

    def _normalize_google_model_name(self, model: Optional[str]) -> str:
        model_name = (model or "").strip()
        if model_name.startswith("models/"):
            model_name = model_name[len("models/") :]

        # Allow accidental model input like "gemini-2.5-flash:generateContent".
        if ":" in model_name:
            maybe_model, maybe_method = model_name.rsplit(":", 1)
            if maybe_method in {"generateContent", "streamGenerateContent", "BidiGenerateContent"}:
                model_name = maybe_model

        # Convert OpenAI-style prefixed model ids into raw Gemini model id.
        if "/" in model_name and not model_name.startswith(("publishers/", "tunedModels/")):
            prefix = model_name.split("/", 1)[0].lower()
            if prefix in {"openai", "openrouter", "deepseek", "google", "gemini"}:
                model_name = model_name.split("/")[-1]

        model_name = model_name.strip().strip("/")
        return model_name or "gemini-2.0-flash"

    def _normalize_google_base_and_model(self, api_base: Optional[str], model: Optional[str]) -> tuple[str, str]:
        base_input = (api_base or self.GOOGLE_DEFAULT_BASE).strip()
        if not base_input:
            base_input = self.GOOGLE_DEFAULT_BASE

        parsed = urlparse(base_input if "://" in base_input else f"https://{base_input}")
        scheme = parsed.scheme or "https"
        if scheme in {"ws", "wss"}:
            scheme = "https"

        host = parsed.netloc or "generativelanguage.googleapis.com"
        raw_path = (parsed.path or "").strip()
        lowered_path = raw_path.lower()

        extracted_model: Optional[str] = None
        method_match = self.GOOGLE_METHOD_PATTERN.search(raw_path)
        if method_match:
            extracted_model = method_match.group("model")
            raw_path = raw_path[: method_match.start()]
            lowered_path = raw_path.lower()

        for suffix in (
            "/openai/chat/completions",
            "/chat/completions",
            "/completions",
            "/openai",
        ):
            if lowered_path.endswith(suffix):
                raw_path = raw_path[: -len(suffix)]
                lowered_path = raw_path.lower()
                break

        if "/v1alpha" in lowered_path:
            version_path = "/v1alpha"
        elif "/v1beta" in lowered_path:
            version_path = "/v1beta"
        elif lowered_path.endswith("/v1") or "/v1/" in lowered_path:
            version_path = "/v1"
        else:
            version_path = "/v1beta"

        normalized_base = f"{scheme}://{host}{version_path}"
        normalized_model = self._normalize_google_model_name(model or extracted_model)
        return normalized_base.rstrip("/"), normalized_model

    def _mask_google_url(self, url: str, params: Optional[Dict[str, str]] = None) -> str:
        final_url = url
        if params:
            query = urlencode(params)
            if query:
                final_url = f"{final_url}{'&' if '?' in final_url else '?'}{query}"
        return self.GOOGLE_URL_KEY_PATTERN.sub(r"\1***", final_url)

    def _build_google_url(self, model: str, api_base: Optional[str], method: str) -> tuple[str, str, str]:
        base, model_name = self._normalize_google_base_and_model(api_base, model)
        method_name = method.strip()
        if method_name not in {"generateContent", "streamGenerateContent"}:
            method_name = "generateContent"
        return f"{base}/models/{model_name}:{method_name}", base, model_name

    def _build_google_live_ws_url(self, api_base: Optional[str]) -> str:
        base_input = (api_base or "").strip()
        lowered_input = base_input.lower()
        if lowered_input.startswith(("ws://", "wss://")) and "bidigeneratecontent" in lowered_input:
            return base_input

        normalized_base, _ = self._normalize_google_base_and_model(api_base, None)
        lowered = normalized_base.lower()
        if lowered.startswith(("ws://", "wss://")) and "bidigeneratecontent" in lowered:
            return normalized_base

        parsed = urlparse(normalized_base if "://" in normalized_base else f"https://{normalized_base}")
        host = parsed.netloc or "generativelanguage.googleapis.com"
        path = (parsed.path or "").lower()

        version = "v1beta"
        if "/v1alpha" in path:
            version = "v1alpha"
        elif "/v1beta" in path:
            version = "v1beta"
        elif "/v1/" in path or path.endswith("/v1"):
            version = "v1"

        return f"wss://{host}{self.GOOGLE_LIVE_WS_PATH_TEMPLATE.format(version=version)}"

    def _convert_image_url_to_google_part(self, image_url: str) -> Optional[Dict[str, Any]]:
        if not image_url:
            return None

        match = self.DATA_URL_PATTERN.match(image_url)
        if match:
            return {
                "inlineData": {
                    "mimeType": match.group("mime"),
                    "data": match.group("data"),
                }
            }

        # For non data-url image, avoid hard failure. Keep minimal textual hint.
        if image_url.startswith("http://") or image_url.startswith("https://"):
            return {"text": f"Image URL: {image_url}"}
        return None

    def _convert_content_to_google_parts(self, content: Any) -> List[Dict[str, Any]]:
        parts: List[Dict[str, Any]] = []

        if isinstance(content, str):
            if content:
                parts.append({"text": content})
            return parts

        if isinstance(content, list):
            for block in content:
                if isinstance(block, str):
                    if block:
                        parts.append({"text": block})
                    continue
                if not isinstance(block, dict):
                    continue

                block_type = str(block.get("type", "")).lower()
                if block_type in {"text", "input_text"}:
                    text = block.get("text")
                    if isinstance(text, str) and text:
                        parts.append({"text": text})
                    continue

                if block_type == "image_url":
                    image_url_obj = block.get("image_url")
                    if isinstance(image_url_obj, dict):
                        image_url = str(image_url_obj.get("url", "") or "")
                    else:
                        image_url = str(image_url_obj or "")
                    image_part = self._convert_image_url_to_google_part(image_url)
                    if image_part:
                        parts.append(image_part)
                    continue

                # Fallback: if a block still has text, preserve it.
                text = block.get("text")
                if isinstance(text, str) and text:
                    parts.append({"text": text})

        return parts

    def _convert_messages_to_google_payload(
        self,
        messages: List[Dict[str, Any]],
        temperature: float,
        max_tokens: Optional[int],
    ) -> Dict[str, Any]:
        contents: List[Dict[str, Any]] = []
        system_texts: List[str] = []

        for message in messages:
            role = str(message.get("role", "user")).lower()
            content = message.get("content", "")

            if role == "system":
                for part in self._convert_content_to_google_parts(content):
                    text = part.get("text")
                    if isinstance(text, str) and text:
                        system_texts.append(text)
                continue

            parts = self._convert_content_to_google_parts(content)
            if not parts:
                continue

            google_role = "model" if role == "assistant" else "user"
            if contents and contents[-1]["role"] == google_role:
                contents[-1]["parts"].extend(parts)
            else:
                contents.append({"role": google_role, "parts": parts})

        if not contents:
            contents = [{"role": "user", "parts": [{"text": ""}]}]

        payload: Dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }

        if system_texts:
            payload["systemInstruction"] = {"parts": [{"text": "\n\n".join(system_texts)}]}

        cfg = get_config()
        if isinstance(getattr(cfg.api, "extra_body", None), dict) and cfg.api.extra_body:
            payload.update(cfg.api.extra_body)

        return payload

    def _build_google_live_setup_and_turns(
        self,
        messages: List[Dict[str, Any]],
        temperature: float,
        max_tokens: Optional[int],
        model: str,
    ) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
        payload = self._convert_messages_to_google_payload(messages, temperature, max_tokens)
        model_name = self._normalize_google_model_name(model)

        setup: Dict[str, Any] = {"model": f"models/{model_name}"}
        generation_config = payload.get("generationConfig")
        if isinstance(generation_config, dict):
            setup["generationConfig"] = generation_config

        system_instruction = payload.get("systemInstruction")
        if isinstance(system_instruction, dict):
            setup["systemInstruction"] = system_instruction

        for key, value in payload.items():
            if key not in {"contents", "generationConfig", "systemInstruction"}:
                setup[key] = value

        turns = payload.get("contents")
        if not isinstance(turns, list) or not turns:
            turns = [{"role": "user", "parts": [{"text": ""}]}]

        return setup, turns

    def _extract_google_text(self, data: Any) -> str:
        if isinstance(data, list):
            for item in data:
                text = self._extract_google_text(item)
                if text:
                    return text
            return ""

        if not isinstance(data, dict):
            return ""

        candidates = data.get("candidates") or []
        if not isinstance(candidates, list):
            return ""

        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            content = candidate.get("content") or {}
            if not isinstance(content, dict):
                continue
            parts = content.get("parts") or []
            if not isinstance(parts, list):
                continue
            texts: List[str] = []
            for part in parts:
                if isinstance(part, dict):
                    text = part.get("text")
                    if isinstance(text, str) and text:
                        texts.append(text)
            if texts:
                return "".join(texts)

        return ""

    def _extract_google_error(self, data: Any) -> str:
        if isinstance(data, dict):
            err = data.get("error")
            if isinstance(err, dict):
                message = err.get("message")
                if isinstance(message, str) and message:
                    return message
            message = data.get("message")
            if isinstance(message, str) and message:
                return message
        if isinstance(data, str):
            return data
        return "Unknown Google API error"

    def _extract_google_live_text(self, server_content: Dict[str, Any]) -> str:
        model_turn = server_content.get("modelTurn") or {}
        if not isinstance(model_turn, dict):
            return ""

        parts = model_turn.get("parts") or []
        if not isinstance(parts, list):
            return ""

        texts: List[str] = []
        for part in parts:
            if isinstance(part, dict):
                text = part.get("text")
                if isinstance(text, str) and text:
                    texts.append(text)
        return "".join(texts)

    async def _connect_google_live_ws(
        self,
        ws_url: str,
        headers: Dict[str, str],
        api_key: Optional[str],
        timeout_seconds: int,
    ):
        use_system_proxy = self._use_system_proxy()
        connect_kwargs = {
            "open_timeout": timeout_seconds,
            "close_timeout": timeout_seconds,
            "ping_timeout": timeout_seconds,
        }
        try:
            if "proxy" in inspect.signature(websockets.connect).parameters:
                connect_kwargs["proxy"] = True if use_system_proxy else None
        except Exception:
            pass

        candidates: List[tuple[str, Dict[str, str]]] = [(ws_url, headers)]
        if api_key and "key=" not in ws_url:
            sep = "&" if "?" in ws_url else "?"
            ws_with_query_key = f"{ws_url}{sep}key={quote(api_key)}"
            query_headers = {k: v for k, v in headers.items() if k.lower() != "x-goog-api-key"}
            candidates.append((ws_with_query_key, query_headers))

        last_error: Optional[Exception] = None
        attempted_urls: List[str] = []
        for url, ws_headers in candidates:
            safe_url = self._mask_google_url(url)
            try:
                try:
                    return await websockets.connect(url, additional_headers=ws_headers, **connect_kwargs)
                except TypeError:
                    return await websockets.connect(url, extra_headers=ws_headers, **connect_kwargs)
            except Exception as e:  # pragma: no cover - network/runtime branch
                attempted_urls.append(safe_url)
                logger.warning("[LLM] Google Live connect failed url=%s error=%s", safe_url, e)
                last_error = e

        raise RuntimeError(
            f"Failed to connect Google Live API websocket, attempted={attempted_urls}, last_error={last_error}"
        )

    async def _call_google_generate_content(
        self,
        messages: List[Dict[str, Any]],
        temperature: float,
        model: str,
        api_key: Optional[str],
        api_base: Optional[str],
    ) -> LLMResponse:
        cfg = get_config()
        timeout_seconds = getattr(cfg.api, "request_timeout", 120)
        max_tokens = getattr(cfg.api, "max_tokens", None)
        use_system_proxy = self._use_system_proxy()

        payload = self._convert_messages_to_google_payload(messages, temperature, max_tokens)
        url, normalized_base, normalized_model = self._build_google_url(
            model=model,
            api_base=api_base,
            method="generateContent",
        )
        params: Dict[str, str] = {}
        if api_key:
            params["key"] = api_key

        headers = self._build_google_headers()
        logger.info(
            "[LLM] Google request mode=generateContent base=%s model=%s url=%s timeout=%ss proxy=%s",
            normalized_base,
            normalized_model,
            self._mask_google_url(url, params),
            timeout_seconds,
            use_system_proxy,
        )

        async with httpx.AsyncClient(timeout=timeout_seconds, trust_env=use_system_proxy) as client:
            response = await client.post(url, params=params, headers=headers, json=payload)

        if response.status_code >= 400:
            detail = response.text
            try:
                detail_json = response.json()
                detail = self._extract_google_error(detail_json)
            except Exception:
                pass
            raise RuntimeError(
                f"Google API error ({response.status_code}) url={self._mask_google_url(url, params)}: {detail}"
            )

        data = response.json()
        text = self._extract_google_text(data)
        return LLMResponse(content=text or "", reasoning_content=None)

    async def _stream_google_generate_content(
        self,
        messages: List[Dict[str, Any]],
        temperature: float,
        model: str,
        api_key: Optional[str],
        api_base: Optional[str],
    ):
        cfg = get_config()
        timeout_seconds = getattr(cfg.api, "request_timeout", 120)
        max_tokens = getattr(cfg.api, "max_tokens", None)
        use_system_proxy = self._use_system_proxy()

        payload = self._convert_messages_to_google_payload(messages, temperature, max_tokens)
        url, normalized_base, normalized_model = self._build_google_url(
            model=model,
            api_base=api_base,
            method="streamGenerateContent",
        )
        params: Dict[str, str] = {"alt": "sse"}
        if api_key:
            params["key"] = api_key

        headers = self._build_google_headers()
        accumulated_text = ""
        log_url = self._mask_google_url(url, params)
        logger.info(
            "[LLM] Google request mode=streamGenerateContent base=%s model=%s url=%s timeout=%ss proxy=%s",
            normalized_base,
            normalized_model,
            log_url,
            timeout_seconds,
            use_system_proxy,
        )

        try:
            async with httpx.AsyncClient(timeout=timeout_seconds, trust_env=use_system_proxy) as client:
                async with client.stream("POST", url, params=params, headers=headers, json=payload) as response:
                    if response.status_code >= 400:
                        raw = await response.aread()
                        detail = raw.decode("utf-8", errors="ignore")
                        try:
                            detail_json = json.loads(detail)
                            detail = self._extract_google_error(detail_json)
                        except Exception:
                            pass
                        yield self._format_sse_chunk(
                            "content",
                            f"Google API error ({response.status_code}) url={log_url}: {detail}",
                        )
                        return

                    async for line in response.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        data_str = line[5:].strip()
                        if not data_str or data_str == "[DONE]":
                            continue

                        try:
                            chunk_obj = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        chunk_text = self._extract_google_text(chunk_obj)
                        if not chunk_text:
                            continue

                        if chunk_text.startswith(accumulated_text):
                            delta = chunk_text[len(accumulated_text) :]
                            accumulated_text = chunk_text
                        elif accumulated_text and chunk_text in accumulated_text:
                            delta = ""
                        else:
                            delta = chunk_text
                            accumulated_text += chunk_text

                        if delta:
                            yield self._format_sse_chunk("content", delta)
        except Exception as e:
            logger.error("Google streaming failed (url=%s): %s", log_url, e)
            yield self._format_sse_chunk("content", f"Google streaming error (url={log_url}): {e}")

    async def _stream_google_bidi_generate_content(
        self,
        messages: List[Dict[str, Any]],
        temperature: float,
        model: str,
        api_key: Optional[str],
        api_base: Optional[str],
    ):
        cfg = get_config()
        timeout_seconds = getattr(cfg.api, "request_timeout", 120)
        max_tokens = getattr(cfg.api, "max_tokens", None)
        ws_url = self._build_google_live_ws_url(api_base)
        ws_headers = self._build_google_ws_headers(api_key)
        setup_payload, turns = self._build_google_live_setup_and_turns(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            model=model,
        )
        logger.info(
            "[LLM] Google request mode=BidiGenerateContent url=%s timeout=%ss proxy=%s",
            self._mask_google_url(ws_url),
            timeout_seconds,
            self._use_system_proxy(),
        )

        try:
            websocket = await self._connect_google_live_ws(
                ws_url=ws_url,
                headers=ws_headers,
                api_key=api_key,
                timeout_seconds=timeout_seconds,
            )
            async with websocket:
                await websocket.send(json.dumps({"setup": setup_payload}, ensure_ascii=False))

                pending_messages: List[Dict[str, Any]] = []
                try:
                    first_raw = await asyncio.wait_for(websocket.recv(), timeout=timeout_seconds)
                    first_obj = json.loads(first_raw)
                    if not first_obj.get("setupComplete"):
                        pending_messages.append(first_obj)
                except asyncio.TimeoutError:
                    raise RuntimeError("Google Live API setup timeout")
                except json.JSONDecodeError:
                    pass

                await websocket.send(
                    json.dumps(
                        {
                            "clientContent": {
                                "turns": turns,
                                "turnComplete": True,
                            }
                        },
                        ensure_ascii=False,
                    )
                )

                while True:
                    if pending_messages:
                        message_obj = pending_messages.pop(0)
                    else:
                        raw = await asyncio.wait_for(websocket.recv(), timeout=timeout_seconds)
                        message_obj = json.loads(raw)

                    go_away = message_obj.get("goAway")
                    if isinstance(go_away, dict):
                        reason = go_away.get("reason") or "server sent goAway"
                        raise RuntimeError(str(reason))

                    server_content = message_obj.get("serverContent")
                    if not isinstance(server_content, dict):
                        continue

                    chunk_text = self._extract_google_live_text(server_content)
                    if chunk_text:
                        yield self._format_sse_chunk("content", chunk_text)

                    if server_content.get("turnComplete"):
                        break
        except Exception as e:
            safe_ws_url = self._mask_google_url(ws_url)
            logger.error("Google Live streaming failed (url=%s): %s", safe_ws_url, e)
            yield self._format_sse_chunk("content", f"Google Live streaming error (url={safe_ws_url}): {e}")

    async def get_response(self, prompt: str, temperature: float = 0.7) -> str:
        response = await self.get_response_with_reasoning(prompt, temperature)
        return response.content

    async def get_response_with_reasoning(self, prompt: str, temperature: float = 0.7) -> LLMResponse:
        return await self.chat_with_context_and_reasoning_with_overrides(
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            model_override=None,
            api_key_override=None,
            api_base_override=None,
            provider_hint=None,
        )

    def is_available(self) -> bool:
        return self._initialized

    async def chat_with_context(self, messages: List[Dict], temperature: float = 0.7) -> str:
        response = await self.chat_with_context_and_reasoning(messages, temperature)
        return response.content

    async def chat_with_context_and_reasoning_with_overrides(
        self,
        messages: List[Dict[str, Any]],
        temperature: float = 0.7,
        model_override: Optional[str] = None,
        api_key_override: Optional[str] = None,
        api_base_override: Optional[str] = None,
        provider_hint: Optional[str] = None,
    ) -> LLMResponse:
        if not self._initialized:
            self._initialize_client()
            if not self._initialized:
                return LLMResponse(content="LLM service unavailable: client init failed")

        cfg = get_config()
        final_model = model_override or cfg.api.model
        final_base = api_base_override or cfg.api.base_url
        final_api_key = api_key_override or cfg.api.api_key
        protocol = self._resolve_protocol(provider_hint=provider_hint, api_base=final_base)

        if protocol == self.PROTOCOL_GOOGLE_GENERATE:
            try:
                return await self._call_google_generate_content(
                    messages=messages,
                    temperature=temperature,
                    model=final_model,
                    api_key=final_api_key,
                    api_base=final_base,
                )
            except Exception as e:
                safe_error = self._sanitize_litellm_error_text(e)
                logger.error("Google chat call failed: %s", safe_error)
                return LLMResponse(content=f"Google API call error: {safe_error}")

        try:
            model_name = final_model
            normalized_provider_hint = (provider_hint or "").strip().lower()
            if normalized_provider_hint and normalized_provider_hint not in {"openai", "openai_compatible"}:
                if not model_name.startswith(f"{normalized_provider_hint}/"):
                    model_name = f"{normalized_provider_hint}/{model_name}"
            else:
                model_name = self._get_model_name(model_name, final_base)

            normalized_temperature, compat_params = self._normalize_openai_params_for_model(
                model_name=model_name,
                temperature=temperature,
            )

            response = await acompletion(
                model=model_name,
                messages=messages,
                temperature=normalized_temperature,
                max_tokens=cfg.api.max_tokens if hasattr(cfg.api, "max_tokens") else None,
                **compat_params,
                **self._get_litellm_params(final_api_key, final_base, protocol),
            )
            message = response.choices[0].message
            return LLMResponse(
                content=message.content or "",
                reasoning_content=getattr(message, "reasoning_content", None),
            )
        except Exception as e:
            safe_error = self._sanitize_litellm_error_text(e)
            logger.error("Context chat call failed: %s", safe_error)
            return LLMResponse(content=f"Chat call error: {safe_error}")

    async def chat_with_context_and_reasoning(self, messages: List[Dict], temperature: float = 0.7) -> LLMResponse:
        return await self.chat_with_context_and_reasoning_with_overrides(
            messages=messages,
            temperature=temperature,
            model_override=None,
            api_key_override=None,
            api_base_override=None,
        )

    @staticmethod
    def _obj_get(obj: Any, key: str, default: Any = None) -> Any:
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    def _merge_stream_tool_call_deltas(self, buffers: Dict[int, Dict[str, Any]], delta_tool_calls: Any) -> None:
        if not delta_tool_calls:
            return

        for raw_call in delta_tool_calls:
            index_raw = self._obj_get(raw_call, "index", None)
            try:
                index = int(index_raw) if index_raw is not None else len(buffers)
            except Exception:
                index = len(buffers)

            buffer = buffers.setdefault(
                index,
                {
                    "id": None,
                    "name": None,
                    "arguments_parts": [],
                },
            )

            call_id = self._obj_get(raw_call, "id", None)
            if call_id:
                buffer["id"] = call_id

            fn = self._obj_get(raw_call, "function", None)
            if fn is not None:
                fn_name = self._obj_get(fn, "name", None)
                if fn_name:
                    buffer["name"] = fn_name
                fn_args = self._obj_get(fn, "arguments", None)
                if fn_args is not None and fn_args != "":
                    buffer["arguments_parts"].append(str(fn_args))
                continue

            # Some providers may flatten function fields.
            fn_name = self._obj_get(raw_call, "name", None)
            if fn_name:
                buffer["name"] = fn_name
            fn_args = self._obj_get(raw_call, "arguments", None)
            if fn_args is not None and fn_args != "":
                buffer["arguments_parts"].append(str(fn_args))

    def _finalize_stream_tool_calls(self, buffers: Dict[int, Dict[str, Any]]) -> List[Dict[str, Any]]:
        finalized: List[Dict[str, Any]] = []

        for index in sorted(buffers.keys()):
            item = buffers[index]
            raw_arguments = "".join(item.get("arguments_parts", [])).strip()
            parsed_arguments: Any = {}
            parse_error: Optional[str] = None

            if raw_arguments:
                try:
                    parsed_arguments = json.loads(raw_arguments)
                except Exception as e_json:
                    try:
                        import json5 as _json5

                        parsed_arguments = _json5.loads(raw_arguments)
                    except Exception:
                        parse_error = str(e_json)
                        parsed_arguments = {}

            finalized.append(
                {
                    "id": item.get("id") or f"tool_call_{index}",
                    "name": item.get("name") or "",
                    "arguments": parsed_arguments,
                    "arguments_raw": raw_arguments,
                    "parse_error": parse_error,
                }
            )

        return finalized

    @staticmethod
    def _is_retryable_stream_exception(error: Exception) -> bool:
        """Best-effort classification for transient streaming failures."""
        retryable_types = tuple(
            t
            for t in (
                getattr(litellm, "APIConnectionError", None),
                getattr(litellm, "ServiceUnavailableError", None),
                getattr(litellm, "Timeout", None),
                getattr(litellm, "InternalServerError", None),
            )
            if isinstance(t, type)
        )
        if retryable_types and isinstance(error, retryable_types):
            return True

        text = str(error).lower()
        transient_markers = (
            "connection error",
            "connection reset",
            "connection aborted",
            "connection refused",
            "network error",
            "timed out",
            "timeout",
            "service unavailable",
            "temporarily unavailable",
        )
        return any(marker in text for marker in transient_markers)

    @staticmethod
    def _sanitize_litellm_error_text(error: Any) -> str:
        """Trim noisy LiteLLM hint/provider lines from surfaced error text."""
        raw = str(error or "").strip()
        if not raw:
            return "unknown error"

        skip_markers = (
            "provider list:",
            "docs.litellm.ai/docs/providers",
            "litellm.info:",
            "if you need to debug this error",
        )

        cleaned: List[str] = []
        for line in raw.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            lowered = stripped.lower()
            if any(marker in lowered for marker in skip_markers):
                continue
            cleaned.append(stripped)

        if not cleaned:
            return raw.splitlines()[0].strip() if raw.splitlines() else raw

        deduped: List[str] = []
        for line in cleaned:
            if not deduped or deduped[-1] != line:
                deduped.append(line)
        return " | ".join(deduped)

    async def stream_chat_with_context(
        self,
        messages: List[Dict],
        temperature: float = 0.7,
        model_override: Optional[Dict[str, str]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Any] = None,
    ):
        if not self._initialized:
            self._initialize_client()
            if not self._initialized:
                yield self._format_sse_chunk("content", "LLM service unavailable: client init failed")
                return

        cfg = get_config()
        max_attempts = 3
        auth_retried = False

        if model_override:
            final_model = model_override.get("model") or cfg.api.model
            final_base = model_override.get("api_base") or cfg.api.base_url
            final_api_key = model_override.get("api_key") or cfg.api.api_key
        else:
            final_model = cfg.api.model
            final_base = cfg.api.base_url
            final_api_key = cfg.api.api_key

        protocol = self._resolve_protocol(api_base=final_base)
        if protocol == self.PROTOCOL_GOOGLE_GENERATE:
            if tools:
                msg = (
                    "当前模型路由不支持原生 function calling（Google protocol path）。"
                    "请切换到支持 tools/function-calling 的 OpenAI-compatible 模型。"
                )
                logger.error("[LLM] %s", msg)
                yield self._format_sse_chunk(
                    "tool_calls",
                    json.dumps(
                        [
                            {
                                "id": "tool_protocol_not_supported",
                                "name": "",
                                "arguments": {},
                                "arguments_raw": "",
                                "parse_error": msg,
                            }
                        ],
                        ensure_ascii=False,
                    ),
                )
                return
            if self._is_google_live_enabled():
                logger.info("[LLM] Google stream route: BidiGenerateContent (Live API)")
                async for chunk in self._stream_google_bidi_generate_content(
                    messages=messages,
                    temperature=temperature,
                    model=final_model,
                    api_key=final_api_key,
                    api_base=final_base,
                ):
                    yield chunk
            else:
                logger.info("[LLM] Google stream route: streamGenerateContent (SSE)")
                async for chunk in self._stream_google_generate_content(
                    messages=messages,
                    temperature=temperature,
                    model=final_model,
                    api_key=final_api_key,
                    api_base=final_base,
                ):
                    yield chunk
            return

        for attempt in range(max_attempts):
            try:
                model_name = self._get_model_name(model=final_model, base_url=final_base)
                llm_params = self._get_litellm_params(final_api_key, final_base, protocol)
                timeout_seconds = getattr(cfg.api, "request_timeout", 120)
                normalized_temperature, compat_params = self._normalize_openai_params_for_model(
                    model_name=model_name,
                    temperature=temperature,
                )

                logger.debug(
                    "[LLM] attempt=%s is_auth=%s api_base=%s model=%s",
                    attempt,
                    naga_auth.is_authenticated(),
                    llm_params.get("api_base"),
                    model_name,
                )

                request_kwargs: Dict[str, Any] = {}
                if tools:
                    request_kwargs["tools"] = tools
                    if tool_choice is not None:
                        request_kwargs["tool_choice"] = tool_choice

                response = await acompletion(
                    model=model_name,
                    messages=messages,
                    temperature=normalized_temperature,
                    max_tokens=cfg.api.max_tokens if hasattr(cfg.api, "max_tokens") else None,
                    stream=True,
                    timeout=timeout_seconds,
                    stream_timeout=timeout_seconds,
                    num_retries=0,
                    **compat_params,
                    **request_kwargs,
                    **llm_params,
                )

                tool_call_buffers: Dict[int, Dict[str, Any]] = {}
                async for chunk in response:
                    if not chunk.choices:
                        continue

                    delta = chunk.choices[0].delta
                    reasoning = getattr(delta, "reasoning_content", None)
                    if reasoning:
                        yield self._format_sse_chunk("reasoning", reasoning)

                    content = getattr(delta, "content", None)
                    if content:
                        yield self._format_sse_chunk("content", content)

                    delta_tool_calls = getattr(delta, "tool_calls", None)
                    if delta_tool_calls:
                        self._merge_stream_tool_call_deltas(tool_call_buffers, delta_tool_calls)

                if tool_call_buffers:
                    finalized_calls = self._finalize_stream_tool_calls(tool_call_buffers)
                    if finalized_calls:
                        yield self._format_sse_chunk("tool_calls", json.dumps(finalized_calls, ensure_ascii=False))
                return

            except litellm.AuthenticationError as e:
                logger.error(
                    "LLM 401 diagnostic: attempt=%s is_auth=%s has_refresh=%s",
                    attempt,
                    naga_auth.is_authenticated(),
                    naga_auth.has_refresh_token(),
                )
                if not auth_retried and naga_auth.is_authenticated():
                    auth_retried = True
                    try:
                        await naga_auth.refresh()
                        logger.info("Token refresh success, retrying LLM call")
                        continue
                    except Exception as refresh_err:
                        logger.error("Token refresh failed: %s", refresh_err)
                yield self._format_sse_chunk("auth_expired", "Login expired, please sign in again")
                return

            except Exception as e:
                if self._is_retryable_stream_exception(e):
                    safe_error = self._sanitize_litellm_error_text(e)
                    if attempt < max_attempts - 1:
                        logger.warning(
                            "Streaming call connection issue (attempt %s/%s): %s",
                            attempt + 1,
                            max_attempts,
                            safe_error,
                        )
                        await asyncio.sleep(1 + attempt)
                        continue
                    yield self._format_sse_chunk(
                        "content",
                        f"Streaming call error (connection issue after {max_attempts} retries): {safe_error}",
                    )
                    return
                safe_error = self._sanitize_litellm_error_text(e)
                logger.error("Streaming chat failed: %s", safe_error)
                yield self._format_sse_chunk("content", f"Streaming call error: {safe_error}")
                return

    def _format_sse_chunk(self, chunk_type: str, text: str) -> str:
        data = {"type": chunk_type, "text": text}
        b64 = base64.b64encode(json.dumps(data, ensure_ascii=False).encode("utf-8")).decode("ascii")
        return f"data: {b64}\n\n"


_llm_service: Optional[LLMService] = None


def get_llm_service() -> LLMService:
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService()
    return _llm_service


llm_app = FastAPI(title="LLM Service API", description="LLM service API", version="1.0.0")


@llm_app.post("/llm/chat")
async def llm_chat(request: Dict[str, Any]):
    try:
        prompt = request.get("prompt", "")
        temperature = request.get("temperature", 0.7)

        if not prompt:
            raise HTTPException(status_code=400, detail="prompt cannot be empty")

        llm_service = get_llm_service()
        response = await llm_service.get_response(prompt, temperature)

        return {"status": "success", "response": response, "temperature": temperature}
    except Exception as e:
        logger.error("LLM chat endpoint error: %s", e)
        raise HTTPException(status_code=500, detail=f"LLM service error: {e}")
