"""
赛马娘数据处理器

将角色、技能和支援卡数据拆分为可检索的分块
"""

from typing import List, Dict, Any
from ..base import BaseProcessor, Document, ChunkType


class UmaMusumeProcessor(BaseProcessor):
    """赛马娘数据处理器"""

    game_id = "umamusume"

    APTITUDE_MAP: Dict[str, str] = {
        "short": "短距离", "mile": "英里", "medium": "中距离",
        "long": "长距离", "turf": "芝", "dirt": "泥地",
        "nige": "逃", "senkou": "先行", "sashi": "差し",
        "oikomi": "追込",
    }

    CARD_TYPE_MAP: Dict[str, str] = {
        "speed": "速度", "stamina": "耐力", "power": "力量",
        "guts": "根性", "wisdom": "智力", "friend": "友人",
        "group": "团队",
    }

    def get_data_files(self) -> Dict[str, str]:
        return {
            "characters": "umamusume/jp/characters.json",
            "skills": "umamusume/jp/skills.json",
            "support_cards": "umamusume/jp/support_cards.json",
        }

    def process(self, data: Dict[str, Any]) -> List[Document]:
        documents: List[Document] = []

        if "characters" in data:
            for character in data["characters"]:
                doc = self._process_character(character)
                if doc:
                    documents.append(doc)

        if "skills" in data:
            for skill in data["skills"]:
                doc = self._process_skill(skill)
                if doc:
                    documents.append(doc)

        if "support_cards" in data:
            for support_card in data["support_cards"]:
                doc = self._process_support_card(support_card)
                if doc:
                    documents.append(doc)

        return documents

    def _process_character(self, character: Dict[str, Any]) -> Document:
        name: str = character.get("name", "")
        entity_id: str = character.get("id", f"uma_{name}")

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
            "is_variant": character.get("is_variant", False),
        })

        # 2. 育成事件
        training_events: List[Dict[str, Any]] = character.get("training_events", [])
        for i, event in enumerate(training_events):
            event_name: str = event.get("event_name", "")
            choices: List[Dict[str, Any]] = event.get("choices", [])
            if not event_name or not choices:
                continue

            event_content = self._build_event_chunk(name, event)
            doc.add_chunk(ChunkType.EVENT, event_content, chunk_index=i, metadata={
                "event_name": event_name,
                "event_type": event.get("event_type", ""),
            })

        return doc

    def _build_character_basic(self, character: Dict[str, Any]) -> str:
        name: str = character.get("name", "")
        rarity: int = character.get("rarity", 0)
        name_ja: str = character.get("name_ja", "")
        variant_name: str = character.get("variant_name", "")
        growth_rates: Dict[str, Any] = character.get("growth_rates", {})
        aptitude: Dict[str, str] = character.get("aptitude", {})

        parts: List[str] = [
            f"【{name}】是赛马娘{rarity}星角色。"
        ]
        if name_ja:
            parts.append(f"日文名：{name_ja}")
        if variant_name:
            parts.append(f"变体：{variant_name}")
        if growth_rates:
            parts.append(
                f"成长率：速度{growth_rates.get('speed', 0)}、"
                f"耐力{growth_rates.get('stamina', 0)}、"
                f"力量{growth_rates.get('power', 0)}、"
                f"根性{growth_rates.get('guts', 0)}、"
                f"智力{growth_rates.get('wisdom', 0)}"
            )
        if aptitude:
            apt_parts: List[str] = []
            for key, label in self.APTITUDE_MAP.items():
                value: str = aptitude.get(key, "")
                if value:
                    apt_parts.append(f"{label}{value}")
            if apt_parts:
                parts.append(f"适性：{'、'.join(apt_parts)}")

        return self._clean_text("\n".join(parts))

    def _build_event_chunk(self, char_name: str, event: Dict[str, Any]) -> str:
        event_name: str = event.get("event_name", "")
        event_type: str = event.get("event_type", "")
        choices: List[Dict[str, Any]] = event.get("choices", [])

        parts: List[str] = [f"【{char_name}】的育成事件【{event_name}】"]
        if event_type:
            parts.append(f"事件类型：{event_type}")

        choice_lines: List[str] = []
        for idx, choice in enumerate(choices, 1):
            text: str = choice.get("text_cn", "") or choice.get("text", "")
            effect: str = choice.get("effect_cn", "") or choice.get("effect", "")
            choice_lines.append(f"{idx}. {text} → {effect}")

        if choice_lines:
            parts.append("选项：")
            parts.extend(choice_lines)

        return self._clean_text("\n".join(parts))

    def _process_skill(self, skill: Dict[str, Any]) -> Document:
        name: str = skill.get("name", "")
        entity_id: str = skill.get("id", f"skill_{name}")

        doc = Document(
            game_id=self.game_id,
            entity_type="skill",
            entity_id=entity_id,
            entity_name=name,
            raw_data=skill,
        )

        basic_content = self._build_skill_basic(skill)
        doc.add_chunk(ChunkType.BASIC, basic_content, metadata={
            "skill_type": skill.get("skill_type", ""),
            "rarity": skill.get("rarity", ""),
        })

        return doc

    def _build_skill_basic(self, skill: Dict[str, Any]) -> str:
        name: str = skill.get("name", "")
        name_ja: str = skill.get("name_ja", "")
        skill_type: str = skill.get("skill_type", "")
        description: str = skill.get("description", "")

        parts: List[str] = [f"【{name}】是赛马娘技能。"]
        if name_ja:
            parts.append(f"日文名：{name_ja}")
        if skill_type:
            parts.append(f"技能类型：{skill_type}")
        if description:
            parts.append(f"描述：{description}")

        return self._clean_text("\n".join(parts))

    def _process_support_card(self, support_card: Dict[str, Any]) -> Document:
        name: str = support_card.get("name", "")
        entity_id: str = support_card.get("id", f"support_{name}")

        doc = Document(
            game_id=self.game_id,
            entity_type="support_card",
            entity_id=entity_id,
            entity_name=name,
            raw_data=support_card,
        )

        basic_content = self._build_support_card_basic(support_card)
        doc.add_chunk(ChunkType.BASIC, basic_content, metadata={
            "rarity": support_card.get("rarity", ""),
            "card_type": support_card.get("card_type", ""),
        })

        return doc

    def _build_support_card_basic(self, support_card: Dict[str, Any]) -> str:
        name: str = support_card.get("name", "")
        rarity: str = support_card.get("rarity", "")
        card_type: str = support_card.get("card_type", "")
        card_type_cn: str = self.CARD_TYPE_MAP.get(card_type, card_type)
        related_character: str = support_card.get("related_character", "")
        unique_effect: str = support_card.get("unique_effect", "")

        parts: List[str] = [f"【{name}】是赛马娘{rarity}支援卡，{card_type_cn}类型。"]
        if related_character:
            parts.append(f"关联角色：{related_character}")
        if unique_effect:
            parts.append(f"固有效果：{unique_effect}")

        return self._clean_text("\n".join(parts))
