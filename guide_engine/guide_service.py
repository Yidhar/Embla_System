from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from .calculation_service import CalculationParams, CalculationResult, get_calculation_service
from .gamedata_loader import get_gamedata_loader
from .kantai_calculation_service import KantaiCalcParams, KantaiCalculationService
from .models import GuideReference, GuideRequest, GuideResponse, get_guide_engine_settings
from .neo4j_service import Neo4jService
from .prompt_manager import PromptManager
from .query_router import QueryMode, RouteResult, get_query_router
from .screenshot_provider import get_screenshot_provider
from .neo4j_service import Neo4jService


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
        neo4j_service: Neo4jService | None = None,
        prompt_manager: PromptManager | None = None,
    ) -> None:
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
        if request.force_query_mode:
            mode = QueryMode(request.force_query_mode)
            entities = self.router.extract_entities(request.content)
            route = RouteResult(mode=mode, reason="force_query_mode", entities=entities)
        else:
            route = self.router.route_sync(request.content)
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
            model_override=settings.game_guide_llm_api_model,
            api_key_override=settings.game_guide_llm_api_key,
            api_base_override=settings.game_guide_llm_api_base_url,
            provider_hint=settings.game_guide_llm_api_type,
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
        game_ids = sorted(set(GuideService.GAME_ID_DISPLAY_MAP.keys()))
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
        graph_rag_enabled = prompt_config.get("graph_rag_enabled", False)

        context_parts: list[str] = []
        references: list[GuideReference] = []

        # Kantai FULL 模式地图校验
        map_hint = self._check_kantai_map_requirement(game_id, route.mode, request.content)
        if map_hint:
            context_parts.append(map_hint)

        # ---- 构建并行任务 ----
        task_keys: list[str] = []
        tasks: list[Any] = []

        # 1. Neo4j 干员/配合查询（仅 graph_rag_enabled 时）
        operator_names: list[str] = []
        if graph_rag_enabled:
            operator_names = self._extract_operator_names_for_graph(request.content, route, prompt_config)
            for name in operator_names:
                task_keys.append(f"neo4j_op_{name}")
                tasks.append(self.neo4j.get_operator(game_id, name))
            # synergy 关系当前未导入种子数据，暂时跳过查询以避免无效警告
            # if operator_names:
            #     task_keys.append(f"neo4j_syn_{operator_names[0]}")
            #     tasks.append(self.neo4j.get_operator_synergies(game_id, operator_names[0]))

        # ---- 并行执行 ----
        results = await asyncio.gather(*tasks, return_exceptions=True)
        result_map: dict[str, Any] = dict(zip(task_keys, results))

        # ---- 处理 Neo4j 干员结果 ----
        for name in operator_names:
            op_data = result_map.get(f"neo4j_op_{name}")
            if isinstance(op_data, dict):
                context_parts.append(self._format_operator_context(op_data))
                references.append(GuideReference(
                    type="operator",
                    title=f"干员: {op_data.get('name', name)}",
                    source="knowledge_graph",
                ))

        # ---- 处理 Neo4j 配合结果 ----
        if operator_names:
            syn_data = result_map.get(f"neo4j_syn_{operator_names[0]}")
            if isinstance(syn_data, list) and syn_data:
                syn_text = self._format_synergy_context(operator_names[0], syn_data)
                if syn_text:
                    context_parts.append(syn_text)

        # ---- 计算上下文 ----
        calc_context = await self._build_calculation_context(request, route, [], prompt_config)
        if calc_context:
            context_parts.insert(0, calc_context)
            references.append(GuideReference(type="calculation", title="计算服务", source="guide_engine"))

        return "\n\n---\n\n".join(context_parts), references

    # ---- Neo4j 格式化辅助 ----

    @staticmethod
    def _format_operator_context(operator: dict[str, Any]) -> str:
        """格式化干员信息为上下文文本"""
        lines = [
            f"## 干员信息: {operator.get('name', '未知')}",
            f"- 稀有度: {operator.get('rarity', 0)}星",
            f"- 职业: {operator.get('class', '未知')}",
            f"- 分支: {operator.get('branch', '未知')}",
            f"- 特性: {operator.get('trait', '无')}",
            f"- 获取方式: {operator.get('obtain', '未知')}",
        ]
        tags = operator.get("tags", [])
        if tags:
            lines.append(f"- 标签: {', '.join(tags)}")

        skills = operator.get("skills", [])
        if skills:
            lines.append("\n### 技能")
            for i, skill in enumerate(skills, 1):
                if isinstance(skill, dict) and skill.get("name"):
                    lines.append(f"{i}技能 - {skill.get('name')}")
                    if skill.get("type"):
                        lines.append(f"  类型: {skill['type']}")
                    if skill.get("charge_type"):
                        lines.append(f"  回复方式: {skill['charge_type']}")
                    if skill.get("description"):
                        lines.append(f"  描述: {skill['description']}")
                    if skill.get("mastery_recommendation"):
                        lines.append(f"  专精建议: {skill['mastery_recommendation']}")

        talents = operator.get("talents", [])
        if talents:
            lines.append("\n### 天赋")
            for talent in talents:
                if isinstance(talent, dict) and talent.get("name"):
                    lines.append(f"{talent.get('name')}: {talent.get('description', '')}")

        return "\n".join(lines)

    @staticmethod
    def _format_synergy_context(operator_name: str, synergies: list[dict[str, Any]]) -> str:
        """格式化配合推荐"""
        if not synergies:
            return ""
        lines = [f"## {operator_name} 的配合推荐"]
        for syn in synergies:
            partner = syn.get("name", syn.get("name_en", "未知"))
            reason = syn.get("synergy_reason", "")
            score = syn.get("synergy_score", 0)
            lines.append(f"- {partner}（推荐度 {score}/10）: {reason}")
        return "\n".join(lines)

    @staticmethod
    def _check_kantai_map_requirement(game_id: str, mode: QueryMode, query: str) -> str:
        """舰C FULL 模式检查地图/海域是否缺失，缺失时返回追问提示"""
        if game_id != "kantai-collection" or mode != QueryMode.FULL:
            return ""
        map_patterns = [
            r"(?<!\d)[1-7]-[1-5](?!\d)",
            r"(?<![A-Za-z])E-?\d+(?!\d)",
            r"(海域|关卡)[^\s，,。]{0,6}",
        ]
        if any(re.search(pat, query, re.IGNORECASE) for pat in map_patterns):
            return ""
        return (
            "【流程要求】这是攻略模式且未给出具体关卡/海域，"
            "请先反问用户想打哪个图/海域（例如 2-5、3-2、E-3）。"
            "在得到关卡前不要给阵容与配装结论。"
        )

    async def _build_calculation_context(
        self,
        request: GuideRequest,
        route: RouteResult,
        docs: list[dict[str, Any]],
        prompt_config: dict[str, Any],
    ) -> str:
        game_id = (request.game_id or "arknights").strip() or "arknights"
        if route.mode != QueryMode.CALCULATION:
            return ""

        if game_id == "arknights":
            aliases = prompt_config.get("entity_patterns", {}).get("operator_aliases", {})
            operator_name = self._guess_operator_name(route, docs, request.content, operator_aliases=aliases)
            if not operator_name:
                return ""

            # 自动选择模组：取第一个模组，level=3
            loader = get_gamedata_loader()
            char = loader.get_character(operator_name)
            module_id: str | None = None
            module_level: int = 0
            if char:
                modules = loader.get_character_modules(char.char_id)
                if modules:
                    module_id = modules[0].uniequip_id
                    module_level = 3
                    logger.info("[GuideService] auto module: %s Lv.%d", modules[0].uniequip_name, module_level)

            params = CalculationParams(
                operator_name=operator_name,
                skill_index=route.entities.skill_index if route.entities.skill_index is not None else 2,
                skill_level=route.entities.get_final_skill_level(),
                elite=route.entities.elite if route.entities.elite is not None else 2,
                level=90,
                trust=route.entities.trust if route.entities.trust is not None else 200,
                potential=route.entities.potential if route.entities.potential is not None else 5,
                module_id=module_id,
                module_level=module_level,
                enemy_defense=route.entities.enemy_defense if route.entities.enemy_defense is not None else 0,
                enemy_res=route.entities.enemy_res if route.entities.enemy_res is not None else 0,
            )
            result = get_calculation_service().calculate(params)
            if not result:
                return ""
            return self._format_detailed_calculation(result, params)

        if game_id == "kantai-collection":
            calc_service = KantaiCalculationService(self.neo4j)
            result = await calc_service.calculate_from_text(
                KantaiCalcParams(game_id=game_id, query_text=request.content)
            )
            return calc_service.format_result(result)

        return ""

    @staticmethod
    def _format_detailed_calculation(result: CalculationResult, params: CalculationParams) -> str:
        """格式化详细计算结果（含基础属性、信赖/模组加成、计算步骤）"""
        loader = get_gamedata_loader()
        char = loader.get_character(params.operator_name)

        lines: list[str] = [
            f"【精确计算结果】{result.operator_name} - {result.skill_name}（{result.skill_level_str}）",
            "",
            "计算假设：",
            f"- 精英{params.elite} Lv.{params.level}，信赖{params.trust}%，潜能{params.potential}",
            f"- 敌人防御{params.enemy_defense}，法抗{params.enemy_res}%",
        ]

        # 干员基础属性
        if char:
            phase = char.get_phase_attrs(params.elite, params.level)
            if phase:
                lines.append("")
                lines.append(f"干员基础属性（精英{params.elite} Lv.{params.level}）：")
                lines.append(f"- 基础攻击力: {phase.atk}")
                lines.append(f"- 防御力: {phase.defense}")
                lines.append(f"- 生命值: {phase.max_hp}")
                lines.append(f"- 基础攻击间隔: {phase.base_attack_time}秒")
                lines.append(f"- 阻挡数: {phase.block_cnt}")

            # 信赖加成
            trust_bonus = char.get_trust_bonus(params.trust)
            if trust_bonus:
                parts: list[str] = []
                if trust_bonus.get("atk"):
                    parts.append(f"攻击力+{trust_bonus['atk']:.0f}")
                if trust_bonus.get("defense"):
                    parts.append(f"防御力+{trust_bonus['defense']:.0f}")
                if trust_bonus.get("max_hp"):
                    parts.append(f"生命值+{trust_bonus['max_hp']:.0f}")
                if parts:
                    lines.append(f"- 信赖加成（{params.trust}%）：{'，'.join(parts)}")

            # 模组加成
            if params.module_id and params.module_level > 0:
                mod = loader.get_module(params.module_id)
                if mod and params.module_level <= len(mod.levels):
                    mod_lv = mod.levels[params.module_level - 1]
                    mod_parts: list[str] = []
                    if mod_lv.attributes.get("atk"):
                        mod_parts.append(f"攻击力+{mod_lv.attributes['atk']:.0f}")
                    if mod_lv.attributes.get("max_hp"):
                        mod_parts.append(f"生命值+{mod_lv.attributes['max_hp']:.0f}")
                    if mod_lv.attributes.get("defense"):
                        mod_parts.append(f"防御力+{mod_lv.attributes['defense']:.0f}")
                    if mod_lv.attributes.get("attack_speed"):
                        mod_parts.append(f"攻速+{mod_lv.attributes['attack_speed']:.0f}")
                    label = f"{mod.uniequip_name} Lv.{params.module_level}"
                    if mod_parts:
                        lines.append(f"- 模组：{label}（{'，'.join(mod_parts)}）")
                    else:
                        lines.append(f"- 模组：{label}")

        # 计算后面板
        lines.append("")
        lines.append("计算后面板：")
        lines.append(f"- 最终攻击力: {result.final_atk:.0f}（包含信赖、天赋、技能加成）")
        lines.append(f"- 攻击间隔: {result.final_attack_interval:.3f}秒（攻速{result.final_attack_speed:.0f}）")
        lines.append(f"- 单次伤害: {result.damage_per_hit:.0f}（{result.damage_type.value}伤害）")
        lines.append(f"- DPS: {result.dps:.0f}")

        # 技能数据
        if result.skill_duration > 0:
            lines.append("")
            lines.append("技能数据：")
            lines.append(f"- SP消耗: {result.sp_cost}，初始SP: {result.init_sp}")
            lines.append(f"- 持续时间: {result.skill_duration}秒")
            lines.append(f"- 技能总伤: {result.total_skill_damage:.0f}")
            if result.final_attack_interval > 0:
                attack_count = result.skill_duration / result.final_attack_interval
                lines.append(f"- 技能期间约{attack_count:.1f}次攻击")

        # 计算步骤
        if result.calculation_steps:
            lines.append("")
            lines.append("计算详情：")
            for step in result.calculation_steps:
                lines.append(f"- {step}")

        return "\n".join(lines)

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
                model_override=settings.game_guide_llm_api_model,
                api_key_override=settings.game_guide_llm_api_key,
                api_base_override=settings.game_guide_llm_api_base_url,
                provider_hint=settings.game_guide_llm_api_type,
            )
        else:
            llm_response = await llm_service.chat_with_context_and_reasoning_with_overrides(
                messages=messages,
                model_override=settings.game_guide_llm_api_model,
                api_key_override=settings.game_guide_llm_api_key,
                api_base_override=settings.game_guide_llm_api_base_url,
                provider_hint=settings.game_guide_llm_api_type,
            )
        return llm_response.content

    @staticmethod
    def _guess_operator_name(
        route: RouteResult,
        docs: list[dict[str, Any]],
        query: str = "",
        operator_aliases: dict[str, list[str]] | None = None,
    ) -> str | None:
        if route.entities.operator_names:
            return route.entities.operator_names[0]

        # 优先从 prompt config 的别名表匹配
        if query and operator_aliases:
            for canonical, aliases in operator_aliases.items():
                if canonical in query:
                    return canonical
                for alias in aliases:
                    if alias in query:
                        return canonical

        # 从查询文本中匹配已知干员名（按名字长度降序，优先匹配长名）
        if query:
            loader = get_gamedata_loader()
            loader.load()
            known_names = sorted(loader._name_mapping.keys(), key=len, reverse=True)
            for name in known_names:
                if name in query:
                    return name

        for doc in docs:
            title = str(doc.get("title", ""))
            if " - " in title:
                return title.split(" - ", 1)[0].strip() or None
        return None

    @staticmethod
    def _extract_operator_names_for_graph(
        query: str,
        route: RouteResult,
        prompt_config: dict[str, Any],
    ) -> list[str]:
        """合并 route.entities、prompt aliases、GameDataLoader 三个来源提取干员名（最多3个）"""
        names: list[str] = []

        # 来源1：路由实体
        if route.entities.operator_names:
            names.extend(route.entities.operator_names)

        # 来源2：prompt config 别名
        aliases = prompt_config.get("entity_patterns", {}).get("operator_aliases", {})
        for canonical, alias_list in aliases.items():
            if canonical in query:
                if canonical not in names:
                    names.append(canonical)
            else:
                for alias in alias_list:
                    if alias in query:
                        if canonical not in names:
                            names.append(canonical)
                        break

        # 来源3：GameDataLoader 已知干员名
        loader = get_gamedata_loader()
        loader.load()
        known_names = sorted(loader._name_mapping.keys(), key=len, reverse=True)
        for name in known_names:
            if name in query and name not in names:
                names.append(name)

        return names[:3]


_guide_service: GuideService | None = None


def get_guide_service() -> GuideService:
    global _guide_service
    if _guide_service is None:
        _guide_service = GuideService()
    return _guide_service
