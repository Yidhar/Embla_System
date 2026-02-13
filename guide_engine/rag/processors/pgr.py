"""战双帕弥什数据处理器"""

from typing import List, Dict, Any
from ..base import BaseProcessor, Document, ChunkType


class PGRProcessor(BaseProcessor):
    """战双帕弥什数据处理器"""

    game_id = "pgr"

    SKILL_TAG_MAP: Dict[str, str] = {
        "red_orb": "红球",
        "yellow_orb": "黄球",
        "blue_orb": "蓝球",
        "qte_skill": "QTE",
        "ultimate_skill": "必杀",
    }

    def get_data_files(self) -> Dict[str, str]:
        return {
            "frames": "pgr/cn/frames.json",
            "weapons": "pgr/cn/weapons.json",
            "memories": "pgr/cn/memories.json",
            "builds": "pgr/cn/builds.json",
        }

    def process(self, data: Dict[str, Any]) -> List[Document]:
        documents: List[Document] = []

        if "frames" in data:
            for frame in data["frames"]:
                doc = self._process_frame(frame)
                if doc:
                    documents.append(doc)

        if "weapons" in data:
            for weapon in data["weapons"]:
                doc = self._process_weapon(weapon)
                if doc:
                    documents.append(doc)

        if "memories" in data:
            for memory in data["memories"]:
                doc = self._process_memory(memory)
                if doc:
                    documents.append(doc)

        if "builds" in data:
            for build in data["builds"]:
                doc = self._process_build(build)
                if doc:
                    documents.append(doc)

        return documents

    def _process_frame(self, frame: Dict[str, Any]) -> Document:
        full_name: str = frame.get("full_name", "")
        entity_id: str = frame.get("id", f"frame_{full_name}")

        doc = Document(
            game_id=self.game_id,
            entity_type="frame",
            entity_id=entity_id,
            entity_name=full_name,
            raw_data=frame,
        )

        # 基础信息
        basic_content = self._build_frame_basic(frame)
        doc.add_chunk(ChunkType.BASIC, basic_content, metadata={
            "rarity": frame.get("rarity", ""),
            "frame_type": frame.get("frame_type", ""),
            "element": frame.get("element", ""),
            "weapon_type": frame.get("weapon_type", ""),
        })

        # 技能 - 每个技能类型单独一个 chunk
        skill_keys: List[str] = ["red_orb", "yellow_orb", "blue_orb", "qte_skill", "ultimate_skill"]
        chunk_idx = 0
        for key in skill_keys:
            skill_data: Dict[str, Any] = frame.get(key, {})
            if skill_data and skill_data.get("name"):
                chunk_idx += 1
                skill_name: str = skill_data.get("name", "")
                description: str = skill_data.get("description", "")
                tag_cn: str = self.SKILL_TAG_MAP.get(key, key)

                content = self._clean_text(
                    f"【{full_name}】的{tag_cn}技能【{skill_name}】\n{description}"
                )
                doc.add_chunk(ChunkType.SKILL, content, chunk_index=chunk_idx, metadata={
                    "skill_type": key,
                    "skill_name": skill_name,
                })

        return doc

    def _build_frame_basic(self, frame: Dict[str, Any]) -> str:
        full_name: str = frame.get("full_name", "")
        name: str = frame.get("name", "")
        frame_name: str = frame.get("frame_name", "")
        rarity: str = frame.get("rarity", "")
        frame_type: str = frame.get("frame_type", "")
        element: str = frame.get("element", "")
        weapon_type: str = frame.get("weapon_type", "")

        parts: List[str] = [
            f"【{full_name}】是战双帕弥什{rarity}级机体，{frame_type}，{element}属性，使用{weapon_type}。",
            f"角色：{name}",
            f"机体：{frame_name}",
        ]

        return self._clean_text("\n".join(parts))

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
            "rarity": weapon.get("rarity", ""),
            "weapon_type": weapon.get("weapon_type", ""),
        })

        return doc

    def _build_weapon_basic(self, weapon: Dict[str, Any]) -> str:
        name: str = weapon.get("name", "")
        rarity: str = weapon.get("rarity", "")
        weapon_type: str = weapon.get("weapon_type", "")
        skill_desc: str = weapon.get("skill_desc", "")
        exclusive_for: str = weapon.get("exclusive_for", "")

        parts: List[str] = [
            f"【{name}】是战双帕弥什{rarity}星{weapon_type}。",
        ]
        if skill_desc:
            parts.append(skill_desc)
        if exclusive_for:
            parts.append(f"专属角色：{exclusive_for}")

        return self._clean_text("\n".join(parts))

    def _process_memory(self, memory: Dict[str, Any]) -> Document:
        name: str = memory.get("name", "")
        entity_id: str = memory.get("id", f"memory_{name}")

        doc = Document(
            game_id=self.game_id,
            entity_type="memory",
            entity_id=entity_id,
            entity_name=name,
            raw_data=memory,
        )

        basic_content = self._build_memory_basic(memory)
        doc.add_chunk(ChunkType.BASIC, basic_content, metadata={
            "rarity": memory.get("rarity", ""),
        })

        return doc

    def _build_memory_basic(self, memory: Dict[str, Any]) -> str:
        name: str = memory.get("name", "")
        rarity: str = memory.get("rarity", "")
        two_piece_effect: str = memory.get("two_piece_effect", "")
        four_piece_effect: str = memory.get("four_piece_effect", "")
        description: str = memory.get("description", "")

        parts: List[str] = [
            f"【{name}】是战双帕弥什{rarity}星意识。",
        ]
        if two_piece_effect:
            parts.append(f"二件套效果：{two_piece_effect}")
        if four_piece_effect:
            parts.append(f"四件套效果：{four_piece_effect}")
        if description:
            parts.append(description)

        return self._clean_text("\n".join(parts))

    def _process_build(self, build: Dict[str, Any]) -> Document:
        build_name: str = build.get("name", "")
        entity_id: str = f"build_{build_name}"

        doc = Document(
            game_id=self.game_id,
            entity_type="build",
            entity_id=entity_id,
            entity_name=build_name,
            raw_data=build,
        )

        guide_content = self._build_guide(build)
        doc.add_chunk(ChunkType.GUIDE, guide_content, metadata={
            "category": build.get("category", ""),
        })

        return doc

    def _build_guide(self, build: Dict[str, Any]) -> str:
        build_name: str = build.get("name", "")
        category: str = build.get("category", "")
        content: str = build.get("content", "")

        parts: List[str] = [
            f"【{build_name}】战双帕弥什配装推荐",
            f"分类：{category}",
        ]

        # 解析 pipe-separated 内容
        if content:
            entries: List[str] = content.split("|")
            for entry in entries:
                entry = entry.strip().replace("\\n", "")
                if "=" not in entry:
                    continue
                key, _, value = entry.partition("=")
                key = key.strip().replace("\\n", "")
                value = value.strip().replace("\\n", "")
                if value:
                    parts.append(f"{key}：{value}")

        return self._clean_text("\n".join(parts))
