"""MCP vision agent for image metadata inspection and lightweight Q&A."""

from __future__ import annotations

import base64
import hashlib
import json
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


class VisionAgent:
    """Inspect local/base64 images and return structured metadata."""

    name = "Vision Agent"

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
            answer = ""
            question = str(task.get("question") or "").strip()
            if action == "image_qa":
                answer = self._answer_question(question=question, metadata=metadata)

            payload = {
                "status": "ok",
                "message": "图像分析完成",
                "data": {
                    "action": action,
                    "metadata": metadata,
                    "question": question,
                    "answer": answer,
                },
            }
            return json.dumps(payload, ensure_ascii=False)
        except Exception as exc:
            return self._json_error(str(exc), tool_name=tool_name)

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

        return "当前提供的是元数据级视觉分析，如需语义级视觉问答可接入多模态模型。"

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
