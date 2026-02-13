"""
Kantai Collection damage calculation service.

This module provides a baseline damage calculation for day/night/torpedo/ASW/radar
combat types with natural language input parsing.
"""

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple
import json
import math
import os
import re

from .neo4j_service import Neo4jService


MAX_IMPROVEMENT = 10
MAX_PROFICIENCY = 7


@dataclass
class KantaiEquipmentInput:
    name: str
    improvement: int = MAX_IMPROVEMENT
    proficiency: int = MAX_PROFICIENCY


@dataclass
class KantaiCalcParams:
    game_id: str
    query_text: str
    attacker_name: Optional[str] = None
    enemy_name: Optional[str] = None
    battle_type: Optional[str] = None  # day|night|torpedo|asw|radar


@dataclass
class KantaiCalcPayload:
    attacker: Optional[str] = None
    enemy: Optional[str] = None
    battle_type: Optional[str] = None
    formation_self: Optional[str] = None
    formation_enemy: Optional[str] = None
    engagement: Optional[str] = None
    attacker_state: Optional[str] = None
    attacker_asw: Optional[int] = None
    attack_pattern: Optional[str] = None
    equipment: List[KantaiEquipmentInput] = field(default_factory=list)


@dataclass
class KantaiCalcResult:
    supported: bool
    message: str
    attacker: Optional[Dict[str, Any]] = None
    enemy: Optional[Dict[str, Any]] = None
    battle_type: Optional[str] = None
    notes: Dict[str, Any] = field(default_factory=dict)
    raw_input: Dict[str, Any] = field(default_factory=dict)


