"""MCP Playwright automation agent."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Dict

from system.config import get_config


class PlaywrightMasterAgent:
    """Browser automation agent powered by Playwright."""

    name = "Playwright Master Agent"

    def __init__(self) -> None:
        config = get_config()
        self._headless = bool(getattr(config.browser, "playwright_headless", True))
        self._repo_root = Path(__file__).resolve().parents[2]
        self._artifact_dir = self._repo_root / "scratch" / "artifacts" / "playwright"
        self._artifact_dir.mkdir(parents=True, exist_ok=True)

    async def handle_handoff(self, task: Dict[str, Any]) -> str:
        tool_name = str(task.get("tool_name") or "").strip().lower()
        tool_aliases = {
            "open_url": "open_url",
            "navigate": "open_url",
            "screenshot_page": "screenshot_page",
            "screenshot": "screenshot_page",
            "extract_text": "extract_text",
            "page_text": "extract_text",
        }
        action = tool_aliases.get(tool_name)
        if not action:
            return self._json_error(
                "未知工具，仅支持 open_url/screenshot_page/extract_text",
                tool_name=tool_name,
            )

        url = str(task.get("url") or task.get("link") or "").strip()
        if not url:
            return self._json_error("缺少 url 参数", tool_name=tool_name)
        if not re.match(r"^https?://", url, re.IGNORECASE):
            return self._json_error("url 仅支持 http/https", tool_name=tool_name)

        timeout_seconds = self._parse_timeout_seconds(task.get("timeout_seconds"))
        selector = str(task.get("selector") or "").strip()
        max_chars = self._parse_max_chars(task.get("max_chars"))
        full_page = bool(task.get("full_page", True))
        output_path = self._resolve_output_path(task.get("output_path"))

        try:
            result = await self._execute_action(
                action=action,
                url=url,
                timeout_seconds=timeout_seconds,
                selector=selector,
                max_chars=max_chars,
                full_page=full_page,
                output_path=output_path,
            )
            return json.dumps(
                {
                    "status": "ok",
                    "message": "浏览器自动化执行完成",
                    "data": result,
                },
                ensure_ascii=False,
            )
        except ModuleNotFoundError as exc:
            if "playwright" in str(exc):
                return self._json_error(
                    "playwright 未安装，请先安装并执行 playwright install",
                    tool_name=tool_name,
                )
            return self._json_error(str(exc), tool_name=tool_name)
        except Exception as exc:
            return self._json_error(str(exc), tool_name=tool_name)

    async def _execute_action(
        self,
        *,
        action: str,
        url: str,
        timeout_seconds: float,
        selector: str,
        max_chars: int,
        full_page: bool,
        output_path: Path,
    ) -> Dict[str, Any]:
        from playwright.async_api import async_playwright

        timeout_ms = int(timeout_seconds * 1000)
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=self._headless)
            context = await browser.new_context(viewport={"width": 1280, "height": 720})
            page = await context.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                title = await page.title()
                final_url = page.url

                if action == "open_url":
                    data = {
                        "action": action,
                        "url": url,
                        "final_url": final_url,
                        "title": title,
                    }
                elif action == "screenshot_page":
                    await page.screenshot(path=str(output_path), full_page=full_page)
                    data = {
                        "action": action,
                        "url": url,
                        "final_url": final_url,
                        "title": title,
                        "screenshot_path": str(output_path).replace("\\", "/"),
                    }
                else:
                    if selector:
                        text = await page.locator(selector).first.inner_text(timeout=timeout_ms)
                    else:
                        text = await page.text_content("body") or ""
                    compact_text = re.sub(r"\s+", " ", text).strip()
                    truncated = False
                    if len(compact_text) > max_chars:
                        compact_text = compact_text[:max_chars]
                        truncated = True
                    data = {
                        "action": action,
                        "url": url,
                        "final_url": final_url,
                        "title": title,
                        "selector": selector,
                        "text": compact_text,
                        "text_length": len(compact_text),
                        "truncated": truncated,
                    }
            finally:
                await context.close()
                await browser.close()

        return data

    def _resolve_output_path(self, output_path: Any) -> Path:
        filename = str(output_path or "").strip()
        safe_name = Path(filename).name if filename else f"screenshot_{int(time.time() * 1000)}.png"
        if not safe_name.lower().endswith(".png"):
            safe_name = f"{safe_name}.png"
        return self._artifact_dir / safe_name

    @staticmethod
    def _parse_timeout_seconds(value: Any) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return 30.0
        return max(1.0, min(180.0, parsed))

    @staticmethod
    def _parse_max_chars(value: Any) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return 8000
        return max(200, min(200000, parsed))

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
