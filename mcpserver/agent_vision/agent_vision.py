"""MCP vision agent with OpenAI-compatible multimodal Q&A."""

from __future__ import annotations

import base64
import hashlib
import json
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.event_bus import EventStore
from system.config import get_config, logger


_VISION_EVENT_STORE: Optional[EventStore] = None


class VisionAgent:
    """Inspect local/base64 images and answer questions with multimodal LLM."""

    name = "Vision Agent"

    def __init__(self) -> None:
        cfg = get_config()
        api_cfg = getattr(cfg, "api", None)
        request_timeout = getattr(api_cfg, "request_timeout", 60) if api_cfg is not None else 60
        try:
            self._default_timeout_seconds = max(1.0, min(600.0, float(request_timeout)))
        except (TypeError, ValueError):
            self._default_timeout_seconds = 60.0

    async def handle_handoff(self, task: Dict[str, Any]) -> str:
        tool_name = str(task.get("tool_name") or "").strip().lower()
        tool_aliases = {
            "inspect_image": "inspect_image",
            "analyze_image": "inspect_image",
            "image_qa": "image_qa",
            "vision_qa": "image_qa",
        }
        action = tool_aliases.get(tool_name)
        if not action:
            return self._json_error("未知工具，仅支持 inspect_image/image_qa", tool_name=tool_name)

        try:
            image_bytes, source = self._resolve_image_bytes(task)
        except Exception as exc:
            return self._json_error(str(exc), tool_name=tool_name)

        try:
            metadata = self._analyze_image(image_bytes=image_bytes, source=source)
            payload_data: Dict[str, Any] = {
                "action": action,
                "metadata": metadata,
            }

            if action == "image_qa":
                question = str(task.get("question") or "").strip()
                answer = ""
                qa_mode = "metadata_fallback"
                llm_error = ""
                llm_usage: Dict[str, int] = {}
                llm_runtime = self._resolve_multimodal_runtime(task)
                fallback_reason = "llm_unavailable"

                if question and llm_runtime is not None:
                    try:
                        answer, llm_usage = await self._ask_multimodal_qa(
                            question=question,
                            image_bytes=image_bytes,
                            metadata=metadata,
                            runtime=llm_runtime,
                        )
                        qa_mode = "multimodal_llm"
                        fallback_reason = ""
                    except Exception as exc:
                        llm_error = self._sanitize_error_text(str(exc), secret=llm_runtime.get("api_key", ""))
                        fallback_reason = "llm_error"
                        answer = self._answer_question(question=question, metadata=metadata)
                else:
                    answer = self._answer_question(question=question, metadata=metadata)

                payload_data.update(
                    {
                        "question": question,
                        "answer": answer,
                        "qa_mode": qa_mode,
                        "llm_enabled": llm_runtime is not None,
                        "llm_model": str((llm_runtime or {}).get("model") or ""),
                        "llm_base_url": str((llm_runtime or {}).get("base_url") or ""),
                        "llm_usage": llm_usage,
                        "llm_error": llm_error,
                    }
                )

                self._emit_observability_event(
                    qa_mode=qa_mode,
                    fallback_reason=fallback_reason,
                    question=question,
                    answer=answer,
                    metadata=metadata,
                    runtime=llm_runtime,
                    llm_error=llm_error,
                    task=task,
                )

            payload = {
                "status": "ok",
                "message": "图像分析完成",
                "data": payload_data,
            }
            return json.dumps(payload, ensure_ascii=False)
        except Exception as exc:
            return self._json_error(str(exc), tool_name=tool_name)

    def _emit_observability_event(
        self,
        *,
        qa_mode: str,
        fallback_reason: str,
        question: str,
        answer: str,
        metadata: Dict[str, Any],
        runtime: Optional[Dict[str, Any]],
        llm_error: str,
        task: Dict[str, Any],
    ) -> None:
        store = self._get_event_store()
        if store is None:
            return

        payload = {
            "session_id": str(task.get("session_id") or ""),
            "execution_session_id": str(task.get("execution_session_id") or ""),
            "question_length": len(question),
            "answer_length": len(answer),
            "qa_mode": qa_mode,
            "fallback_reason": fallback_reason,
            "llm_enabled": runtime is not None,
            "model": str((runtime or {}).get("model") or ""),
            "base_url": str((runtime or {}).get("base_url") or ""),
            "image_source": str(metadata.get("source") or ""),
            "image_format": str(metadata.get("format") or ""),
            "image_width": metadata.get("width"),
            "image_height": metadata.get("height"),
            "llm_error": llm_error,
        }

        event_type = "VisionMultimodalQAFallback"
        severity = "warning"
        if qa_mode == "multimodal_llm":
            event_type = "VisionMultimodalQASucceeded"
            severity = "info"
        elif fallback_reason == "llm_error":
            event_type = "VisionMultimodalQAError"
            severity = "warning"

        try:
            store.emit(
                event_type,
                payload,
                source="mcpserver.agent_vision",
                severity=severity,
            )
        except Exception as exc:
            logger.debug("VisionAgent event emit failed: %s", exc)

    @staticmethod
    def _get_event_store() -> Optional[EventStore]:
        global _VISION_EVENT_STORE
        if _VISION_EVENT_STORE is not None:
            return _VISION_EVENT_STORE
        try:
            event_file = Path(__file__).resolve().parents[2] / "logs" / "autonomous" / "events.jsonl"
            _VISION_EVENT_STORE = EventStore(file_path=event_file)
        except Exception as exc:
            logger.debug("VisionAgent event store init failed: %s", exc)
            return None
        return _VISION_EVENT_STORE

    def _resolve_image_bytes(self, task: Dict[str, Any]) -> Tuple[bytes, str]:
        image_path = str(task.get("image_path") or task.get("path") or "").strip()
        if image_path:
            path = Path(image_path).expanduser()
            if not path.is_absolute():
                path = (Path(__file__).resolve().parents[2] / path).resolve()
            if not path.exists() or not path.is_file():
                raise ValueError("image_path 不存在或不是文件")
            return path.read_bytes(), str(path).replace("\\", "/")

        image_base64 = str(task.get("image_base64") or "").strip()
        if image_base64:
            if "," in image_base64 and image_base64.lower().startswith("data:"):
                image_base64 = image_base64.split(",", 1)[1]
            try:
                data = base64.b64decode(image_base64, validate=True)
            except Exception as exc:
                raise ValueError(f"image_base64 非法: {exc}") from exc
            if not data:
                raise ValueError("image_base64 解码后为空")
            return data, "base64"

        raise ValueError("缺少 image_path 或 image_base64")

    def _analyze_image(self, *, image_bytes: bytes, source: str) -> Dict[str, Any]:
        sha256 = hashlib.sha256(image_bytes).hexdigest()
        byte_size = len(image_bytes)
        format_name = self._infer_format(image_bytes)

        width: Optional[int] = None
        height: Optional[int] = None
        mode = ""
        mean_luma: Optional[float] = None

        try:
            from PIL import Image, ImageStat

            with Image.open(BytesIO(image_bytes)) as image:
                width, height = image.size
                mode = str(image.mode or "")
                if not format_name:
                    format_name = str(image.format or "").lower()
                gray = image.convert("L")
                mean_luma = round(float(ImageStat.Stat(gray).mean[0]), 2)
        except Exception:
            width, height = self._infer_dimensions(image_bytes)

        return {
            "source": source,
            "sha256": sha256,
            "byte_size": byte_size,
            "format": format_name,
            "width": width,
            "height": height,
            "aspect_ratio": round(width / height, 4) if width and height else None,
            "mode": mode,
            "mean_luma": mean_luma,
        }

    def _resolve_multimodal_runtime(self, task: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        cfg = get_config()
        api_cfg = getattr(cfg, "api", None)
        cc_cfg = getattr(cfg, "computer_control", None)

        cc_enabled = bool(getattr(cc_cfg, "enabled", False))
        api_key = self._first_non_empty(
            task.get("api_key"),
            getattr(cc_cfg, "api_key", "") if cc_enabled else "",
            getattr(api_cfg, "api_key", ""),
        )
        if api_key == "sk-placeholder-key-not-set":
            api_key = ""

        model = self._first_non_empty(
            task.get("model"),
            getattr(cc_cfg, "model", "") if cc_enabled else "",
            getattr(api_cfg, "model", ""),
        )

        base_url = self._first_non_empty(
            task.get("base_url"),
            getattr(cc_cfg, "model_url", "") if cc_enabled else "",
            getattr(api_cfg, "base_url", ""),
        )

        if not api_key or not model:
            return None

        timeout_seconds = self._parse_timeout_seconds(
            task.get("timeout_seconds"),
            default_value=self._default_timeout_seconds,
        )

        max_tokens = self._parse_optional_int(task.get("max_tokens"), fallback=1024, lower=1, upper=16384)
        temperature = self._parse_optional_float(task.get("temperature"), fallback=0.2, lower=0.0, upper=2.0)

        reasoning_effort = self._first_non_empty(
            task.get("reasoning_effort"),
            task.get("thinking_intensity"),
            getattr(api_cfg, "reasoning_effort", ""),
            getattr(api_cfg, "thinking_intensity", ""),
        ).lower()
        if reasoning_effort not in {"low", "medium", "high", "xhigh"}:
            reasoning_effort = ""

        extra_headers: Dict[str, Any] = {}
        if isinstance(getattr(api_cfg, "extra_headers", None), dict):
            extra_headers = {str(k): v for k, v in getattr(api_cfg, "extra_headers", {}).items()}

        extra_body: Dict[str, Any] = {}
        if isinstance(getattr(api_cfg, "extra_body", None), dict):
            extra_body = {str(k): v for k, v in getattr(api_cfg, "extra_body", {}).items()}

        return {
            "api_key": api_key,
            "base_url": base_url,
            "model": model,
            "timeout_seconds": timeout_seconds,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "reasoning_effort": reasoning_effort,
            "extra_headers": extra_headers,
            "extra_body": extra_body,
        }

    async def _ask_multimodal_qa(
        self,
        *,
        question: str,
        image_bytes: bytes,
        metadata: Dict[str, Any],
        runtime: Dict[str, Any],
    ) -> Tuple[str, Dict[str, int]]:
        from openai import AsyncOpenAI

        image_format = str(metadata.get("format") or "").lower()
        image_mime = self._mime_from_format(image_format)
        image_base64 = base64.b64encode(image_bytes).decode("ascii")
        image_data_url = f"data:{image_mime};base64,{image_base64}"

        prompt = (
            "你是 Embla_system 的视觉分析子代理。"
            "请结合图像内容和附带元数据回答用户问题，输出简洁中文答案。"
            "\n\n[用户问题]\n"
            f"{question}"
            "\n\n[图像元数据]\n"
            f"{json.dumps(metadata, ensure_ascii=False)}"
        )

        default_headers = runtime.get("extra_headers") if isinstance(runtime.get("extra_headers"), dict) else None
        client = AsyncOpenAI(
            api_key=str(runtime.get("api_key") or ""),
            base_url=str(runtime.get("base_url") or "") or None,
            timeout=float(runtime.get("timeout_seconds") or self._default_timeout_seconds),
            default_headers=default_headers,
        )

        request_payload: Dict[str, Any] = {
            "model": str(runtime.get("model") or ""),
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": image_data_url}},
                    ],
                }
            ],
            "max_tokens": int(runtime.get("max_tokens") or 1024),
            "temperature": float(runtime.get("temperature") or 0.2),
        }

        reasoning_effort = str(runtime.get("reasoning_effort") or "").strip().lower()
        model_name = str(runtime.get("model") or "").lower()
        if reasoning_effort and "gpt-5" in model_name:
            request_payload["reasoning_effort"] = reasoning_effort

        extra_body = runtime.get("extra_body")
        if isinstance(extra_body, dict) and extra_body:
            for key, value in extra_body.items():
                if key not in request_payload:
                    request_payload[key] = value

        response = await client.chat.completions.create(**request_payload)
        answer = self._extract_text_response(response)
        if not answer:
            answer = "模型未返回可解析文本。"

        usage = self._extract_usage(response)
        return answer, usage

    @staticmethod
    def _extract_text_response(response: Any) -> str:
        choices = getattr(response, "choices", None)
        if not choices:
            return ""
        first_choice = choices[0]
        message = getattr(first_choice, "message", None)
        if message is None:
            return ""
        content = getattr(message, "content", "")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            text_parts: List[str] = []
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "text":
                        text_parts.append(str(item.get("text") or ""))
                else:
                    text = getattr(item, "text", None)
                    if text is not None:
                        text_parts.append(str(text))
            return "".join(text_parts).strip()
        return str(content or "").strip()

    @staticmethod
    def _extract_usage(response: Any) -> Dict[str, int]:
        usage = getattr(response, "usage", None)
        if usage is None:
            return {}

        prompt_tokens = VisionAgent._safe_int(getattr(usage, "prompt_tokens", None))
        completion_tokens = VisionAgent._safe_int(getattr(usage, "completion_tokens", None))
        total_tokens = VisionAgent._safe_int(getattr(usage, "total_tokens", None))

        payload: Dict[str, int] = {}
        if prompt_tokens is not None:
            payload["prompt_tokens"] = prompt_tokens
        if completion_tokens is not None:
            payload["completion_tokens"] = completion_tokens
        if total_tokens is not None:
            payload["total_tokens"] = total_tokens
        return payload

    @staticmethod
    def _safe_int(value: Any) -> Optional[int]:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed

    @staticmethod
    def _sanitize_error_text(text: str, *, secret: str) -> str:
        message = str(text or "")
        masked_secret = str(secret or "").strip()
        if masked_secret:
            message = message.replace(masked_secret, "***")
        return message

    @staticmethod
    def _first_non_empty(*values: Any) -> str:
        for value in values:
            text = str(value or "").strip()
            if text:
                return text
        return ""

    @staticmethod
    def _mime_from_format(image_format: str) -> str:
        lowered = str(image_format or "").strip().lower()
        if lowered in {"jpg", "jpeg"}:
            return "image/jpeg"
        if lowered == "png":
            return "image/png"
        if lowered == "gif":
            return "image/gif"
        if lowered == "webp":
            return "image/webp"
        if lowered == "bmp":
            return "image/bmp"
        return "image/png"

    @staticmethod
    def _infer_dimensions(image_bytes: bytes) -> Tuple[Optional[int], Optional[int]]:
        if len(image_bytes) >= 24 and image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            width = int.from_bytes(image_bytes[16:20], "big")
            height = int.from_bytes(image_bytes[20:24], "big")
            return width, height

        if len(image_bytes) >= 2 and image_bytes[0:2] == b"\xff\xd8":
            index = 2
            while index + 9 < len(image_bytes):
                if image_bytes[index] != 0xFF:
                    index += 1
                    continue
                marker = image_bytes[index + 1]
                if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
                    block_len = int.from_bytes(image_bytes[index + 2:index + 4], "big")
                    if index + block_len + 2 > len(image_bytes):
                        break
                    height = int.from_bytes(image_bytes[index + 5:index + 7], "big")
                    width = int.from_bytes(image_bytes[index + 7:index + 9], "big")
                    return width, height
                block_len = int.from_bytes(image_bytes[index + 2:index + 4], "big")
                if block_len <= 0:
                    break
                index += block_len + 2
        return None, None

    @staticmethod
    def _infer_format(image_bytes: bytes) -> str:
        if len(image_bytes) >= 8 and image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            return "png"
        if len(image_bytes) >= 2 and image_bytes.startswith(b"\xff\xd8"):
            return "jpeg"
        if len(image_bytes) >= 6 and image_bytes[:6] in {b"GIF87a", b"GIF89a"}:
            return "gif"
        if len(image_bytes) >= 12 and image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
            return "webp"
        if len(image_bytes) >= 2 and image_bytes.startswith(b"BM"):
            return "bmp"
        return ""

    @staticmethod
    def _answer_question(*, question: str, metadata: Dict[str, Any]) -> str:
        if not question:
            return ""
        text = question.lower()
        width = metadata.get("width")
        height = metadata.get("height")
        image_format = metadata.get("format")
        luma = metadata.get("mean_luma")

        if any(keyword in text for keyword in ["尺寸", "size", "宽", "高", "resolution"]):
            if width and height:
                return f"图像尺寸为 {width}x{height}。"
            return "无法解析图像尺寸。"

        if any(keyword in text for keyword in ["格式", "format", "类型"]):
            if image_format:
                return f"图像格式为 {image_format}。"
            return "无法识别图像格式。"

        if any(keyword in text for keyword in ["亮", "dark", "bright", "亮度"]):
            if luma is not None:
                return f"图像平均亮度约为 {luma}（0-255）。"
            return "当前环境无法计算亮度。"

        return "当前未接收到可用视觉模型回答，已回退到元数据级分析。"

    @staticmethod
    def _parse_timeout_seconds(value: Any, *, default_value: float) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return default_value
        return max(1.0, min(600.0, parsed))

    @staticmethod
    def _parse_optional_int(value: Any, *, fallback: int, lower: int, upper: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return fallback
        return max(lower, min(upper, parsed))

    @staticmethod
    def _parse_optional_float(value: Any, *, fallback: float, lower: float, upper: float) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return fallback
        return max(lower, min(upper, parsed))

    @staticmethod
    def _json_error(message: str, *, tool_name: str) -> str:
        return json.dumps(
            {
                "status": "error",
                "message": message,
                "tool_name": tool_name,
                "data": {},
            },
            ensure_ascii=False,
        )
