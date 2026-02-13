#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import base64
import importlib
import json
import os
from pathlib import Path
from typing import Any

from apiserver.agentic_tool_loop import execute_tool_calls
from mcpserver.mcp_registry import auto_register_mcp, get_registered_services


_GEMINI_PATCHED: bool = False


def _is_truthy_env(env_name: str) -> bool:
    raw_value = os.getenv(env_name, "")
    value = raw_value.strip().lower()
    return value in {"1", "true", "yes", "on"}


def _decode_data_url(data_url: str) -> tuple[str, bytes]:
    if not data_url.startswith("data:"):
        raise ValueError("不是 data URL")

    header, encoded = data_url.split(",", 1)
    if ";base64" not in header:
        raise ValueError("仅支持 base64 data URL")

    mime_type = header[5:].split(";", 1)[0].strip()
    if not mime_type:
        raise ValueError("data URL 缺少 mime_type")

    payload = base64.b64decode(encoded, validate=True)
    return mime_type, payload


def _guess_mime_by_suffix(file_path: Path) -> str:
    suffix = file_path.suffix.lower()
    mapping: dict[str, str] = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
    }
    mime_type = mapping.get(suffix)
    if mime_type is None:
        raise ValueError(f"不支持的图片后缀: {suffix}")
    return mime_type


def _image_ref_to_bytes(image_ref: str) -> tuple[str, bytes]:
    try:
        return _decode_data_url(image_ref)
    except Exception:
        pass

    maybe_path = Path(image_ref).expanduser()
    if maybe_path.exists() and maybe_path.is_file():
        mime_type = _guess_mime_by_suffix(maybe_path)
        return mime_type, maybe_path.read_bytes()

    raise ValueError("仅支持 data URL 或本地图片路径")


def _enable_gemini_vision_override_if_needed() -> None:
    global _GEMINI_PATCHED
    if _GEMINI_PATCHED:
        return
    if not _is_truthy_env("GEMINI"):
        return

    try:
        genai = importlib.import_module("google.genai")
        types = importlib.import_module("google.genai.types")
    except Exception as exc:
        raise RuntimeError("GEMINI=True 但未安装 google-genai，请执行: uv add --group test google-genai") from exc

    from guide_engine.guide_service import GuideService
    from guide_engine.models import get_guide_engine_settings

    original_generate_answer = GuideService._generate_answer

    def _get_gemini_runtime() -> tuple[str, str, str | None]:
        settings = get_guide_engine_settings()
        model_name = (settings.game_guide_llm_api_model or "").strip()
        api_key = (settings.game_guide_llm_api_key or "").strip()
        custom_base = (settings.game_guide_llm_api_base_url or "").strip() or None
        if not model_name:
            raise RuntimeError("GEMINI=True 但 game_guide_llm_api_model 为空")
        if not api_key:
            raise RuntimeError("GEMINI=True 但 game_guide_llm_api_key 为空")
        return model_name, api_key, custom_base

    async def _call_gemini_with_contents(contents: list[Any]) -> str:
        model_name, api_key, custom_base = _get_gemini_runtime()
        client_kwargs: dict[str, Any] = {"api_key": api_key}
        if custom_base:
            client_kwargs["http_options"] = {"base_url": custom_base}

        client = genai.Client(**client_kwargs)
        async_client = client.aio
        try:
            response = await async_client.models.generate_content(model=model_name, contents=contents)
            text = getattr(response, "text", None)
            if isinstance(text, str) and text.strip():
                return text
            return str(response)
        finally:
            await async_client.aclose()

    async def _generate_answer_with_gemini(
        self: Any,
        request: Any,
        prompt_config: dict[str, Any],
        rag_context: str,
        images: list[str],
    ) -> str:
        if not images:
            return await original_generate_answer(self, request, prompt_config, rag_context, images)

        user_text = request.content
        if rag_context:
            user_text = f"{request.content}\n\n[参考上下文]\n{rag_context}"

        contents: list[Any] = []
        system_prompt = str(prompt_config.get("system_prompt", "")).strip()
        if system_prompt:
            contents.append(system_prompt)
        contents.append(user_text)

        for image_ref in images:
            mime_type, image_bytes = _image_ref_to_bytes(image_ref)
            contents.append(types.Part.from_bytes(data=image_bytes, mime_type=mime_type))

        return await _call_gemini_with_contents(contents)

    async def _detect_game_id_from_images_with_gemini(
        self: Any,
        images: list[str],
    ) -> tuple[str | None, str]:
        supported_game_ids = self._iter_supported_game_ids()
        display_map = getattr(self, "GAME_ID_DISPLAY_MAP", {})
        mapping_lines = [f"- {game_id} -> {display_map.get(game_id, game_id)}" for game_id in supported_game_ids]
        mapping_text = "\n".join(mapping_lines)

        contents: list[Any] = [
            (
                "你是游戏识别器。请根据截图判断游戏。"
                "下面是 game_id 到游戏名的对照表：\n"
                f"{mapping_text}\n"
                "输出规则：\n"
                "1) 回答里必须包含一个 game_id（直接写 game_id 即可）\n"
                "2) 可以包含其他解释文本\n"
                "3) 不能判断时输出 unknown\n"
                "注意：请确保 game_id 原样出现在回复中。"
            ),
            "请识别这张截图对应的游戏。",
        ]

        for image_ref in images:
            mime_type, image_bytes = _image_ref_to_bytes(image_ref)
            contents.append(types.Part.from_bytes(data=image_bytes, mime_type=mime_type))

        raw_content = await _call_gemini_with_contents(contents)
        detected_game_id = self._extract_game_id_from_response(raw_content, supported_game_ids)
        return detected_game_id, raw_content

    GuideService._generate_answer = _generate_answer_with_gemini
    GuideService._detect_game_id_from_images = _detect_game_id_from_images_with_gemini
    _GEMINI_PATCHED = True
    print("[INFO] GEMINI=True，已启用测试脚本内置 Gemini 视觉调用通道（含游戏识别）")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="从工具调用层测试 game_guide")
    parser.add_argument(
        "--game-id",
        default="",
        help="游戏 ID（可选，不传则不下发 game_id，让服务自动识别）",
    )
    parser.add_argument("--query", default="这关怎么打", help="测试问题")
    parser.add_argument(
        "--tool-name",
        default="ask_guide",
        choices=["ask_guide", "ask_guide_with_screenshot", "calculate_damage", "get_team_recommendation"],
        help="要测试的工具名",
    )
    parser.add_argument(
        "--test-pic",
        default="/home/pyl/ttt1.jpg",
        help="测试图片路径；为空字符串表示不设置 TEST_PIC_PATH",
    )
    parser.add_argument("--session-id", default="guide-tool-test", help="模拟会话 ID")
    return parser.parse_args()


