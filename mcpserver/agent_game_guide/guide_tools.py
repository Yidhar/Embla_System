from __future__ import annotations

from typing import Any

from guide_engine import GuideRequest, get_guide_service
from guide_engine.models import get_guide_engine_settings


class GuideTools:
    def __init__(self) -> None:
        self.guide_service = get_guide_service()

    async def ask_guide(
        self,
        query: str,
        game_id: str | None = None,
        server_id: str | None = None,
        images: list[str] | None = None,
        auto_screenshot: bool | None = None,
        history: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        settings = get_guide_engine_settings()
        use_auto_screenshot = settings.auto_screenshot_on_guide if auto_screenshot is None else auto_screenshot

        request = GuideRequest(
            content=query,
            game_id=game_id,
            server_id=server_id,
            images=images or [],
            auto_screenshot=use_auto_screenshot,
            history=history or [],
        )
        result = await self.guide_service.ask(request)
        return {
            "status": "ok",
            "response": result.content,
            "query_mode": result.query_mode,
            "references": [item.model_dump() for item in result.references],
            "metadata": result.metadata,
        }

    async def ask_guide_with_screenshot(
        self,
        query: str,
        game_id: str | None = None,
        server_id: str | None = None,
        images: list[str] | None = None,
        history: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return await self.ask_guide(
            query=query,
            game_id=game_id,
            server_id=server_id,
            images=images,
            auto_screenshot=True,
            history=history,
        )

    async def calculate_damage(self, query: str, game_id: str | None = None) -> dict[str, Any]:
        enhanced_query = f"请进行伤害计算：{query}"
        return await self.ask_guide(query=enhanced_query, game_id=game_id, auto_screenshot=False)

    async def get_team_recommendation(self, query: str, game_id: str | None = None) -> dict[str, Any]:
        enhanced_query = f"请给出配队建议：{query}"
        return await self.ask_guide(query=enhanced_query, game_id=game_id, auto_screenshot=True)
