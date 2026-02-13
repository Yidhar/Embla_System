"""
鸣潮数据处理器

将共鸣者、武器、声骸和合鸣效果数据拆分为可检索的分块
"""

from typing import List, Dict, Any
from ..base import BaseProcessor, Document, ChunkType


class WutheringWavesProcessor(BaseProcessor):
    """鸣潮数据处理器"""

    game_id = "wutheringwaves"

    def get_data_files(self) -> Dict[str, str]:
        return {
            "resonators": "wutheringwaves/cn/resonators.json",
            "weapons": "wutheringwaves/cn/weapons.json",
            "echoes": "wutheringwaves/cn/echoes.json",
            "sonatas": "wutheringwaves/cn/sonatas.json",
        }

    def process(self, data: Dict[str, Any]) -> List[Document]:
        documents: list[Document] = []

        if "resonators" in data:
            for resonator in data["resonators"]:
                doc = self._process_resonator(resonator)
                if doc:
                    documents.append(doc)

        if "weapons" in data:
            for weapon in data["weapons"]:
                doc = self._process_weapon(weapon)
                if doc:
                    documents.append(doc)

        if "echoes" in data:
            for echo in data["echoes"]:
                doc = self._process_echo(echo)
                if doc:
                    documents.append(doc)

        if "sonatas" in data:
            for sonata in data["sonatas"]:
                doc = self._process_sonata(sonata)
                if doc:
                    documents.append(doc)

        return documents

    def _process_resonator(self, resonator: Dict[str, Any]) -> Document:
        name: str = resonator.get("name", "")
        entity_id: str = resonator.get("id", f"resonator_{name}")

        doc = Document(
            game_id=self.game_id,
            entity_type="resonator",
            entity_id=entity_id,
            entity_name=name,
            raw_data=resonator
        )

        rarity = resonator.get("rarity", 0)
        element: str = resonator.get("element", "")
        weapon_type: str = resonator.get("weapon_type", "")
        faction: str = resonator.get("faction", "")
        description: str = resonator.get("description", "")
        combat_style: str = resonator.get("combat_style", "")

        parts: list[str] = [
            f"【{name}】是鸣潮{rarity}星共鸣者，{element}属性，使用{weapon_type}。"
        ]
        if faction:
            parts.append(f"阵营：{faction}")
        if description:
            parts.append(f"描述：{description}")
        if combat_style:
            parts.append(f"战斗风格：{combat_style}")

        basic_content: str = self._clean_text("\n".join(parts))
        doc.add_chunk(ChunkType.BASIC, basic_content, metadata={
            "rarity": rarity,
            "element": element,
            "weapon_type": weapon_type,
        })

        return doc

    def _process_weapon(self, weapon: Dict[str, Any]) -> Document:
        name: str = weapon.get("name", "")
        entity_id: str = weapon.get("id", f"weapon_{name}")

        doc = Document(
            game_id=self.game_id,
            entity_type="weapon",
            entity_id=entity_id,
            entity_name=name,
            raw_data=weapon
        )

        rarity = weapon.get("rarity", 0)
        weapon_type: str = weapon.get("weapon_type", "")
        passive_desc: str = weapon.get("passive_desc", "")

        parts: list[str] = [
            f"【{name}】是鸣潮{rarity}星{weapon_type}。"
        ]
        if passive_desc:
            parts.append(f"被动效果：{passive_desc}")

        basic_content: str = self._clean_text("\n".join(parts))
        doc.add_chunk(ChunkType.BASIC, basic_content, metadata={
            "rarity": rarity,
            "weapon_type": weapon_type,
        })

        return doc

    def _process_echo(self, echo: Dict[str, Any]) -> Document:
        name: str = echo.get("name", "")
        entity_id: str = echo.get("id", f"echo_{name}")

        doc = Document(
            game_id=self.game_id,
            entity_type="echo",
            entity_id=entity_id,
            entity_name=name,
            raw_data=echo
        )

        cost = echo.get("cost", 0)
        skill_desc: str = echo.get("skill_desc", "")

        parts: list[str] = [
            f"【{name}】是鸣潮声骸，cost为{cost}。"
        ]
        if skill_desc:
            parts.append(f"技能：{skill_desc}")

        basic_content: str = self._clean_text("\n".join(parts))
        doc.add_chunk(ChunkType.BASIC, basic_content, metadata={
            "cost": cost,
        })

        return doc

    def _process_sonata(self, sonata: Dict[str, Any]) -> Document:
        name: str = sonata.get("name", "")
        entity_id: str = sonata.get("id", f"sonata_{name}")

        doc = Document(
            game_id=self.game_id,
            entity_type="sonata",
            entity_id=entity_id,
            entity_name=name,
            raw_data=sonata
        )

        two_piece: str = sonata.get("two_piece", "")
        five_piece: str = sonata.get("five_piece", "")

        parts: list[str] = [
            f"【{name}】是鸣潮合鸣效果。"
        ]
        if two_piece:
            parts.append(f"二件套效果：{two_piece}")
        if five_piece:
            parts.append(f"五件套效果：{five_piece}")

        basic_content: str = self._clean_text("\n".join(parts))
        doc.add_chunk(ChunkType.BASIC, basic_content, metadata={})

        return doc