class KantaiCalculationService:
    """
    Resolve ship/enemy entities and perform baseline damage calculation.
    """

    def __init__(self, neo4j_service: Optional[Neo4jService] = None):
        self.neo4j = neo4j_service or Neo4jService()

    async def calculate_from_text(self, params: KantaiCalcParams) -> KantaiCalcResult:
        battle_type = params.battle_type or self._infer_battle_type(params.query_text)
        payload = self._extract_payload_from_text(params.query_text)
        payload.battle_type = payload.battle_type or battle_type

        missing_fields = self._missing_fields(payload)
        if missing_fields:
            return KantaiCalcResult(
                supported=False,
                message=self._build_missing_prompt(missing_fields),
                battle_type=payload.battle_type,
                notes={"missing": missing_fields},
            )

        attacker = None
        enemy = None
        if params.attacker_name or payload.attacker:
            attacker_name = params.attacker_name or payload.attacker
            if attacker_name is not None:
                attacker = await self.neo4j.get_ship(params.game_id, attacker_name)
        else:
            attacker = await self.neo4j.find_ship_in_text(params.game_id, params.query_text)

        if params.enemy_name or payload.enemy:
            enemy_name = params.enemy_name or payload.enemy
            if enemy_name is not None:
                enemy = await self.neo4j.get_enemy_ship(params.game_id, enemy_name)
        else:
            enemy = await self.neo4j.find_enemy_in_text(params.game_id, params.query_text)

        if not attacker:
            return KantaiCalcResult(
                supported=False,
                message="未识别到攻击方舰船名称，无法进行计算。",
                battle_type=payload.battle_type,
            )
        if not enemy:
            return KantaiCalcResult(
                supported=False,
                message="未识别到敌方舰船名称，无法进行计算。",
                battle_type=payload.battle_type,
            )

        calc_notes = self._calculate_damage(attacker, enemy, payload)

        return KantaiCalcResult(
            supported=True,
            message="已完成基础伤害计算（未包含特殊攻击、地图倍率与熟练度细项）。",
            attacker=attacker,
            enemy=enemy,
            battle_type=payload.battle_type,
            raw_input={
                "attacker": payload.attacker,
                "enemy": payload.enemy,
                "battle_type": payload.battle_type,
                "formation_self": payload.formation_self,
                "formation_enemy": payload.formation_enemy,
                "engagement": payload.engagement,
                "attacker_state": payload.attacker_state,
                "attacker_asw": payload.attacker_asw,
                "attack_pattern": payload.attack_pattern,
                "equipment": [
                    {
                        "name": item.name,
                        "improvement": item.improvement,
                        "proficiency": item.proficiency,
                    }
                    for item in payload.equipment
                ],
            },
            notes=calc_notes,
        )

    def format_result(self, result: KantaiCalcResult) -> str:
        lines = ["【舰队收藏计算服务】"]
        lines.append(f"战斗类型: {result.battle_type or '未知'}")

        if result.attacker:
            lines.append(f"攻击方: {result.attacker.get('name')}")
            lines.append(f"- 舰种: {result.attacker.get('stype_name')}")
            lines.append(f"- 基础火力: {self._stat_range(result.attacker.get('houg'))}")
            lines.append(f"- 基础雷装: {self._stat_range(result.attacker.get('raig'))}")
            lines.append(f"- 基础对空: {self._stat_range(result.attacker.get('tyku'))}")

        if result.enemy:
            lines.append(f"敌方: {result.enemy.get('name')}")
            lines.append(f"- 舰种: {result.enemy.get('stype_name')}")
            lines.append(f"- 装甲: {self._stat_range(result.enemy.get('souk'))}")
            lines.append(f"- 耐久: {self._stat_range(result.enemy.get('taik'))}")

        lines.append(result.message)

        basics = result.notes.get("basic_stats")
        if basics:
            lines.append("基础面板(满改修/满熟练默认):")
            for key, value in basics.items():
                lines.append(f"- {key}: {value}")

        power = result.notes.get("power_breakdown")
        if power:
            lines.append("火力计算:")
            for key, value in power.items():
                lines.append(f"- {key}: {value}")

        damage = result.notes.get("damage_estimate")
        if damage:
            lines.append("预计伤害区间(含装甲随机):")
            for key, value in damage.items():
                lines.append(f"- {key}: {value}")

        if result.notes.get("equipment_unknown"):
            lines.append("未识别装备:")
            for name in result.notes["equipment_unknown"]:
                lines.append(f"- {name}")

        if result.notes.get("required_inputs"):
            lines.append("缺少关键输入:")
            for req in result.notes["required_inputs"]:
                lines.append(f"- {req}")

        return "\n".join(lines)

    def _infer_battle_type(self, text: str) -> str:
        mapping = {
            "夜战": "night",
            "雷击": "torpedo",
            "鱼雷": "torpedo",
            "对潜": "asw",
            "反潜": "asw",
            "昼战": "day",
            "炮击": "day",
            "雷达": "radar",
            "雷达射击": "radar",
        }
        for key, value in mapping.items():
            if key in text:
                return value
        return "day"

    def _extract_payload_from_text(self, text: str) -> KantaiCalcPayload:
        payload = KantaiCalcPayload()
        payload.attacker = self._extract_named_field(text, ["攻击方", "攻方", "我方", "友军", "自军"])
        payload.enemy = self._extract_named_field(text, ["敌方", "敌舰", "敌人", "深海"])
        payload.battle_type = self._extract_battle_type(text)
        payload.formation_self = self._extract_formation(text, ["我方阵型", "友军阵型", "自军阵型", "阵型"])
        payload.formation_enemy = self._extract_formation(text, ["敌方阵型", "敌阵"])
        payload.engagement = self._extract_engagement(text)
        payload.attacker_state = self._extract_attacker_state(text)
        payload.attacker_asw = self._extract_attacker_asw(text)
        payload.attack_pattern = self._extract_attack_pattern(text)
        payload.equipment = self._extract_equipment(text)
        return payload

    def _extract_named_field(self, text: str, keys: List[str]) -> Optional[str]:
        for key in keys:
            match = re.search(rf"{key}[:：\s]*([^\s，,。；;]+)", text)
            if match:
                return match.group(1).strip()
        return None

    def _extract_battle_type(self, text: str) -> Optional[str]:
        for key, value in {
            "昼战": "day",
            "炮击": "day",
            "夜战": "night",
            "雷击": "torpedo",
            "鱼雷": "torpedo",
            "对潜": "asw",
            "反潜": "asw",
            "雷达射击": "radar",
            "雷达": "radar",
        }.items():
            if key in text:
                return value
        return None

    def _extract_formation(self, text: str, keys: List[str]) -> Optional[str]:
        formation_alias = {
            "单纵": "line_ahead",
            "单纵阵": "line_ahead",
            "复纵": "double_line",
            "复纵阵": "double_line",
            "轮形": "diamond",
            "轮形阵": "diamond",
            "梯形": "echelon",
            "梯形阵": "echelon",
            "单横": "line_abreast",
            "单横阵": "line_abreast",
            "警戒": "vanguard",
            "警戒阵": "vanguard",
            "航行序列1": "cruising_1",
            "航行序列2": "cruising_2",
            "航行序列3": "cruising_3",
            "航行序列4": "cruising_4",
        }
        for key in keys:
            match = re.search(rf"{key}[:：\s]*([^\s，,。；;]+)", text)
            if match:
                raw = match.group(1).strip()
                for alias, value in formation_alias.items():
                    if alias in raw:
                        return value
        for alias, value in formation_alias.items():
            if alias in text:
                return value
        return None

    def _extract_engagement(self, text: str) -> Optional[str]:
        for key in ["同航", "反航", "T有利", "T不利", "丁字有利", "丁字不利", "交叉"]:
            if key in text:
                return key
        return None

    def _extract_attacker_state(self, text: str) -> Optional[str]:
        for key in ["大破", "中破", "小破", "无伤", "正常"]:
            if key in text:
                return key
        return None

    def _extract_attacker_asw(self, text: str) -> Optional[int]:
        match = re.search(r"(对潜|ASW)[:：\s]*(\d+)", text, re.IGNORECASE)
        if match:
            return int(match.group(2))
        return None

    def _extract_attack_pattern(self, text: str) -> Optional[str]:
        mapping = {
            "连击": "double",
            "双击": "double",
            "主副": "main_sub",
            "主电": "main_radar",
            "主雷": "main_radar",
            "主穿": "main_ap",
            "主主": "main_main",
        }
        for key, value in mapping.items():
            if key in text:
                return value
        return None

    def _extract_equipment(self, text: str) -> List[KantaiEquipmentInput]:
        equip_keywords = ["装备", "装配", "携带"]
        equip_text = None
        for key in equip_keywords:
            match = re.search(rf"{key}[:：\s]*(.+)", text)
            if match:
                equip_text = match.group(1)
                break
        if not equip_text:
            return []
        equip_text = re.split(r"(阵型|交战|战斗类型|敌方|我方|攻击方|攻方|敌舰|敌人)", equip_text)[0]
        items = [token.strip() for token in re.split(r"[，,、;；|/]", equip_text) if token.strip()]
        results = []
        for item in items:
            parsed = self._parse_equipment_item(item)
            if parsed:
                results.append(parsed)
        return results

    def _parse_equipment_item(self, text: str) -> Optional[KantaiEquipmentInput]:
        name = re.sub(r"[（(].*?[)）]", "", text).strip()
        if not name:
            return None

        improvement = None
        proficiency = None

        if "满改修" in text or "全改修" in text:
            improvement = MAX_IMPROVEMENT
        star_match = re.search(r"★\+?(\d+)", text)
        if star_match:
            improvement = int(star_match.group(1))
        improve_match = re.search(r"改修(\d+)", text)
        if improve_match:
            improvement = int(improve_match.group(1))

        if "满熟练" in text or "全熟练" in text or ">>" in text:
            proficiency = MAX_PROFICIENCY
        prof_match = re.search(r"熟练度?(\d+)", text)
        if prof_match:
            proficiency = int(prof_match.group(1))

        improvement = improvement if improvement is not None else MAX_IMPROVEMENT
        proficiency = proficiency if proficiency is not None else MAX_PROFICIENCY

        cleaned = re.sub(r"★\+?\d+", "", name)
        cleaned = re.sub(r"改修\d+", "", cleaned)
        cleaned = re.sub(r"熟练度?\d+", "", cleaned)
        cleaned = cleaned.replace(">>", "").strip()

        return KantaiEquipmentInput(name=cleaned, improvement=improvement, proficiency=proficiency)

    def _missing_fields(self, payload: KantaiCalcPayload) -> List[str]:
        required = [
            ("attacker", "攻击方舰名"),
            ("enemy", "敌方舰名"),
            ("battle_type", "战斗类型（昼战/夜战/雷击/对潜/雷达射击）"),
            ("formation_self", "我方阵型"),
            ("formation_enemy", "敌方阵型"),
            ("engagement", "交战形态（同航/反航/T有利/T不利/交叉）"),
            ("attacker_state", "攻击方状态（正常/中破/大破）"),
            ("equipment", "装备列表（改修/熟练度不写默认满改修/满熟练）"),
        ]
        missing = []
        for field, label in required:
            value = getattr(payload, field)
            if field == "equipment" and not value:
                missing.append(label)
            elif not value:
                missing.append(label)
        if payload.battle_type == "asw" and payload.attacker_asw is None:
            missing.append("攻击方对潜面板数值（例如：对潜 80）")
        return missing

    def _build_missing_prompt(self, missing: List[str]) -> str:
        return (
            "为了准确计算，请补充以下信息（用普通语言描述即可）：\n"
            + "\n".join([f"- {item}" for item in missing])
            + "\n\n示例：\n"
            + "请帮我算昼战伤害，攻击方是长门改二，敌方是战舰栖姬。\n"
            + "我方阵型单纵，敌方单纵，交战同航，攻击方状态正常。\n"
            + "装备：41cm连装炮改二★+2、九一式穿甲弹、零式水上侦察机11型甲改二。"
        )

    def _calculate_damage(
        self,
        attacker: Dict[str, Any],
        enemy: Dict[str, Any],
        payload: KantaiCalcPayload,
    ) -> Dict[str, Any]:
        equipment_stats, unknown_items = self._sum_equipment_stats(payload.equipment)
        battle_type = payload.battle_type or "day"
        improvement_bonus = self._calc_improvement_bonus(payload.equipment, battle_type)
        attacker_asw = payload.attacker_asw
        if attacker_asw is None:
            attacker_asw = self._stat_max(attacker.get("taisen"))

        base_stats = {
            "火力": self._stat_max(attacker.get("houg")) + equipment_stats.get("houg", 0),
            "雷装": self._stat_max(attacker.get("raig")) + equipment_stats.get("raig", 0),
            "对空": self._stat_max(attacker.get("tyku")) + equipment_stats.get("tyku", 0),
            "对潜": (attacker_asw or 0) + equipment_stats.get("taisen", 0),
        }

        base_power = self._get_base_power(
            battle_type,
            attacker,
            equipment_stats,
            improvement_bonus,
            attacker_asw,
        )

        formation_bonus = self._get_formation_bonus(battle_type, payload.formation_self)
        engagement_bonus = self._get_engagement_bonus(payload.engagement, battle_type)
        condition_bonus = self._get_condition_bonus(payload.attacker_state, battle_type)
        pattern_bonus = self._get_attack_pattern_bonus(payload.attack_pattern, battle_type)

        precap = base_power * formation_bonus * engagement_bonus * condition_bonus * pattern_bonus
        postcap = self._apply_cap(precap, self._get_cap_value(battle_type))

        armor = self._stat_max(enemy.get("souk"))
        damage_range = self._estimate_damage(postcap, armor)

        notes = {
            "basic_stats": base_stats,
            "power_breakdown": {
                "基础火力": round(base_power, 2),
                "阵型倍率": formation_bonus,
                "交战倍率": engagement_bonus,
                "损伤倍率": condition_bonus,
                "攻击类型倍率": pattern_bonus,
                "封顶前": round(precap, 2),
                "封顶后": round(postcap, 2),
            },
            "damage_estimate": {
                "装甲(参考)": armor,
                "伤害区间": f"{damage_range[0]} ~ {damage_range[1]}",
            },
            "equipment_unknown": unknown_items,
            "defaults": {
                "improvement": "MAX",
                "proficiency": "MAX",
            },
        }
        return notes

    def _get_base_power(
        self,
        battle_type: str,
        attacker: Dict[str, Any],
        equipment_stats: Dict[str, int],
        improvement_bonus: float,
        attacker_asw: Optional[int] = None,
    ) -> float:
        base_fire = self._stat_max(attacker.get("houg")) + equipment_stats.get("houg", 0)
        base_torp = self._stat_max(attacker.get("raig")) + equipment_stats.get("raig", 0)
        base_asw = (attacker_asw or self._stat_max(attacker.get("taisen"))) + equipment_stats.get("taisen", 0)
        base_bomb = equipment_stats.get("bomb", 0)

        if battle_type == "torpedo":
            return base_torp + improvement_bonus + 5
        if battle_type == "night":
            return base_fire + base_torp + improvement_bonus + 5
        if battle_type == "asw":
            return math.sqrt(max(base_asw, 0)) * 2 + base_asw * 0.5 + improvement_bonus + 13
        if battle_type == "radar":
            return math.sqrt(max(base_torp, 0)) * 2

        if base_bomb > 0 and base_torp > 0:
            return 25 + 1.5 * (base_bomb + base_torp + 15)
        return base_fire + improvement_bonus + 5

    def _get_cap_value(self, battle_type: str) -> int:
        if battle_type == "night":
            return 360
        if battle_type == "torpedo":
            return 180
        if battle_type == "asw":
            return 170
        if battle_type == "radar":
            return 170
        return 220

    def _apply_cap(self, power: float, cap_value: int) -> float:
        if power <= cap_value:
            return power
        return cap_value + math.sqrt(power - cap_value)

    def _estimate_damage(self, power: float, armor: int) -> Tuple[int, int]:
        if armor <= 0:
            return int(math.floor(power)), int(math.floor(power))
        min_armor = armor * 0.7
        max_armor = armor * 1.3
        min_damage = max(0, int(math.floor(power - max_armor)))
        max_damage = max(0, int(math.floor(power - min_armor)))
        return min_damage, max_damage

    def _get_formation_bonus(self, battle_type: str, formation: Optional[str]) -> float:
        if not formation:
            return 1.0
        if battle_type == "asw":
            return {
                "line_ahead": 0.6,
                "double_line": 0.8,
                "diamond": 1.2,
                "echelon": 1.1,
                "line_abreast": 1.3,
                "vanguard": 1.0,
                "cruising_1": 1.3,
                "cruising_2": 1.1,
                "cruising_3": 1.0,
                "cruising_4": 0.7,
            }.get(formation, 1.0)
        if battle_type == "torpedo":
            return {
                "line_ahead": 1.0,
                "double_line": 0.8,
                "diamond": 0.7,
                "echelon": 0.6,
                "line_abreast": 0.6,
                "vanguard": 1.0,
                "cruising_1": 0.7,
                "cruising_2": 0.9,
                "cruising_3": 0.6,
                "cruising_4": 1.0,
            }.get(formation, 1.0)
        if battle_type == "night":
            return 1.0 if formation != "vanguard" else 0.5
        return {
            "line_ahead": 1.0,
            "double_line": 0.8,
            "diamond": 0.7,
            "echelon": 0.75,
            "line_abreast": 0.6,
            "vanguard": 1.0,
            "cruising_1": 0.8,
            "cruising_2": 1.0,
            "cruising_3": 0.7,
            "cruising_4": 1.1,
        }.get(formation, 1.0)

    def _get_engagement_bonus(self, engagement: Optional[str], battle_type: str) -> float:
        if battle_type == "night":
            return 1.0
        if not engagement:
            return 1.0
        mapping = {
            "同航": 1.0,
            "反航": 0.8,
            "T有利": 1.2,
            "丁字有利": 1.2,
            "T不利": 0.6,
            "丁字不利": 0.6,
            "交叉": 1.0,
        }
        return mapping.get(engagement, 1.0)

    def _get_condition_bonus(self, state: Optional[str], battle_type: str) -> float:
        if state == "大破":
            return 0.0 if battle_type == "torpedo" else 0.4
        if state == "中破":
            return 0.8 if battle_type == "torpedo" else 0.7
        return 1.0

    def _get_attack_pattern_bonus(self, pattern: Optional[str], battle_type: str) -> float:
        if battle_type != "day" or not pattern:
            return 1.0
        return {
            "double": 1.2,
            "main_sub": 1.1,
            "main_radar": 1.2,
            "main_ap": 1.3,
            "main_main": 1.5,
        }.get(pattern, 1.0)

    def _calc_improvement_bonus(self, items: List[KantaiEquipmentInput], battle_type: str) -> float:
        equip_map = self._load_equipment_map()
        bonus = 0.0
        for item in items:
            info = equip_map.get(item.name)
            if not info:
                continue
            type2 = info.get("type2")
            level = max(0, item.improvement)
            if battle_type == "torpedo":
                if type2 in (5, 21):
                    bonus += 1.2 * math.sqrt(level)
                elif type2 == 32:
                    bonus += 0.2 * level
                continue
            if battle_type in ("asw", "radar"):
                if type2 in (14, 15, 40):
                    bonus += math.sqrt(level)
                elif type2 in (7, 8, 25, 26):
                    bonus += 0.2 * level
                continue
            if type2 in (1, 2, 4, 19, 36, 29, 42, 21, 24, 46, 18, 37, 39, 34, 32, 35, 52, 54):
                bonus += math.sqrt(level)
            elif type2 in (3, 38):
                bonus += 1.5 * math.sqrt(level)
            elif type2 in (7, 8):
                bonus += 0.2 * level
            elif type2 in (14, 15, 40):
                bonus += 0.75 * level
        return bonus

    def _sum_equipment_stats(self, items: List[KantaiEquipmentInput]) -> Tuple[Dict[str, int], List[str]]:
        stats = {"houg": 0, "raig": 0, "tyku": 0, "souk": 0, "taisen": 0, "bomb": 0}
        unknown = []
        if not items:
            return stats, unknown

        equip_map = self._load_equipment_map()
        for item in items:
            info = equip_map.get(item.name)
            if not info:
                unknown.append(item.name)
                continue
            stats["houg"] += info.get("houg", 0)
            stats["raig"] += info.get("raig", 0)
            stats["tyku"] += info.get("tyku", 0)
            stats["souk"] += info.get("souk", 0)
            stats["taisen"] += info.get("taisen", 0)
            stats["bomb"] += info.get("bomb", 0)
        return stats, unknown

    @staticmethod
    @lru_cache(maxsize=1)
    def _load_equipment_map() -> Dict[str, Dict[str, int]]:
        """加载装备数据映射"""
        from pathlib import Path
        from .models import get_guide_engine_settings

        settings = get_guide_engine_settings()
        gamedata_dir = Path(settings.gamedata_dir)
        data_path = gamedata_dir / "kantai-collection_start2.json"

        if not data_path.exists():
            return {}

        with open(data_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        items = data.get("api_mst_slotitem", [])
        result = {}
        for item in items:
            name = item.get("api_name")
            if not name:
                continue
            type_info = item.get("api_type", [])
            type2 = type_info[2] if len(type_info) > 2 else None
            result[name] = {
                "type2": int(type2) if type2 is not None else None,
                "houg": int(item.get("api_houg", 0) or 0),
                "raig": int(item.get("api_raig", 0) or 0),
                "tyku": int(item.get("api_tyku", 0) or 0),
                "souk": int(item.get("api_souk", 0) or 0),
                "taisen": int(item.get("api_taisen", 0) or 0),
                "bomb": int(item.get("api_baku", 0) or 0),
            }
        return result

    @staticmethod
    def _stat_max(value: Any) -> int:
        if isinstance(value, list) and len(value) >= 2:
            return int(value[1])
        if value is None:
            return 0
        return int(value)

    @staticmethod
    def _stat_range(value: Any) -> str:
        if isinstance(value, list) and len(value) >= 2:
            return f"{value[0]}~{value[1]}"
        if value is None:
            return "未知"
        return str(value)
