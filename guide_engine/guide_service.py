from __future__ import annotations

import logging
import re
from typing import Any

from .calculation_service import CalculationParams, get_calculation_service
from .chroma_service import ChromaService
from .kantai_calculation_service import KantaiCalcParams, KantaiCalculationService
from .models import GuideReference, GuideRequest, GuideResponse, get_guide_engine_settings
from .neo4j_service import Neo4jService
from .prompt_manager import PromptManager
from .query_router import QueryMode, RouteResult, get_query_router
from .screenshot_provider import get_screenshot_provider


logger = logging.getLogger("GuideService")


class GuideService:
    GAME_ID_DISPLAY_MAP: dict[str, str] = {
        "arknights": "明日方舟",
        "wuthering-waves": "鸣潮",
        "honkai-star-rail": "崩坏：星穹铁道",
        "genshin-impact": "原神",
        "zenless-zone-zero": "绝区零",
        "punishing-gray-raven": "战双帕弥什",
        "uma-musume": "赛马娘",
        "kantai-collection": "舰队Collection",
    }

    GAME_ID_ALIAS_MAP: dict[str, str] = {
        "明日方舟": "arknights",
        "arknights": "arknights",
        "鸣潮": "wuthering-waves",
        "wuthering waves": "wuthering-waves",
        "wuthering-waves": "wuthering-waves",
        "崩坏星穹铁道": "honkai-star-rail",
        "星穹铁道": "honkai-star-rail",
        "star rail": "honkai-star-rail",
        "honkai star rail": "honkai-star-rail",
        "honkai-star-rail": "honkai-star-rail",
        "原神": "genshin-impact",
        "genshin": "genshin-impact",
        "genshin impact": "genshin-impact",
        "genshin-impact": "genshin-impact",
        "绝区零": "zenless-zone-zero",
        "zzz": "zenless-zone-zero",
        "zenless zone zero": "zenless-zone-zero",
        "zenless-zone-zero": "zenless-zone-zero",
        "战双帕弥什": "punishing-gray-raven",
        "pgr": "punishing-gray-raven",
        "punishing gray raven": "punishing-gray-raven",
        "punishing-gray-raven": "punishing-gray-raven",
        "赛马娘": "uma-musume",
        "uma musume": "uma-musume",
        "uma-musume": "uma-musume",
        "舰队collection": "kantai-collection",
        "舰c": "kantai-collection",
        "舰队收藏": "kantai-collection",
        "kantai collection": "kantai-collection",
        "kantai-collection": "kantai-collection",
    }

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
                    "source": shot.source,
                }
            except Exception as exc:
                metadata["auto_screenshot_error"] = str(exc)

        resolved_game_id = await self._resolve_request_game_id(request, images, metadata)
        effective_request = request.model_copy(update={"game_id": resolved_game_id})

        prompt_config = self.prompt_manager.get_prompt_config(resolved_game_id)
        route: RouteResult = self.router.route_sync(request.content)
        rag_context, references = await self._retrieve_context(effective_request, route, prompt_config)
        llm_content = await self._generate_answer(
            request=effective_request,
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

    async def _resolve_request_game_id(
        self,
        request: GuideRequest,
        images: list[str],
        metadata: dict[str, Any],
    ) -> str:
        raw_game_id = (request.game_id or "").strip()
        if raw_game_id:
            normalized = self.prompt_manager.normalize_game_id(raw_game_id)
            metadata["resolved_game_id"] = normalized
            metadata["game_id_source"] = "request"
            logger.info("[GuideService] game_id from request: %s -> %s", raw_game_id, normalized)
            return normalized

        detected_game_id = None
        detect_raw_response = ""
        if images:
            try:
                detected_game_id, detect_raw_response = await self._detect_game_id_from_images(images)
                metadata["game_id_detect_raw"] = detect_raw_response[:500]
            except Exception as exc:
                metadata["game_id_detect_error"] = str(exc)
                logger.warning("[GuideService] game_id detect failed: %s", exc)

        if detected_game_id:
            metadata["resolved_game_id"] = detected_game_id
            metadata["game_id_source"] = "vision_detected"
            logger.info("[GuideService] game_id detected from vision: %s", detected_game_id)
            return detected_game_id

        fallback_game_id = "arknights"
        metadata["resolved_game_id"] = fallback_game_id
        metadata["game_id_source"] = "fallback_default"
        if images:
            logger.warning(
                "[GuideService] game_id fallback to default=%s (vision detect not resolved)", fallback_game_id
            )
        else:
            logger.info("[GuideService] no game_id and no images, fallback=%s", fallback_game_id)
        return fallback_game_id

    async def _detect_game_id_from_images(self, images: list[str]) -> tuple[str | None, str]:
        from apiserver.llm_service import get_llm_service

        llm_service = get_llm_service()
        settings = get_guide_engine_settings()
        supported_game_ids = self._iter_supported_game_ids()
        mapping_lines = [
            f"- {game_id} -> {self.GAME_ID_DISPLAY_MAP.get(game_id, game_id)}" for game_id in supported_game_ids
        ]
        mapping_text = "\n".join(mapping_lines)

        prompt = (
            "你是游戏识别器。请根据截图判断游戏。"
            "下面是 game_id 到游戏名的对照表：\n"
            f"{mapping_text}\n"
            "输出规则：\n"
            "1) 回答里必须包含一个 game_id（直接写 game_id 即可）\n"
            "2) 可以包含其他解释文本\n"
            "3) 若无法判断，输出 unknown\n"
            "注意：请确保 game_id 原样出现在回复中。"
        )

        user_blocks: list[dict[str, Any]] = [{"type": "text", "text": "请识别这张截图对应的游戏。"}]
        for image in images:
            user_blocks.append({"type": "image_url", "image_url": {"url": image}})

        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_blocks},
        ]

        response = await llm_service.chat_with_context_and_reasoning_with_overrides(
            messages=messages,
            model_override=settings.vision_api_model,
            api_key_override=settings.vision_api_key,
            api_base_override=settings.vision_api_base_url,
        )
        raw_content = response.content or ""
        detected = self._extract_game_id_from_response(raw_content, supported_game_ids)
        return detected, raw_content

    def _extract_game_id_from_response(self, text: str, supported_game_ids: list[str]) -> str | None:
        normalized_text = (text or "").strip()
        if not normalized_text:
            return None

        normalized_lower = normalized_text.lower()
        if normalized_lower == "unknown":
            return None

        # 最高优先级：只要回复中包含任一合法 game_id（in 匹配），即视为识别成功
        for game_id in sorted(supported_game_ids, key=len, reverse=True):
            if game_id.lower() in normalized_lower:
                return game_id

        first_line = normalized_text.splitlines()[0].strip() if normalized_text else ""
        direct = self._resolve_candidate_game_id(first_line, supported_game_ids)
        if direct:
            return direct

        for token in re.findall(r"[a-z][a-z0-9\-]{2,}", normalized_text.lower()):
            resolved = self._resolve_candidate_game_id(token, supported_game_ids)
            if resolved:
                return resolved

        lowered = normalized_text.lower()
        for alias, mapped_game_id in sorted(
            self.GAME_ID_ALIAS_MAP.items(), key=lambda item: len(item[0]), reverse=True
        ):
            if alias.lower() in lowered and mapped_game_id in supported_game_ids:
                return mapped_game_id

        return None

    def _resolve_candidate_game_id(self, candidate: str, supported_game_ids: list[str]) -> str | None:
        cleaned = candidate.strip().strip("`\"'")
        if not cleaned:
            return None

        normalized = self.prompt_manager.normalize_game_id(cleaned)
        if normalized in supported_game_ids:
            return normalized

        lowered = cleaned.lower()
        mapped = self.GAME_ID_ALIAS_MAP.get(lowered)
        if mapped and mapped in supported_game_ids:
            return mapped

        id_token_match = re.search(r"[a-z][a-z0-9\-]{2,}", lowered)
        if id_token_match:
            token = self.prompt_manager.normalize_game_id(id_token_match.group(0))
            if token in supported_game_ids:
                return token

        return None

    @staticmethod
    def _iter_supported_game_ids() -> list[str]:
        game_ids = sorted(set(ChromaService.GAME_ID_MAP.keys()))
        if "arknights" not in game_ids:
            game_ids.append("arknights")
        return game_ids

    async def _retrieve_context(
        self,
        request: GuideRequest,
        route: RouteResult,
        prompt_config: dict[str, Any],
    ) -> tuple[str, list[GuideReference]]:
        game_id = (request.game_id or "arknights").strip() or "arknights"
        retrieval_config = prompt_config.get("retrieval_config", {})
        top_k = int(retrieval_config.get("top_k", 5))
        score_threshold = float(retrieval_config.get("score_threshold", 0.5))
        search_mode = self._resolve_search_mode(game_id, route.mode, request.content)

        context_parts: list[str] = []
        references: list[GuideReference] = []

        try:
            docs = await self.chroma.search(
                game_id=game_id,
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
        game_id = (request.game_id or "arknights").strip() or "arknights"
        if route.mode != QueryMode.CALCULATION:
            return ""

        if game_id == "arknights":
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

        if game_id == "kantai-collection":
            calc_service = KantaiCalculationService(self.neo4j)
            result = await calc_service.calculate_from_text(
                KantaiCalcParams(game_id=game_id, query_text=request.content)
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
