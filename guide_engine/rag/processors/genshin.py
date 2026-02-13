"""
原神数据处理器

将角色、武器、圣遗物数据拆分为可检索的分块
"""

from typing import List, Dict, Any
from ..base import BaseProcessor, Document, ChunkType


class GenshinProcessor(BaseProcessor):
    """原神数据处理器"""

    game_id = "genshin"

    def get_data_files(self) -> Dict[str, str]:
        return {
            "characters": "genshin/global/characters.json",
            "weapons": "genshin/global/weapons.json",
            "artifacts": "genshin/global/artifacts.json",
        }

    def process(self, data: Dict[str, Any]) -> List[Document]:
        documents: list[Document] = []

        if "characters" in data:
            for character in data["characters"]:
                doc = self._process_character(character)
                if doc:
                    documents.append(doc)

        if "weapons" in data:
            for weapon in data["weapons"]:
                doc = self._process_weapon(weapon)
                if doc:
                    documents.append(doc)

        if "artifacts" in data:
            for artifact in data["artifacts"]:
                doc = self._process_artifact(artifact)
                if doc:
                    documents.append(doc)

        return documents

    # ── 角色处理 ──────────────────────────────────────────────

    def _process_character(self, character: Dict[str, Any]) -> Document:
        name: str = character.get("name", "")
        entity_id: str = character.get("id", f"char_{name}")

        doc = Document(
            game_id=self.game_id,
            entity_type="character",
            entity_id=entity_id,
            entity_name=name,
            raw_data=character,
        )

        # 1. 基础信息
        basic_content = self._build_character_basic(character)
        doc.add_chunk(ChunkType.BASIC, basic_content, metadata={
            "rarity": character.get("rarity", 0),
            "elementText": character.get("elementText", ""),
            "weaponText": character.get("weaponText", ""),
        })

        # 2. 突破材料
        costs: Dict[str, Any] = character.get("costs", {})
        if costs:
            material_content = self._build_character_material(name, costs)
            if material_content:
                doc.add_chunk(ChunkType.MATERIAL, material_content)

        return doc

    def _build_character_basic(self, character: Dict[str, Any]) -> str:
        name: str = character.get("name", "")
        rarity: int = character.get("rarity", 0)
        element_text: str = character.get("elementText", "")
        weapon_text: str = character.get("weaponText", "")
        title: str = character.get("title", "")
        substat_text: str = character.get("substatText", "")
        constellation: str = character.get("constellation", "")
        region: str = character.get("region", "")
        affiliation: str = character.get("affiliation", "")
        cv: Dict[str, str] = character.get("cv", {})

        parts: list[str] = [
            f"【{name}】是原神{rarity}星角色，{element_text}元素，使用{weapon_text}。"
        ]
        if title:
            parts.append(f"称号：{title}")
        if substat_text:
            parts.append(f"突破属性：{substat_text}")
        if constellation:
            parts.append(f"命之座：{constellation}")
        if region:
            parts.append(f"地区：{region}")
        if affiliation:
            parts.append(f"所属：{affiliation}")
        if cv:
            cv_chinese: str = cv.get("chinese", "")
            cv_japanese: str = cv.get("japanese", "")
            if cv_chinese or cv_japanese:
                parts.append(f"声优：中{cv_chinese}，日{cv_japanese}")

        return self._clean_text("\n".join(parts))

    def _build_character_material(self, name: str, costs: Dict[str, List[Dict[str, Any]]]) -> str:
        parts: list[str] = [f"【{name}】的突破材料："]

        for stage_key in sorted(costs.keys()):
            materials: List[Dict[str, Any]] = costs[stage_key]
            if not materials:
                continue
            mat_strs: list[str] = [
                f"{m.get('name', '')}x{m.get('count', 0)}" for m in materials
            ]
            stage_label = stage_key.replace("ascend", "突破阶段")
            parts.append(f"{stage_label}：{', '.join(mat_strs)}")

        if len(parts) <= 1:
            return ""
        return self._clean_text("\n".join(parts))

    # ── 武器处理 ──────────────────────────────────────────────

    def _process_weapon(self, weapon: Dict[str, Any]) -> Document:
        name: str = weapon.get("name", "")
        entity_id: str = weapon.get("id", f"weapon_{name}")

        doc = Document(
            game_id=self.game_id,
            entity_type="weapon",
            entity_id=entity_id,
            entity_name=name,
            raw_data=weapon,
        )

        basic_content = self._build_weapon_basic(weapon)
        doc.add_chunk(ChunkType.BASIC, basic_content, metadata={
            "rarity": weapon.get("rarity", 0),
            "weaponText": weapon.get("weaponText", ""),
        })

        return doc

    def _build_weapon_basic(self, weapon: Dict[str, Any]) -> str:
        name: str = weapon.get("name", "")
        rarity: int = weapon.get("rarity", 0)
        weapon_text: str = weapon.get("weaponText", "")
        base_atk: Any = weapon.get("baseAtkValue", "")
        main_stat_text: str = weapon.get("mainStatText", "")
        base_stat_text: str = weapon.get("baseStatText", "")

        parts: list[str] = [
            f"【{name}】是原神{rarity}星{weapon_text}。"
        ]
        if base_atk:
            parts.append(f"基础攻击力：{base_atk}")
        if main_stat_text or base_stat_text:
            parts.append(f"副属性：{main_stat_text} {base_stat_text}")

        for i in range(1, 6):
            refine_key = f"r{i}"
            refine_data: Dict[str, Any] = weapon.get(refine_key, {})
            if refine_data:
                desc: str = refine_data.get("description", "")
                if desc:
                    parts.append(f"精炼{i}：{desc}")

        return self._clean_text("\n".join(parts))

    # ── 圣遗物处理 ─────────────────────────────────────────────

    def _process_artifact(self, artifact: Dict[str, Any]) -> Document:
        name: str = artifact.get("name", "")
        entity_id: str = artifact.get("id", f"artifact_{name}")

        doc = Document(
            game_id=self.game_id,
            entity_type="artifact",
            entity_id=entity_id,
            entity_name=name,
            raw_data=artifact,
        )

        basic_content = self._build_artifact_basic(artifact)
        rarity_list: List[int] = artifact.get("rarityList", [])
        max_rarity: int = max(rarity_list) if rarity_list else 0
        doc.add_chunk(ChunkType.BASIC, basic_content, metadata={
            "max_rarity": max_rarity,
        })

        return doc

    def _build_artifact_basic(self, artifact: Dict[str, Any]) -> str:
        name: str = artifact.get("name", "")
        rarity_list: List[int] = artifact.get("rarityList", [])
        effect_2pc: str = artifact.get("effect2Pc", "")
        effect_4pc: str = artifact.get("effect4Pc", "")
        max_rarity: int = max(rarity_list) if rarity_list else 0

        parts: list[str] = [
            f"【{name}】是原神圣遗物套装。"
        ]
        if max_rarity:
            parts.append(f"最高稀有度：{max_rarity}星")
        if effect_2pc:
            parts.append(f"二件套效果：{effect_2pc}")
        if effect_4pc:
            parts.append(f"四件套效果：{effect_4pc}")

        return self._clean_text("\n".join(parts))
