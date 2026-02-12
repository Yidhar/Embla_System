from __future__ import annotations

import json
from typing import Any

from .guide_tools import GuideTools


class GameGuideAgent:
    name = "GameGuide Agent"

    def __init__(self) -> None:
        self.tools = GuideTools()

    async def handle_handoff(self, task: dict[str, Any]) -> str:
        try:
            tool_name = str(task.get("tool_name") or "").strip()
            if not tool_name:
                return json.dumps({"status": "error", "message": "缺少tool_name参数", "data": {}}, ensure_ascii=False)

            query = str(task.get("query") or task.get("content") or task.get("message") or "").strip()
            game_id = str(task.get("game_id") or "arknights")
            server_id = task.get("server_id")
            images = task.get("images")
            history = task.get("history")
            if not isinstance(images, list):
                images = []
            if not isinstance(history, list):
                history = []

            if tool_name in ("ask_guide", "ask_guide_with_screenshot"):
                auto_screenshot_value = task.get("auto_screenshot")
                auto_screenshot: bool | None = None
                if isinstance(auto_screenshot_value, bool):
                    auto_screenshot = auto_screenshot_value
                data = await self.tools.ask_guide(
                    query=query,
                    game_id=game_id,
                    server_id=server_id if isinstance(server_id, str) else None,
                    images=[str(item) for item in images],
                    auto_screenshot=auto_screenshot,
                    history=[item for item in history if isinstance(item, dict)],
                )
            elif tool_name == "calculate_damage":
                data = await self.tools.calculate_damage(query=query, game_id=game_id)
            elif tool_name == "get_team_recommendation":
                data = await self.tools.get_team_recommendation(query=query, game_id=game_id)
            else:
                return json.dumps(
                    {
                        "status": "error",
                        "message": f"未知工具: {tool_name}。可用工具: ask_guide, ask_guide_with_screenshot, calculate_damage, get_team_recommendation",
                        "data": {},
                    },
                    ensure_ascii=False,
                )

            return json.dumps(data, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"status": "error", "message": str(exc), "data": {}}, ensure_ascii=False)
