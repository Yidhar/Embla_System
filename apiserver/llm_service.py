#!/usr/bin/env python3
"""
LLM service module.

This module unifies routing around OpenAI-compatible chat completions.
Gemini endpoints are normalized to Gemini's OpenAI-compatible base URL.
"""

import asyncio
import json
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import litellm
from fastapi import FastAPI, HTTPException
from litellm import acompletion

# Add project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from system.config import get_config, get_immutable_dna_locked_prompts, resolve_prompt_registry_entry
from core.security import DNAFileSpec, ImmutableDNALoader

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
    """Unified LLM service with OpenAI-compatible routing."""

    PROTOCOL_OPENAI_CHAT = "openai_chat_completions"
    DNA_RUNTIME_HEADER = "[Immutable DNA Runtime Injection]"
    DNA_RUNTIME_ENABLED_ENV = "EMBLA_IMMUTABLE_DNA_RUNTIME_INJECTION"
    DNA_PROMPTS_ROOT_ENV = "EMBLA_IMMUTABLE_DNA_PROMPTS_ROOT"
    DNA_MANIFEST_PATH_ENV = "EMBLA_IMMUTABLE_DNA_MANIFEST_PATH"
    DNA_AUDIT_PATH_ENV = "EMBLA_IMMUTABLE_DNA_AUDIT_PATH"
    DNA_REQUIRED_FILES_DEFAULT = (
        "conversation_style_prompt.md",
        "agentic_tool_prompt.md",
    )

    OPENAI_HINTS = {"openai", "openai_compatible"}
    GOOGLE_HINTS = {"google", "gemini", "google_ai_studio", "google_genai"}
    LEGACY_GOOGLE_ONLY_EXTRA_BODY_KEYS = {"generationconfig", "mediaresolution"}

    def __init__(self):
        self._initialized = False
        self._immutable_dna_enabled = self._resolve_immutable_dna_runtime_enabled()
        self._immutable_dna_required_files = self._resolve_immutable_dna_required_files()
        self._immutable_dna_loader: Optional[ImmutableDNALoader] = None
        self._initialize_client()

    def _resolve_immutable_dna_runtime_enabled(self) -> bool:
        raw = os.environ.get(self.DNA_RUNTIME_ENABLED_ENV, "1")
        normalized = str(raw or "").strip().lower()
        if not normalized:
            return True
        return normalized not in {"0", "false", "no", "off"}

    def _build_immutable_dna_loader(self) -> Optional[ImmutableDNALoader]:
        if not self._immutable_dna_enabled:
            return None

        try:
            repo_root = Path(__file__).resolve().parent.parent
            prompts_root_raw = os.environ.get(
                self.DNA_PROMPTS_ROOT_ENV,
                str(repo_root / "system" / "prompts"),
            )
            prompts_root = Path(str(prompts_root_raw)).expanduser().resolve()
            manifest_path_raw = os.environ.get(
                self.DNA_MANIFEST_PATH_ENV,
                str(prompts_root / "immutable_dna_manifest.spec"),
            )
            manifest_path = Path(str(manifest_path_raw)).expanduser().resolve()
            audit_path_raw = os.environ.get(
                self.DNA_AUDIT_PATH_ENV,
                str(repo_root / "scratch" / "reports" / "immutable_dna_runtime_injection_audit.jsonl"),
            )
            audit_path = Path(str(audit_path_raw)).expanduser().resolve()
            return ImmutableDNALoader(
                root_dir=prompts_root,
                dna_files=[DNAFileSpec(path=name, required=True) for name in self._immutable_dna_required_files],
                manifest_path=manifest_path,
                audit_file=audit_path,
            )
        except Exception as exc:
            logger.error("Immutable DNA loader init failed: %s", exc)
            return None

    def _ensure_immutable_dna_loader(self) -> Optional[ImmutableDNALoader]:
        if self._immutable_dna_loader is None:
            self._immutable_dna_loader = self._build_immutable_dna_loader()
        return self._immutable_dna_loader

    def get_immutable_dna_loader(self) -> Optional[ImmutableDNALoader]:
        return self._ensure_immutable_dna_loader()

    def immutable_dna_preflight(self) -> Dict[str, Any]:
        """Run startup-time immutable DNA verification for fail-fast bootstrap."""
        enabled = bool(self._immutable_dna_enabled)
        report: Dict[str, Any] = {
            "enabled": enabled,
            "passed": False,
            "reason": "uninitialized",
            "required_prompt_files": list(self._immutable_dna_required_files),
        }
        if not enabled:
            report["passed"] = True
            report["reason"] = "immutable_dna_runtime_disabled"
            return report

        loader = self._ensure_immutable_dna_loader()
        if loader is None:
            report["reason"] = "immutable_dna_loader_unavailable"
            return report

        report["manifest_path"] = str(loader.manifest_path)
        report["audit_file"] = str(loader.audit_file)
        verify = loader.verify()
        verify_payload = verify.to_dict()
        report["verify"] = verify_payload
        report["passed"] = bool(verify.ok)
        report["reason"] = str(verify.reason or ("ok" if verify.ok else "verify_failed"))
        if verify_payload.get("manifest_hash"):
            report["manifest_hash"] = str(verify_payload["manifest_hash"])
        return report

    def _resolve_immutable_dna_required_files(self) -> List[str]:
        repo_root = Path(__file__).resolve().parent.parent
        prompts_root_raw = os.environ.get(
            self.DNA_PROMPTS_ROOT_ENV,
            str(repo_root / "system" / "prompts"),
        )
        prompts_dir = Path(str(prompts_root_raw)).expanduser().resolve()
        try:
            configured = get_immutable_dna_locked_prompts()
        except Exception:
            configured = []

        rows: List[str] = []
        for item in configured:
            text = str(item or "").strip()
            if not text:
                continue
            resolved_path = text
            try:
                resolved = resolve_prompt_registry_entry(
                    prompt_name=text,
                    prompts_dir=prompts_dir,
                )
                candidate = str(resolved.get("relative_path") or text).strip() or text
                candidate_path = (prompts_dir / candidate).resolve()
                legacy_path = (prompts_dir / text).resolve()
                if candidate_path.exists() or not legacy_path.exists():
                    resolved_path = candidate
                else:
                    resolved_path = text
            except Exception:
                resolved_path = text
            if resolved_path and resolved_path not in rows:
                rows.append(resolved_path)
        if rows:
            return rows
        return list(self.DNA_REQUIRED_FILES_DEFAULT)

    def _is_dna_runtime_system_message(self, message: Dict[str, Any]) -> bool:
        if str(message.get("role") or "") != "system":
            return False
        content = message.get("content")
        return isinstance(content, str) and content.startswith(self.DNA_RUNTIME_HEADER)

    def _inject_immutable_dna(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not self._immutable_dna_enabled:
            return [dict(item) for item in messages]

        loader = self._ensure_immutable_dna_loader()
        if loader is None:
            raise PermissionError("immutable DNA runtime injection loader unavailable")

        payload = loader.inject()
        dna_text = str(payload.get("dna_text") or "").strip()
        dna_hash = str(payload.get("dna_hash") or "").strip()
        if not dna_text:
            raise PermissionError("immutable DNA runtime injection payload is empty")

        system_prompt = (
            f"{self.DNA_RUNTIME_HEADER}\n"
            f"dna_hash={dna_hash}\n"
            f"{dna_text}"
        )
        sanitized_messages: List[Dict[str, Any]] = []
        for item in messages:
            if not isinstance(item, dict):
                continue
            if self._is_dna_runtime_system_message(item):
                continue
            sanitized_messages.append(dict(item))
        return [{"role": "system", "content": system_prompt}, *sanitized_messages]

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
            if protocol == self.PROTOCOL_OPENAI_CHAT and cfg.api.base_url:
                # Keep existing behavior for OpenAI-compatible providers.
                effective_base = cfg.api.base_url
                normalized_google_base = self._normalize_google_openai_compat_base(effective_base)
                if normalized_google_base:
                    effective_base = normalized_google_base
                if "openai.com" not in (effective_base or ""):
                    litellm.api_base = effective_base.rstrip("/") + "/"

            self._initialized = True
            logger.info("LLM service initialized")
        except Exception as e:
            logger.error("LLM service init failed: %s", e)
            self._initialized = False

    def _normalize_protocol(self, protocol: Optional[str]) -> str:
        value = (protocol or "").strip().lower()
        if value in {"openai_chat_completions", "openai", "openai_compatible"}:
            return self.PROTOCOL_OPENAI_CHAT
        if value in {"google", "gemini"}:
            # Gemini now uses OpenAI-compatible endpoints by default.
            return self.PROTOCOL_OPENAI_CHAT
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
            return self.PROTOCOL_OPENAI_CHAT

        cfg = get_config()
        configured_protocol = getattr(cfg.api, "protocol", "")
        if configured_protocol and not self._is_auto_protocol(configured_protocol):
            return self._normalize_protocol(configured_protocol)

        # In auto mode, Gemini endpoints are treated as OpenAI-compatible.
        # This keeps function-calling behavior consistent across providers.
        base = (api_base or cfg.api.base_url or "").strip().lower()
        if "generativelanguage.googleapis.com" in base:
            return self.PROTOCOL_OPENAI_CHAT

        configured_provider = getattr(cfg.api, "provider", "").strip().lower()
        if configured_provider in self.OPENAI_HINTS:
            return self.PROTOCOL_OPENAI_CHAT
        if configured_provider in self.GOOGLE_HINTS:
            return self.PROTOCOL_OPENAI_CHAT

        return self.PROTOCOL_OPENAI_CHAT

    def _get_config_extra_headers(self) -> Dict[str, Any]:
        cfg = get_config()
        raw_headers = getattr(cfg.api, "extra_headers", None)
        if isinstance(raw_headers, dict):
            return {str(k): v for k, v in raw_headers.items()}
        return {}

    def _get_config_extra_body(self) -> Dict[str, Any]:
        cfg = get_config()
        raw_body = getattr(cfg.api, "extra_body", None)
        if isinstance(raw_body, dict):
            return {str(k): v for k, v in raw_body.items()}
        return {}

    def _filter_extra_headers_for_protocol(self, protocol: str, extra_headers: Dict[str, Any]) -> Dict[str, Any]:
        if not extra_headers:
            return {}
        return dict(extra_headers)

    def _filter_extra_body_for_protocol(self, protocol: str, extra_body: Dict[str, Any]) -> Dict[str, Any]:
        if not extra_body:
            return {}

        filtered: Dict[str, Any] = {}
        for key, value in extra_body.items():
            key_str = str(key)
            key_lower = key_str.strip().lower()
            if key_lower in self.LEGACY_GOOGLE_ONLY_EXTRA_BODY_KEYS:
                continue
            filtered[key_str] = value
        return filtered

    def _normalize_google_openai_compat_base(self, raw_base_url: Optional[str]) -> Optional[str]:
        base_input = (raw_base_url or "").strip()
        if not base_input:
            return None

        parsed = urlparse(base_input if "://" in base_input else f"https://{base_input}")
        host = (parsed.netloc or "").strip()
        if "generativelanguage.googleapis.com" not in host.lower():
            return base_input.rstrip("/")

        scheme = parsed.scheme or "https"
        path = (parsed.path or "").strip().rstrip("/")
        lowered_path = path.lower()

        models_idx = lowered_path.find("/models/")
        if models_idx != -1:
            path = path[:models_idx]
            lowered_path = path.lower()

        for suffix in ("/openai/chat/completions", "/chat/completions", "/completions"):
            if lowered_path.endswith(suffix):
                path = path[: -len(suffix)]
                lowered_path = path.lower()
                break

        if lowered_path.endswith("/openai"):
            path = path[: -len("/openai")]
            lowered_path = path.lower()

        if "/v1alpha" in lowered_path:
            version_path = "/v1alpha"
        elif "/v1beta" in lowered_path:
            version_path = "/v1beta"
        elif lowered_path.endswith("/v1") or "/v1/" in lowered_path:
            version_path = "/v1"
        else:
            version_path = "/v1beta"

        return f"{scheme}://{host}{version_path}/openai"

    def _get_model_name(self, model: Optional[str] = None, base_url: Optional[str] = None) -> str:
        """Get LiteLLM-style model identifier for OpenAI-compatible flow."""
        cfg = get_config()
        model = model or cfg.api.model
        base_url = (base_url or cfg.api.base_url or "").lower()

        if "/" in model:
            return model

        if "deepseek" in base_url and not model.startswith("deepseek/"):
            return f"deepseek/{model}"
        if "openrouter" in base_url and not model.startswith("openrouter/"):
            return f"openrouter/{model}"
        if not model.startswith("openai/"):
            return f"openai/{model}"
        return model

    @staticmethod
    def _infer_custom_provider_from_model(model_name: str) -> Optional[str]:
        lowered = (model_name or "").strip().lower()
        if lowered.startswith("openai/"):
            return "openai"
        if lowered.startswith("openrouter/"):
            return "openrouter"
        if lowered.startswith("deepseek/"):
            return "deepseek"
        if lowered.startswith("gemini/") or lowered.startswith("google/"):
            return "google"
        return None

    def _normalize_openai_params_for_model(
        self,
        model_name: str,
        temperature: Optional[float],
    ) -> tuple[Optional[float], Dict[str, Any]]:
        """
        Normalize OpenAI-compatible params for model-specific constraints.

        Notes:
        - GPT-5 family currently supports only temperature=1.
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

    def _build_reasoning_effort_params(
        self,
        *,
        model_name: str,
        reasoning_effort: Optional[str],
    ) -> Dict[str, Any]:
        intensity = str(reasoning_effort or "").strip().lower()
        if intensity not in {"low", "medium", "high", "xhigh"}:
            return {}
        lowered_model = str(model_name or "").strip().lower()
        if "gpt-5" not in lowered_model:
            return {}
        return {"reasoning_effort": intensity}

    @staticmethod
    def _resolve_reasoning_effort(
        *,
        config_api: Any,
        override_value: Optional[str] = None,
    ) -> str:
        for candidate in (
            override_value,
            getattr(config_api, "reasoning_effort", None),
            getattr(config_api, "thinking_intensity", None),
        ):
            normalized = str(candidate or "").strip().lower()
            if normalized in {"low", "medium", "high", "xhigh"}:
                return normalized
            if normalized in {"", "auto", "default"}:
                continue
        return "medium"

    def _get_litellm_params(
        self,
        api_key: Optional[str],
        api_base: Optional[str],
    ) -> Dict[str, Any]:
        """Build LiteLLM params for OpenAI-compatible flow."""
        cfg = get_config()
        extra_body = self._filter_extra_body_for_protocol(self.PROTOCOL_OPENAI_CHAT, self._get_config_extra_body())

        params: Dict[str, Any] = {}
        params["api_key"] = api_key or cfg.api.api_key
        base = api_base or cfg.api.base_url
        normalized_google_base = self._normalize_google_openai_compat_base(base)
        if normalized_google_base:
            base = normalized_google_base
        params["api_base"] = base.rstrip("/") + "/" if base else None

        if extra_body:
            params["extra_body"] = extra_body

        extra_headers = self._filter_extra_headers_for_protocol(self.PROTOCOL_OPENAI_CHAT, self._get_config_extra_headers())
        if extra_headers:
            params["extra_headers"] = extra_headers

        return params

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
        reasoning_effort_override: Optional[str] = None,
    ) -> LLMResponse:
        if not self._initialized:
            self._initialize_client()
            if not self._initialized:
                return LLMResponse(content="LLM service unavailable: client init failed")

        cfg = get_config()
        final_model = model_override or cfg.api.model
        final_base = api_base_override or cfg.api.base_url
        final_api_key = api_key_override or cfg.api.api_key

        try:
            prepared_messages = self._inject_immutable_dna(messages)
        except Exception as e:
            safe_error = self._sanitize_litellm_error_text(e)
            logger.error("Immutable DNA runtime injection failed: %s", safe_error)
            return LLMResponse(content=f"Chat call blocked: {safe_error}")

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
            resolved_reasoning_effort = self._resolve_reasoning_effort(
                config_api=cfg.api,
                override_value=reasoning_effort_override,
            )
            reasoning_effort_params = self._build_reasoning_effort_params(
                model_name=model_name,
                reasoning_effort=resolved_reasoning_effort,
            )
            provider_override = self._infer_custom_provider_from_model(model_name)
            provider_params: Dict[str, Any] = {}
            if provider_override:
                provider_params["custom_llm_provider"] = provider_override

            response = await acompletion(
                model=model_name,
                messages=prepared_messages,
                temperature=normalized_temperature,
                max_tokens=cfg.api.max_tokens if hasattr(cfg.api, "max_tokens") else None,
                **compat_params,
                **reasoning_effort_params,
                **provider_params,
                **self._get_litellm_params(final_api_key, final_base),
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

        exc_name = type(error).__name__.lower()
        exc_module = type(error).__module__.lower()
        # Some provider/client stacks raise timeout/connection errors with empty str(error).
        if any(marker in exc_name for marker in ("timeout", "connectionerror", "connecterror", "readerror")):
            return True
        if exc_module.startswith(("httpx", "httpcore")) and any(
            marker in exc_name for marker in ("connect", "read", "write", "network", "protocol")
        ):
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
            error_type = type(error).__name__ if error is not None else "UnknownError"
            args = getattr(error, "args", ())
            arg_text = " | ".join(str(item).strip() for item in args if str(item).strip())
            return f"{error_type}: {arg_text}" if arg_text else f"{error_type}: empty error message"

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

    @staticmethod
    def _describe_exception(error: Any) -> str:
        """Build a structured exception summary for internal logs."""
        if error is None:
            return "UnknownError"
        exc_type = type(error)
        name = f"{exc_type.__module__}.{exc_type.__name__}"
        raw = str(error).strip()
        if raw:
            return f"{name}: {raw}"
        args = getattr(error, "args", ())
        arg_text = " | ".join(str(item).strip() for item in args if str(item).strip())
        if arg_text:
            return f"{name}: {arg_text}"
        return f"{name}: <empty message>"

    async def stream_chat_with_context(
        self,
        messages: List[Dict],
        temperature: float = 0.7,
        model_override: Optional[Dict[str, Any]] = None,
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

        if model_override:
            final_model = model_override.get("model") or cfg.api.model
            final_base = model_override.get("api_base") or cfg.api.base_url
            final_api_key = model_override.get("api_key") or cfg.api.api_key
            final_provider_hint = str(model_override.get("provider") or "").strip()
            final_protocol_override = str(model_override.get("protocol") or "").strip()
            final_reasoning_effort_override = str(
                model_override.get("reasoning_effort") or model_override.get("thinking_intensity") or ""
            ).strip()
        else:
            final_model = cfg.api.model
            final_base = cfg.api.base_url
            final_api_key = cfg.api.api_key
            final_provider_hint = ""
            final_protocol_override = ""
            final_reasoning_effort_override = ""

        try:
            prepared_messages = self._inject_immutable_dna(messages)
        except Exception as e:
            safe_error = self._sanitize_litellm_error_text(e)
            logger.error("Immutable DNA runtime injection failed: %s", safe_error)
            yield self._format_sse_chunk("error", f"Chat call blocked: {safe_error}")
            return

        for attempt in range(max_attempts):
            try:
                protocol = self._resolve_protocol(
                    provider_hint=final_provider_hint or None,
                    api_base=final_base,
                    protocol_override=final_protocol_override or None,
                )
                if protocol != self.PROTOCOL_OPENAI_CHAT:
                    logger.warning("Unsupported protocol override=%s, fallback to openai_chat_completions", protocol)

                normalized_provider_hint = (final_provider_hint or "").strip().lower()
                if normalized_provider_hint and normalized_provider_hint not in {"openai", "openai_compatible", "auto"}:
                    model_name = str(final_model or "").strip()
                    if model_name and "/" not in model_name:
                        model_name = f"{normalized_provider_hint}/{model_name}"
                else:
                    model_name = self._get_model_name(model=final_model, base_url=final_base)
                llm_params = self._get_litellm_params(final_api_key, final_base)
                timeout_seconds = getattr(cfg.api, "request_timeout", 120)
                normalized_temperature, compat_params = self._normalize_openai_params_for_model(
                    model_name=model_name,
                    temperature=temperature,
                )
                resolved_reasoning_effort = self._resolve_reasoning_effort(
                    config_api=cfg.api,
                    override_value=final_reasoning_effort_override,
                )
                reasoning_effort_params = self._build_reasoning_effort_params(
                    model_name=model_name,
                    reasoning_effort=resolved_reasoning_effort,
                )
                provider_override = self._infer_custom_provider_from_model(model_name)
                provider_params: Dict[str, Any] = {}
                if provider_override:
                    provider_params["custom_llm_provider"] = provider_override

                logger.debug(
                    "[LLM] attempt=%s api_base=%s model=%s",
                    attempt,
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
                    messages=prepared_messages,
                    temperature=normalized_temperature,
                    max_tokens=cfg.api.max_tokens if hasattr(cfg.api, "max_tokens") else None,
                    stream=True,
                    timeout=timeout_seconds,
                    stream_timeout=timeout_seconds,
                    num_retries=0,
                    **compat_params,
                    **reasoning_effort_params,
                    **request_kwargs,
                    **provider_params,
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
                        yield self._format_sse_chunk("tool_calls", finalized_calls)
                return

            except litellm.AuthenticationError as e:
                logger.error("LLM authentication failed: attempt=%s", attempt)
                safe_error = self._sanitize_litellm_error_text(e)
                yield self._format_sse_chunk("error", f"LLM authentication failed: {safe_error}")
                return

            except Exception as e:
                is_retryable = self._is_retryable_stream_exception(e)
                safe_error = self._sanitize_litellm_error_text(e)
                detailed_error = self._describe_exception(e)

                if attempt < max_attempts - 1:
                    issue_kind = "connection issue" if is_retryable else "unexpected error"
                    logger.warning(
                        "Streaming call %s (attempt %s/%s), retrying: %s (%s)",
                        issue_kind,
                        attempt + 1,
                        max_attempts,
                        safe_error,
                        detailed_error,
                    )
                    await asyncio.sleep(1 + attempt)
                    continue

                if is_retryable:
                    logger.error(
                        "Streaming connection issue exhausted after %s attempts: %s (%s)",
                        max_attempts,
                        safe_error,
                        detailed_error,
                    )
                    yield self._format_sse_chunk(
                        "content",
                        f"Streaming call error (connection issue after {max_attempts} retries): {safe_error}",
                    )
                    return

                logger.exception(
                    "Streaming chat failed after %s attempts: %s (%s)",
                    max_attempts,
                    safe_error,
                    detailed_error,
                )
                yield self._format_sse_chunk(
                    "content",
                    f"Streaming call error (unexpected issue after {max_attempts} retries): {safe_error}",
                )
                return

    def _format_sse_chunk(self, chunk_type: str, text: Any) -> str:
        data = {"type": chunk_type, "text": text}
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


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