def _ensure_test_pic(test_pic: str) -> None:
    if not test_pic:
        os.environ.pop("TEST_PIC_PATH", None)
        return

    pic_path = Path(test_pic).expanduser().resolve()
    if not pic_path.exists() or not pic_path.is_file():
        raise FileNotFoundError(f"测试图片不存在: {pic_path}")
    os.environ["TEST_PIC_PATH"] = str(pic_path)


def _build_tool_call(args: argparse.Namespace) -> dict[str, Any]:
    tool_call: dict[str, Any] = {
        "agentType": "mcp",
        "tool_name": str(args.tool_name),
        "query": str(args.query),
    }
    game_id = str(args.game_id).strip()
    if game_id:
        tool_call["game_id"] = game_id
    return tool_call


async def _run_once(args: argparse.Namespace) -> int:
    _ensure_test_pic(str(args.test_pic))
    _enable_gemini_vision_override_if_needed()

    auto_register_mcp()
    services = get_registered_services()
    print(f"已注册服务: {services}")
    if "game_guide" not in services:
        print("[FAIL] 未注册 game_guide")
        return 2

    tool_call = _build_tool_call(args)
    print(f"工具调用入参: {json.dumps(tool_call, ensure_ascii=False)}")
    results = await execute_tool_calls([tool_call], session_id=str(args.session_id))

    if not results:
        print("[FAIL] execute_tool_calls 无返回")
        return 3

    result_item = results[0]
    print(f"工具层结果状态: {result_item.get('status')}")
    print(f"工具层路由服务: {result_item.get('service_name')}")

    raw_payload = result_item.get("result", "")
    if not isinstance(raw_payload, str):
        print(f"[FAIL] result 不是字符串: {type(raw_payload)}")
        return 4

    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError:
        print("[FAIL] result 不是合法 JSON")
        print(raw_payload)
        return 5

    status = payload.get("status")
    metadata = payload.get("metadata", {})
    query_mode = payload.get("query_mode")
    response_text = str(payload.get("response", ""))

    print(f"业务状态: {status}")
    print(f"query_mode: {query_mode}")
    print(f"metadata: {json.dumps(metadata, ensure_ascii=False)}")
    if isinstance(metadata, dict):
        print(f"resolved_game_id: {metadata.get('resolved_game_id')}")
        print(f"game_id_source: {metadata.get('game_id_source')}")
    print(f"response: {response_text}")

    if status != "ok":
        print("[FAIL] 业务返回 status 非 ok")
        print(f"payload: {json.dumps(payload, ensure_ascii=False)}")
        return 6

    auto_screenshot = metadata.get("auto_screenshot") if isinstance(metadata, dict) else None
    auto_screenshot_error = metadata.get("auto_screenshot_error") if isinstance(metadata, dict) else None

    if args.tool_name in {"ask_guide", "ask_guide_with_screenshot", "get_team_recommendation"}:
        if auto_screenshot is None and auto_screenshot_error is None:
            print("[FAIL] 未看到 auto_screenshot 或 auto_screenshot_error")
            return 7

    expected_test_pic = str(args.test_pic).strip()
    if expected_test_pic and isinstance(auto_screenshot, dict):
        source = auto_screenshot.get("source")
        if source != "env:TEST_PIC_PATH":
            print(f"[FAIL] 期望 source=env:TEST_PIC_PATH，实际: {source}")
            return 8

    print("[PASS] 从工具调用层到 game_guide 的链路测试通过")
    return 0


def main() -> None:
    args = parse_args()
    exit_code = asyncio.run(_run_once(args))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
