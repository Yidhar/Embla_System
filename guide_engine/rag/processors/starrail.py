"""
崩坏星穹铁道数据处理器

将角色、光锥和遗器数据拆分为可检索的分块
"""

from typing import List, Dict, Any, Optional
from ..base import BaseProcessor, Document, ChunkType


class StarrailProcessor(BaseProcessor):
    """崩坏星穹铁道数据处理器"""

    game_id = "starrail"

    PATH_MAP: Dict[str, str] = {
        "Knight": "存护",
        "Rogue": "巡猎",
        "Mage": "智识",
        "Shaman": "丰饶",
        "Warlock": "虚无",
        "Warrior": "毁灭",
        "Priest": "同谐",
        "Memoriae": "记忆",
    }

    ELEMENT_MAP: Dict[str, str] = {
        "Physical": "物理",
        "Fire": "火",
        "Ice": "冰",
        "Thunder": "雷",
        "Wind": "风",
        "Quantum": "量子",
        "Imaginary": "虚数",
    }

    def get_data_files(self) -> Dict[str, str]:
        return {
            "characters": "starrail/global/characters.json",
            "light_cones": "starrail/global/light_cones.json",
            "relic_sets": "starrail/global/relic_sets.json",
        }

    def process(self, data: Dict[str, Any]) -> List[Document]:
        documents: list[Document] = []

        if "characters" in data:
            chars = data["characters"]
            if isinstance(chars, dict):
                for char_id, char_data in chars.items():
                    doc = self._process_character(char_id, char_data)
                    if doc:
                        documents.append(doc)

        if "light_cones" in data:
            light_cones = data["light_cones"]
            if isinstance(light_cones, dict):
                for lc_id, lc_data in light_cones.items():
                    doc = self._process_light_cone(lc_id, lc_data)
                    if doc:
                        documents.append(doc)

        if "relic_sets" in data:
            relic_sets = data["relic_sets"]
            if isinstance(relic_sets, dict):
                for relic_id, relic_data in relic_sets.items():
                    doc = self._process_relic_set(relic_id, relic_data)
                    if doc:
                        documents.append(doc)

        return documents

    def _process_character(self, char_id: str, character: Dict[str, Any]) -> Optional[Document]:
        name: str = character.get("name", "")

        doc = Document(
            game_id=self.game_id,
            entity_type="character",
            entity_id=char_id,
            entity_name=name,
            raw_data=character,
        )

        rarity: int = character.get("rarity", 0)
        path: str = character.get("path", "")
        element: str = character.get("element", "")
        max_sp: Any = character.get("max_sp", "")

        path_cn = self.PATH_MAP.get(path, path)
        element_cn = self.ELEMENT_MAP.get(element, element)

        parts: list[str] = [
            f"【{name}】是崩坏星穹铁道{rarity}星角色，{path_cn}命途，{element_cn}属性。",
            f"终结技能量：{max_sp}",
        ]

        basic_content = self._clean_text("\n".join(parts))
        doc.add_chunk(ChunkType.BASIC, basic_content, metadata={
            "rarity": rarity,
            "path": path,
            "element": element,
        })

        return doc

    def _process_light_cone(self, lc_id: str, light_cone: Dict[str, Any]) -> Optional[Document]:
        name: str = light_cone.get("name", "")

        doc = Document(
            game_id=self.game_id,
            entity_type="light_cone",
            entity_id=lc_id,
            entity_name=name,
            raw_data=light_cone,
        )

        rarity: int = light_cone.get("rarity", 0)
        path: str = light_cone.get("path", "")
        desc: str = light_cone.get("desc", "")

        path_cn = self.PATH_MAP.get(path, path)

        parts: list[str] = [
            f"【{name}】是崩坏星穹铁道{rarity}星光锥，{path_cn}命途。",
        ]
        if desc:
            parts.append(desc)

        basic_content = self._clean_text("\n".join(parts))
        doc.add_chunk(ChunkType.BASIC, basic_content, metadata={
            "rarity": rarity,
            "path": path,
        })

        return doc

    def _process_relic_set(self, relic_id: str, relic_set: Dict[str, Any]) -> Optional[Document]:
        name: str = relic_set.get("name", "")

        doc = Document(
            game_id=self.game_id,
            entity_type="relic_set",
            entity_id=relic_id,
            entity_name=name,
            raw_data=relic_set,
        )

        desc: list[str] = relic_set.get("desc", [])

        parts: list[str] = [
            f"【{name}】是崩坏星穹铁道遗器套装。",
        ]
        if len(desc) > 0:
            parts.append(f"二件套效果：{desc[0]}")
        if len(desc) > 1:
            parts.append(f"四件套效果：{desc[1]}")

        basic_content = self._clean_text("\n".join(parts))
        doc.add_chunk(ChunkType.BASIC, basic_content, metadata={})

        return doc
