from __future__ import annotations

from typing import Any

from .calculation_service import CalculationParams, get_calculation_service
from .chroma_service import ChromaService
from .kantai_calculation_service import KantaiCalcParams, KantaiCalculationService
from .models import GuideReference, GuideRequest, GuideResponse, get_guide_engine_settings
from .neo4j_service import Neo4jService
from .prompt_manager import PromptManager
from .query_router import QueryMode, RouteResult, get_query_router
from .screenshot_provider import get_screenshot_provider


class GuideService:
    def __init__(
        self,
        chroma_service: ChromaService | None = None,
        neo4j_service: Neo4jService | None = None,
        prompt_manager: PromptManager | None = None,
    ) -> None:
        self.chroma = chroma_service or ChromaService()
        self.neo4j = neo4j_service or Neo4jService()
        self.prompt_manager = prompt_manager or PromptManager()
        self.router = get_query_router()

    async def ask(self, request: GuideRequest) -> GuideResponse:
        settings = get_guide_engine_settings()
        if not settings.enabled:
            return GuideResponse(content="攻略引擎当前已禁用", query_mode="full", references=[], metadata={})

        images: list[str] = list(request.images)
        metadata: dict[str, Any] = {}
        if request.auto_screenshot:
            try:
                shot = get_screenshot_provider().capture_data_url()
                images.append(shot.data_url)
                metadata["auto_screenshot"] = {
                    "width": shot.width,
                    "height": shot.height,
                    "monitor_index": shot.monitor_index,
                }
            except Exception as exc:
                metadata["auto_screenshot_error"] = str(exc)

        prompt_config = self.prompt_manager.get_prompt_config(request.game_id)
        route: RouteResult = self.router.route_sync(request.content)
        rag_context, references = await self._retrieve_context(request, route, prompt_config)
        llm_content = await self._generate_answer(
            request=request,
            prompt_config=prompt_config,
            rag_context=rag_context,
            images=images,
        )

        return GuideResponse(
            content=llm_content,
            query_mode=route.mode.value,
            references=references,
            metadata=metadata,
        )

    async def _retrieve_context(
        self,
        request: GuideRequest,
        route: RouteResult,
        prompt_config: dict[str, Any],
    ) -> tuple[str, list[GuideReference]]:
        retrieval_config = prompt_config.get("retrieval_config", {})
        top_k = int(retrieval_config.get("top_k", 5))
        score_threshold = float(retrieval_config.get("score_threshold", 0.5))
        search_mode = self._resolve_search_mode(request.game_id, route.mode, request.content)

        context_parts: list[str] = []
        references: list[GuideReference] = []

        try:
            docs = await self.chroma.search(
                game_id=request.game_id,
                query=request.content,
                top_k=top_k,
                score_threshold=score_threshold,
                search_mode=search_mode,
            )
        except Exception:
            docs = []

        for doc in docs:
            title = str(doc.get("title", "相关内容"))
            content = str(doc.get("content", ""))
            context_parts.append(f"### {title}\n{content}")
            references.append(
                GuideReference(
                    type="document",
                    title=title,
                    source=str(doc.get("source_url", "")),
                    score=float(doc.get("score", 0.0)),
                )
            )

        calc_context = await self._build_calculation_context(request, route, docs)
        if calc_context:
            context_parts.insert(0, calc_context)
            references.append(GuideReference(type="calculation", title="计算服务", source="guide_engine"))

        return "\n\n---\n\n".join(context_parts), references

    async def _build_calculation_context(
        self,
        request: GuideRequest,
        route: RouteResult,
        docs: list[dict[str, Any]],
    ) -> str:
        if route.mode != QueryMode.CALCULATION:
            return ""

        if request.game_id == "arknights":
            operator_name = self._guess_operator_name(route, docs)
            if not operator_name:
                return ""
            params = CalculationParams(
                operator_name=operator_name,
                skill_index=route.entities.skill_index if route.entities.skill_index is not None else 2,
                skill_level=route.entities.get_final_skill_level(),
                elite=route.entities.elite if route.entities.elite is not None else 2,
                level=90,
                trust=route.entities.trust if route.entities.trust is not None else 200,
                potential=route.entities.potential if route.entities.potential is not None else 5,
                enemy_defense=route.entities.enemy_defense if route.entities.enemy_defense is not None else 0,
                enemy_res=route.entities.enemy_res if route.entities.enemy_res is not None else 0,
            )
            result = get_calculation_service().calculate(params)
            if not result:
                return ""
            return get_calculation_service().format_result(result)

        if request.game_id == "kantai-collection":
            calc_service = KantaiCalculationService(self.neo4j)
            result = await calc_service.calculate_from_text(
                KantaiCalcParams(game_id=request.game_id, query_text=request.content)
            )
            return calc_service.format_result(result)

        return ""

    async def _generate_answer(
        self,
        request: GuideRequest,
        prompt_config: dict[str, Any],
        rag_context: str,
        images: list[str],
    ) -> str:
        from apiserver.llm_service import get_llm_service

        llm_service = get_llm_service()
        settings = get_guide_engine_settings()
        system_prompt = str(prompt_config.get("system_prompt", ""))

        user_text = request.content
        if rag_context:
            user_text = f"{request.content}\n\n[参考上下文]\n{rag_context}"

        user_content: Any = user_text
        if images:
            blocks: list[dict[str, Any]] = [{"type": "text", "text": user_text}]
            for image in images:
                blocks.append({"type": "image_url", "image_url": {"url": image}})
            user_content = blocks

        messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
        for item in request.history:
            role = item.get("role")
            content = item.get("content")
            if isinstance(role, str) and content is not None:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": user_content})

        if images:
            llm_response = await llm_service.chat_with_context_and_reasoning_with_overrides(
                messages=messages,
                model_override=settings.vision_api_model,
                api_key_override=settings.vision_api_key,
                api_base_override=settings.vision_api_base_url,
            )
        else:
            llm_response = await llm_service.chat_with_context_and_reasoning(messages)
        return llm_response.content

    @staticmethod
    def _resolve_search_mode(game_id: str, mode: QueryMode, query: str) -> str:
        if mode in (QueryMode.WIKI_ONLY, QueryMode.CALCULATION):
            if game_id == "kantai-collection":
                enemy_keywords = ["深海", "敌", "敌人", "敌舰", "敌船", "栖", "栖姬", "栖鬼", "boss", "Boss", "BOSS"]
                if mode == QueryMode.WIKI_ONLY and any(keyword in query for keyword in enemy_keywords):
                    return "enemy_only"
            return "wiki_only"
        return "full"

    @staticmethod
    def _guess_operator_name(route: RouteResult, docs: list[dict[str, Any]]) -> str | None:
        if route.entities.operator_names:
            return route.entities.operator_names[0]
        for doc in docs:
            title = str(doc.get("title", ""))
            if " - " in title:
                return title.split(" - ", 1)[0].strip() or None
        return None


_guide_service: GuideService | None = None


def get_guide_service() -> GuideService:
    global _guide_service
    if _guide_service is None:
        _guide_service = GuideService()
    return _guide_service
