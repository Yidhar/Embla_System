"""
绝区零数据处理器

将代理人、音擎、驱动盘和邦布数据拆分为可检索的分块
"""

import re
from typing import List, Dict, Any

from ..base import BaseProcessor, Document, ChunkType


class ZenlessProcessor(BaseProcessor):
    """绝区零数据处理器"""

    game_id = "zenless"

    ELEMENT_MAP: Dict[int, str] = {
        200: "物理", 201: "火", 202: "冰", 203: "电", 205: "以太",
    }

    TYPE_MAP: Dict[int, str] = {
        1: "强攻", 2: "击破", 3: "异常", 4: "支援", 5: "防护",
    }

    CAMP_MAP: Dict[int, str] = {
        1: "狡兔屋", 2: "维多利亚家政", 3: "哔哩哔哩视频小队",
        4: "卡吕冬之子", 5: "欧比城的流放者", 6: "新艾利都治安局",
        7: "空洞特工", 8: "奥波斯小队",
    }

    def get_data_files(self) -> Dict[str, str]:
        return {
            "characters": "zenless/global/characters.json",
            "weapons": "zenless/global/weapons.json",
            "drive_discs": "zenless/global/drive_discs.json",
            "bangboos": "zenless/global/bangboos.json",
        }

    def process(self, data: Dict[str, Any]) -> List[Document]:
        documents: list[Document] = []

        if "characters" in data:
            for agent_id, agent in data["characters"].items():
                doc = self._process_agent(agent_id, agent)
                if doc:
                    documents.append(doc)

        if "weapons" in data:
            for weapon_id, weapon in data["weapons"].items():
                doc = self._process_weapon(weapon_id, weapon)
                if doc:
                    documents.append(doc)

        if "drive_discs" in data:
            for disc_id, disc in data["drive_discs"].items():
                doc = self._process_drive_disc(disc_id, disc)
                if doc:
                    documents.append(doc)

        if "bangboos" in data:
            for bangboo_id, bangboo in data["bangboos"].items():
                doc = self._process_bangboo(bangboo_id, bangboo)
                if doc:
                    documents.append(doc)

        return documents

    def _rank_display(self, rank: int) -> str:
        if rank == 4:
            return "S"
        elif rank == 3:
            return "A"
        else:
            return str(rank)

    def _strip_color_tags(self, text: str) -> str:
        if not text:
            return ""
        return re.sub(r'<color=[^>]*>|</color>', '', text)

    def _process_agent(self, agent_id: str, agent: Dict[str, Any]) -> Document:
        name: str = agent.get("CHS", agent.get("EN", ""))
        if not name:
            return None  # type: ignore[return-value]

        doc = Document(
            game_id=self.game_id,
            entity_type="agent",
            entity_id=agent_id,
            entity_name=name,
            raw_data=agent,
        )

        rank: int = agent.get("rank", 0)
        element: int = agent.get("element", 0)
        type_val: int = agent.get("type", 0)
        camp: int = agent.get("camp", 0)
        desc: str = agent.get("desc", "")

        rarity = self._rank_display(rank)
        element_cn = self.ELEMENT_MAP.get(element, str(element))
        type_cn = self.TYPE_MAP.get(type_val, str(type_val))
        camp_cn = self.CAMP_MAP.get(camp, str(camp))

        parts: list[str] = [
            f"【{name}】是绝区零{rarity}级代理人，{element_cn}属性，{type_cn}类型。",
            f"阵营：{camp_cn}",
        ]
        if desc:
            parts.append(desc)

        basic_content = self._clean_text("\n".join(parts))
        doc.add_chunk(ChunkType.BASIC, basic_content, metadata={
            "rank": rank,
            "element": element,
            "type": type_val,
            "camp": camp,
        })

        return doc

    def _process_weapon(self, weapon_id: str, weapon: Dict[str, Any]) -> Document:
        name: str = weapon.get("CHS", weapon.get("EN", ""))
        if not name:
            return None  # type: ignore[return-value]

        doc = Document(
            game_id=self.game_id,
            entity_type="weapon",
            entity_id=weapon_id,
            entity_name=name,
            raw_data=weapon,
        )

        rank: int = weapon.get("rank", 0)
        desc: str = weapon.get("desc", "")
        rarity = self._rank_display(rank)

        parts: list[str] = [
            f"【{name}】是绝区零{rarity}级音擎。",
        ]
        if desc:
            parts.append(desc)

        basic_content = self._clean_text("\n".join(parts))
        doc.add_chunk(ChunkType.BASIC, basic_content, metadata={
            "rank": rank,
        })

        return doc

    def _process_drive_disc(self, disc_id: str, disc: Dict[str, Any]) -> Document:
        chs: Dict[str, Any] = disc.get("CHS", {})
        en: Dict[str, Any] = disc.get("EN", {})
        name: str = chs.get("name", en.get("name", ""))
        if not name:
            return None  # type: ignore[return-value]

        doc = Document(
            game_id=self.game_id,
            entity_type="drive_disc",
            entity_id=disc_id,
            entity_name=name,
            raw_data=disc,
        )

        desc2: str = self._strip_color_tags(chs.get("desc2", ""))
        desc4: str = self._strip_color_tags(chs.get("desc4", ""))

        parts: list[str] = [
            f"【{name}】是绝区零驱动盘套装。",
        ]
        if desc2:
            parts.append(f"二件套效果：{desc2}")
        if desc4:
            parts.append(f"四件套效果：{desc4}")

        basic_content = self._clean_text("\n".join(parts))
        doc.add_chunk(ChunkType.BASIC, basic_content, metadata={})

        return doc

    def _process_bangboo(self, bangboo_id: str, bangboo: Dict[str, Any]) -> Document:
        name: str = bangboo.get("CHS", bangboo.get("EN", ""))
        if not name:
            return None  # type: ignore[return-value]

        doc = Document(
            game_id=self.game_id,
            entity_type="bangboo",
            entity_id=bangboo_id,
            entity_name=name,
            raw_data=bangboo,
        )

        rank: int = bangboo.get("rank", 0)
        desc: str = bangboo.get("desc", "")
        rarity = self._rank_display(rank)

        parts: list[str] = [
            f"【{name}】是绝区零{rarity}级邦布。",
        ]
        if desc:
            parts.append(desc)

        basic_content = self._clean_text("\n".join(parts))
        doc.add_chunk(ChunkType.BASIC, basic_content, metadata={
            "rank": rank,
        })

        return doc
