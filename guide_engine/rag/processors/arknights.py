"""
明日方舟数据处理器

将干员和敌人数据拆分为可检索的分块
"""

from typing import List, Dict, Any
from ..base import BaseProcessor, Document, ChunkType


class ArknightsProcessor(BaseProcessor):
    """明日方舟数据处理器"""

    game_id = "arknights"

    def get_data_files(self) -> Dict[str, str]:
        return {
            "operators": "arknights_cn_operators.json",
            "enemies": "arknights_cn_enemies.json",
        }

    def process(self, data: Dict[str, Any]) -> List[Document]:
        documents: list[Document] = []

        if "operators" in data:
            for operator in data["operators"]:
                doc = self._process_operator(operator)
                if doc:
                    documents.append(doc)

        if "enemies" in data:
            for enemy in data["enemies"]:
                doc = self._process_enemy(enemy)
                if doc:
                    documents.append(doc)

        return documents

    def _process_operator(self, operator: Dict[str, Any]) -> Document:
        name = operator.get("name", "")
        entity_id = operator.get("id", f"char_{name}")

        doc = Document(
            game_id=self.game_id,
            entity_type="operator",
            entity_id=entity_id,
            entity_name=name,
            raw_data=operator
        )

        # 1. 基础信息
        basic_content = self._build_basic_chunk(operator)
        doc.add_chunk(ChunkType.BASIC, basic_content, metadata={
            "rarity": operator.get("rarity", 0),
            "class": operator.get("class", ""),
            "branch": operator.get("branch", ""),
        })

        # 2. 技能（每个技能单独一个 chunk）
        for i, skill in enumerate(operator.get("skills", [])):
            skill_content = self._build_skill_chunk(name, skill, i + 1)
            if skill_content:
                doc.add_chunk(ChunkType.SKILL, skill_content, chunk_index=i + 1, metadata={
                    "skill_name": skill.get("name", ""),
                    "skill_index": i + 1,
                })

        # 3. 天赋
        talents = operator.get("talents", [])
        if talents:
            talent_content = self._build_talents_chunk(name, talents)
            doc.add_chunk(ChunkType.TALENT, talent_content)

        # 4. 模组
        valid_modules = [m for m in operator.get("modules", []) if m.get("levels")]
        if valid_modules:
            module_content = self._build_modules_chunk(name, valid_modules)
            doc.add_chunk(ChunkType.MODULE, module_content)

        # 5. 基建技能
        building_skills = operator.get("building_skills", [])
        if building_skills:
            building_content = self._build_building_chunk(name, building_skills)
            doc.add_chunk(ChunkType.BUILDING, building_content)

        return doc

    def _build_basic_chunk(self, operator: Dict[str, Any]) -> str:
        name = operator.get("name", "")
        rarity = operator.get("rarity", 0)
        op_class = operator.get("class", "")
        branch = operator.get("branch", "")
        trait = operator.get("trait", "")
        obtain = operator.get("obtain", "")
        tags = operator.get("tags", [])
        aliases = operator.get("aliases", [])

        parts = [
            f"【{name}】是明日方舟{rarity}星干员，职业{op_class}，分支{branch}。"
        ]
        if trait:
            parts.append(f"特性：{trait}")
        if tags:
            parts.append(f"定位：{', '.join(tags)}")
        if obtain:
            parts.append(f"获取方式：{obtain}")
        if aliases:
            parts.append(f"别名：{', '.join(aliases)}")

        return self._clean_text("\n".join(parts))

    def _build_skill_chunk(self, name: str, skill: Dict[str, Any], index: int) -> str:
        skill_name = skill.get("name", "")
        if not skill_name:
            return ""

        skill_type = skill.get("type", "")
        charge_type = skill.get("charge_type", "")
        levels = skill.get("levels", {})

        parts = [f"【{name}】的{index}技能【{skill_name}】"]
        if skill_type:
            parts.append(f"触发方式：{skill_type}")
        if charge_type:
            parts.append(f"回复方式：{charge_type}")

        level_order = ["lv7", "m1", "m2", "m3"]
        level_names = {"lv7": "7级", "m1": "专精1", "m2": "专精2", "m3": "专精3"}

        for level_key in level_order:
            if level_key in levels:
                level_data = levels[level_key]
                level_name = level_names.get(level_key, level_key)
                desc = level_data.get("description", "")
                sp_cost = level_data.get("sp_cost")
                sp_init = level_data.get("sp_init")
                duration = level_data.get("duration")

                level_text = f"\n{level_name}：{desc}"
                attrs: list[str] = []
                if sp_cost is not None:
                    attrs.append(f"SP消耗:{sp_cost}")
                if sp_init is not None:
                    attrs.append(f"初始SP:{sp_init}")
                if duration is not None:
                    attrs.append(f"持续:{duration}秒")
                if attrs:
                    level_text += f" ({', '.join(attrs)})"
                parts.append(level_text)

        return self._clean_text("\n".join(parts))

    def _build_talents_chunk(self, name: str, talents: List[Dict[str, Any]]) -> str:
        parts = [f"【{name}】的天赋："]
        for talent in talents:
            talent_name = talent.get("name", "")
            levels = talent.get("levels", {})
            if not talent_name:
                continue

            talent_parts = [f"\n天赋【{talent_name}】"]
            for level_key, level_data in levels.items():
                condition = level_data.get("condition", "")
                desc = level_data.get("description", "")
                if level_key == "base":
                    talent_parts.append(f"基础({condition})：{desc}")
                elif level_key == "max_potential":
                    talent_parts.append(f"满潜({condition})：{desc}")
                else:
                    talent_parts.append(f"{level_key}({condition})：{desc}")
            parts.append("\n".join(talent_parts))

        return self._clean_text("\n".join(parts))

    def _build_modules_chunk(self, name: str, modules: List[Dict[str, Any]]) -> str:
        parts = [f"【{name}】的模组："]
        for module in modules:
            module_name = module.get("name", "")
            module_type = module.get("type", "")
            levels = module.get("levels", {})
            if not module_name or not levels:
                continue

            module_parts = [f"\n模组【{module_name}】"]
            if module_type:
                module_parts[0] += f" ({module_type})"

            for level_key in ["1", "2", "3"]:
                if level_key in levels:
                    level_data = levels[level_key]
                    stats = level_data.get("stats", {})
                    trait = level_data.get("trait", "")
                    talent = level_data.get("talent", "")

                    level_parts = [f"等级{level_key}:"]
                    if stats:
                        stat_str = ", ".join([f"{k}+{v}" for k, v in stats.items()])
                        level_parts.append(f"属性 {stat_str}")
                    if trait:
                        level_parts.append(f"特性变化 {trait}")
                    if talent:
                        level_parts.append(f"天赋变化 {talent}")
                    module_parts.append(" ".join(level_parts))

            parts.append("\n".join(module_parts))

        return self._clean_text("\n".join(parts))

    def _build_building_chunk(self, name: str, skills: List[Dict[str, Any]]) -> str:
        parts = [f"【{name}】的基建技能："]
        for skill in skills:
            skill_name = skill.get("name", "")
            phase = skill.get("phase", "")
            building = skill.get("building", "")
            desc = skill.get("description", "")
            if not skill_name:
                continue

            skill_text = f"\n【{skill_name}】"
            if phase:
                skill_text += f"({phase})"
            if building:
                skill_text += f" - {building}"
            skill_text += f"：{desc}"
            parts.append(skill_text)

        return self._clean_text("\n".join(parts))

    def _process_enemy(self, enemy: Dict[str, Any]) -> Document:
        name = enemy.get("name", "")
        entity_id = enemy.get("id", f"enemy_{name}")

        doc = Document(
            game_id=self.game_id,
            entity_type="enemy",
            entity_id=entity_id,
            entity_name=name,
            raw_data=enemy
        )

        basic_content = self._build_enemy_chunk(enemy)
        doc.add_chunk(ChunkType.BASIC, basic_content, metadata={
            "enemy_type": enemy.get("enemy_type", ""),
            "category": enemy.get("category", ""),
        })

        return doc

    def _build_enemy_chunk(self, enemy: Dict[str, Any]) -> str:
        name = enemy.get("name", "")
        enemy_type = enemy.get("enemy_type", "普通")
        category = enemy.get("category", "")
        hp = enemy.get("hp", 0)
        atk = enemy.get("atk", 0)
        defense = enemy.get("defense", 0)
        res = enemy.get("res", 0)
        attack_type = enemy.get("attack_type", "")
        move_type = enemy.get("move_type", "")
        talents = enemy.get("talents", [])
        skills = enemy.get("skills", [])

        parts = [f"【{name}】是明日方舟{enemy_type}敌人"]
        if category:
            parts[0] += f"，分类{category}"
        parts.append(f"属性：生命{hp}，攻击{atk}，防御{defense}，法抗{res}")
        if attack_type:
            parts.append(f"攻击方式：{attack_type}")
        if move_type:
            parts.append(f"移动类型：{move_type}")
        if talents:
            parts.append("能力：" + " / ".join(talents))
        if skills:
            parts.append("技能：" + " / ".join(skills))

        return self._clean_text("\n".join(parts))
