"""
GameData 数据加载器

加载和解析 ArknightsGameData 的结构化数据，用于精确计算。
"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from functools import lru_cache


# 数据目录
GAMEDATA_DIR = Path(__file__).parent.parent / "data" / "arknights" / "gamedata"
INDEX_DIR = Path(__file__).parent.parent / "data" / "arknights" / "index"


@dataclass
class PhaseAttributes:
    """精英阶段属性"""
    max_hp: int = 0
    atk: int = 0
    defense: int = 0  # def是Python关键字
    magic_resistance: float = 0
    cost: int = 0
    block_cnt: int = 0
    base_attack_time: float = 1.0
    respawn_time: int = 70


@dataclass
class SkillLevel:
    """技能等级数据"""
    name: str = ""
    description: str = ""
    skill_type: int = 0  # 0=被动, 1=手动, 2=自动
    sp_type: int = 1     # 1=自动回复, 2=攻击回复, 4=受击回复, 8=被动
    sp_cost: int = 0
    init_sp: int = 0
    duration: float = 0
    blackboard: Dict[str, float] = field(default_factory=dict)


@dataclass
class Skill:
    """技能数据"""
    skill_id: str = ""
    icon_id: str = ""
    levels: List[SkillLevel] = field(default_factory=list)

    def get_level(self, level: int) -> Optional[SkillLevel]:
        """获取指定等级的技能数据，level: 1-10 (M3=10)"""
        if 1 <= level <= len(self.levels):
            return self.levels[level - 1]
        return None

    def get_max_level(self) -> Optional[SkillLevel]:
        """获取最高等级（专三）数据"""
        return self.levels[-1] if self.levels else None


@dataclass
class TalentCandidate:
    """天赋候选（不同潜能/精英等级下的天赋）"""
    unlock_condition: Dict[str, Any] = field(default_factory=dict)
    required_potential: int = 0
    name: str = ""
    description: str = ""
    blackboard: Dict[str, float] = field(default_factory=dict)


@dataclass
class Talent:
    """天赋数据"""
    candidates: List[TalentCandidate] = field(default_factory=list)

    def get_candidate(self, elite: int, potential: int) -> Optional[TalentCandidate]:
        """获取符合条件的天赋"""
        matched = None
        for cand in self.candidates:
            cond = cand.unlock_condition
            req_elite_raw = cond.get("phase", 0)
            # 处理 "PHASE_X" 格式的字符串
            if isinstance(req_elite_raw, str):
                req_elite = int(req_elite_raw.replace("PHASE_", "")) if "PHASE_" in req_elite_raw else 0
            else:
                req_elite = req_elite_raw
            req_potential = cand.required_potential

            if elite >= req_elite and potential >= req_potential:
                matched = cand  # 取最高匹配
        return matched


@dataclass
class ModuleLevel:
    """模组等级数据"""
    level: int = 1
    attributes: Dict[str, float] = field(default_factory=dict)
    talent_effect: str = ""
    trait_effect: str = ""
    blackboard: Dict[str, float] = field(default_factory=dict)  # 天赋效果blackboard
    trait_blackboard: Dict[str, float] = field(default_factory=dict)  # 特性效果blackboard


@dataclass
class Module:
    """模组数据"""
    uniequip_id: str = ""
    uniequip_name: str = ""
    type_icon: str = ""
    char_id: str = ""  # 关联的干员ID
    levels: List[ModuleLevel] = field(default_factory=list)


@dataclass
class Character:
    """干员数据"""
    char_id: str = ""
    name: str = ""
    appellation: str = ""  # 英文代号
    profession: str = ""   # 职业
    sub_profession: str = ""  # 子职业
    rarity: int = 0        # 0-5 对应 1-6星
    position: str = ""     # MELEE/RANGED

    # 各精英阶段属性
    phases: List[PhaseAttributes] = field(default_factory=list)

    # 技能引用ID列表
    skill_ids: List[str] = field(default_factory=list)

    # 天赋
    talents: List[Talent] = field(default_factory=list)

    # 信赖加成
    favor_key_frames: List[Dict[str, float]] = field(default_factory=list)

    # 潜能加成
    potential_ranks: List[Dict[str, Any]] = field(default_factory=list)

    def get_phase_attrs(self, elite: int, level: int) -> Optional[PhaseAttributes]:
        """获取指定精英等级的属性"""
        if 0 <= elite < len(self.phases):
            return self.phases[elite]
        return None

    def get_trust_bonus(self, trust: int = 200) -> Dict[str, float]:
        """获取信赖加成（默认满信赖200%）"""
        # favor_key_frames 通常有两个：0信赖和满信赖
        if not self.favor_key_frames:
            return {}

        max_frame = self.favor_key_frames[-1] if len(self.favor_key_frames) > 1 else self.favor_key_frames[0]
        ratio = min(trust, 200) / 200.0

        return {
            "max_hp": max_frame.get("maxHp", 0) * ratio,
            "atk": max_frame.get("atk", 0) * ratio,
            "defense": max_frame.get("def", 0) * ratio,
        }


@dataclass
class Enemy:
    """敌人数据"""
    enemy_id: str = ""
    name: str = ""
    description: str = ""
    enemy_level: str = ""  # NORMAL/ELITE/BOSS

    # 属性
    max_hp: int = 0
    atk: int = 0
    defense: int = 0
    magic_resistance: float = 0

    # 其他
    move_speed: float = 1.0
    attack_speed: float = 100
    base_attack_time: float = 2.0
    weight: int = 0
    life_point: int = 1


class GameDataLoader:
    """游戏数据加载器"""

    def __init__(self, gamedata_dir: Path = GAMEDATA_DIR):
        self.gamedata_dir = gamedata_dir
        self._characters: Dict[str, Character] = {}
        self._skills: Dict[str, Skill] = {}
        self._modules: Dict[str, Module] = {}
        self._char_modules: Dict[str, List[Module]] = {}  # char_id -> [modules]
        self._enemies: Dict[str, Enemy] = {}
        self._name_mapping: Dict[str, str] = {}  # 名字 -> char_id
        self._loaded = False

    def load(self):
        """加载所有数据"""
        if self._loaded:
            return

        self._load_characters()
        self._load_skills()
        self._load_modules()
        self._load_enemies()
        self._load_name_mapping()
        self._loaded = True

        print(f"[GameDataLoader] 数据加载完成:")
        print(f"  干员: {len(self._characters)}")
        print(f"  技能: {len(self._skills)}")
        print(f"  模组: {len(self._modules)}")
        print(f"  敌人: {len(self._enemies)}")

    def _load_characters(self):
        """加载干员数据"""
        char_file = self.gamedata_dir / "character_table.json"
        if not char_file.exists():
            print(f"[GameDataLoader] 警告: {char_file} 不存在")
            return

        with open(char_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        for char_id, char_data in data.items():
            # 跳过召唤物和陷阱
            if char_id.startswith(("trap_", "token_")):
                continue
            if char_data.get("profession") in ["TOKEN", "TRAP"]:
                continue

            char = self._parse_character(char_id, char_data)
            self._characters[char_id] = char

    def _parse_character(self, char_id: str, data: dict) -> Character:
        """解析单个干员数据"""
        # 解析稀有度 (可能是数字或"TIER_X"格式)
        rarity_raw = data.get("rarity", 0)
        if isinstance(rarity_raw, str):
            rarity = int(rarity_raw.replace("TIER_", "")) - 1 if "TIER_" in rarity_raw else 0
        else:
            rarity = rarity_raw

        char = Character(
            char_id=char_id,
            name=data.get("name", ""),
            appellation=data.get("appellation", ""),
            profession=data.get("profession", ""),
            sub_profession=data.get("subProfessionId", ""),
            rarity=rarity,
            position=data.get("position", ""),
        )

        # 解析精英阶段属性
        for phase_data in data.get("phases", []):
            attrs = self._parse_phase_attributes(phase_data)
            char.phases.append(attrs)

        # 提取技能ID
        for skill_data in data.get("skills", []):
            skill_id = skill_data.get("skillId")
            if skill_id:
                char.skill_ids.append(skill_id)

        # 解析天赋
        talents_data = data.get("talents") or []
        for talent_data in talents_data:
            if talent_data:
                talent = self._parse_talent(talent_data)
                char.talents.append(talent)

        # 信赖加成
        favor_data = data.get("favorKeyFrames") or []
        for frame in favor_data:
            char.favor_key_frames.append(frame.get("data", {}))

        # 潜能加成
        char.potential_ranks = data.get("potentialRanks") or []

        return char

    def _parse_phase_attributes(self, phase_data: dict) -> PhaseAttributes:
        """解析精英阶段属性"""
        # attributesKeyFrames: [level_1, level_max]
        key_frames = phase_data.get("attributesKeyFrames", [])
        if not key_frames:
            return PhaseAttributes()

        # 取满级属性
        max_frame = key_frames[-1].get("data", {})

        return PhaseAttributes(
            max_hp=max_frame.get("maxHp", 0),
            atk=max_frame.get("atk", 0),
            defense=max_frame.get("def", 0),
            magic_resistance=max_frame.get("magicResistance", 0),
            cost=max_frame.get("cost", 0),
            block_cnt=max_frame.get("blockCnt", 0),
            base_attack_time=max_frame.get("baseAttackTime", 1.0),
            respawn_time=max_frame.get("respawnTime", 70),
        )

    def _parse_talent(self, talent_data: dict) -> Talent:
        """解析天赋数据"""
        talent = Talent()

        for cand_data in talent_data.get("candidates", []):
            if not cand_data:
                continue

            cand = TalentCandidate(
                unlock_condition=cand_data.get("unlockCondition", {}),
                required_potential=cand_data.get("requiredPotentialRank", 0),
                name=cand_data.get("name", ""),
                description=cand_data.get("description", ""),
            )

            # 解析blackboard
            for item in cand_data.get("blackboard", []):
                key = item.get("key", "")
                value = item.get("value", 0)
                cand.blackboard[key] = value

            talent.candidates.append(cand)

        return talent

    def _load_skills(self):
        """加载技能数据"""
        skill_file = self.gamedata_dir / "skill_table.json"
        if not skill_file.exists():
            return

        with open(skill_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        for skill_id, skill_data in data.items():
            skill = self._parse_skill(skill_id, skill_data)
            self._skills[skill_id] = skill

    def _parse_skill(self, skill_id: str, data: dict) -> Skill:
        """解析技能数据"""
        skill = Skill(
            skill_id=skill_id,
            icon_id=data.get("iconId", ""),
        )

        for level_data in data.get("levels", []):
            level = self._parse_skill_level(level_data)
            skill.levels.append(level)

        return skill

    def _parse_skill_level(self, data: dict) -> SkillLevel:
        """解析技能等级数据"""
        sp_data = data.get("spData", {})

        level = SkillLevel(
            name=data.get("name", ""),
            description=data.get("description", ""),
            skill_type=data.get("skillType", 0),
            sp_type=sp_data.get("spType", 1),
            sp_cost=sp_data.get("spCost", 0),
            init_sp=sp_data.get("initSp", 0),
            duration=data.get("duration", 0),
        )

        # 解析blackboard - 关键数值
        for item in data.get("blackboard", []):
            key = item.get("key", "")
            value = item.get("value", 0)
            level.blackboard[key] = value

        return level

    def _load_modules(self):
        """加载模组数据"""
        # uniequip_table 包含模组基础信息
        equip_file = self.gamedata_dir / "uniequip_table.json"
        # battle_equip_table 包含模组战斗效果
        battle_file = self.gamedata_dir / "battle_equip_table.json"

        if not equip_file.exists():
            return

        with open(equip_file, "r", encoding="utf-8") as f:
            equip_data = json.load(f)

        battle_data = {}
        if battle_file.exists():
            with open(battle_file, "r", encoding="utf-8") as f:
                battle_data = json.load(f)

        # 解析模组
        for equip_id, equip_info in equip_data.get("equipDict", {}).items():
            char_id = equip_info.get("charId", "")
            equip_type = equip_info.get("type", "")

            # 跳过INITIAL类型（证章），只保留真正的模组
            if equip_type == "INITIAL":
                continue

            module = Module(
                uniequip_id=equip_id,
                uniequip_name=equip_info.get("uniEquipName", ""),
                type_icon=equip_info.get("typeIcon", ""),
                char_id=char_id,
            )

            # 从battle_equip_table获取战斗效果
            if equip_id in battle_data:
                battle_info = battle_data[equip_id]
                for phase in battle_info.get("phases", []):
                    mod_level = ModuleLevel(
                        level=phase.get("equipLevel", 1),
                    )

                    # 属性加成
                    for attr in (phase.get("attributeBlackboard") or []):
                        key = attr.get("key", "")
                        value = attr.get("value", 0)
                        mod_level.attributes[key] = value

                    # 天赋效果和特性效果的blackboard
                    for part in (phase.get("parts") or []):
                        # 天赋效果
                        talent_bundle = part.get("addOrOverrideTalentDataBundle")
                        if talent_bundle:
                            candidates = talent_bundle.get("candidates") or []
                            for cand in candidates:
                                if cand:
                                    for item in (cand.get("blackboard") or []):
                                        mod_level.blackboard[item.get("key", "")] = item.get("value", 0)

                        # 特性效果（如"2敌人时攻速+12"等条件触发效果）
                        trait_bundle = part.get("overrideTraitDataBundle")
                        if trait_bundle:
                            candidates = trait_bundle.get("candidates") or []
                            for cand in candidates:
                                if cand:
                                    for item in (cand.get("blackboard") or []):
                                        mod_level.trait_blackboard[item.get("key", "")] = item.get("value", 0)

                    module.levels.append(mod_level)

            self._modules[equip_id] = module

            # 建立 char_id -> modules 映射
            if char_id:
                if char_id not in self._char_modules:
                    self._char_modules[char_id] = []
                self._char_modules[char_id].append(module)

    def _load_enemies(self):
        """加载敌人数据"""
        enemy_file = self.gamedata_dir / "enemy_handbook_table.json"
        if not enemy_file.exists():
            return

        with open(enemy_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        # enemyData 是字典，键为enemy_id
        enemy_data_dict = data.get("enemyData") or {}
        for enemy_id, enemy_info in enemy_data_dict.items():
            enemy = self._parse_enemy(enemy_info)
            self._enemies[enemy.enemy_id] = enemy

    def _parse_enemy(self, data: dict) -> Enemy:
        """解析敌人数据（从handbook表，只有基础信息）"""
        # 注意：enemy_handbook_table 只有描述信息
        # 详细战斗数值在 levels/enemydata 目录下
        return Enemy(
            enemy_id=data.get("enemyId", ""),
            name=data.get("name", ""),
            description=data.get("description", ""),
            enemy_level=data.get("enemyLevel", "NORMAL"),
            # 以下字段handbook表里没有，保持默认值
            max_hp=0,
            atk=0,
            defense=0,
            magic_resistance=0,
        )

    def _load_name_mapping(self):
        """加载名字映射"""
        mapping_file = INDEX_DIR / "operator_mapping.json"
        if mapping_file.exists():
            with open(mapping_file, "r", encoding="utf-8") as f:
                mapping = json.load(f)
            self._name_mapping = mapping.get("by_name", {})
        else:
            # 从已加载的角色数据生成
            for char_id, char in self._characters.items():
                self._name_mapping[char.name] = char_id

    # ========== 查询接口 ==========

    def get_character(self, name_or_id: str) -> Optional[Character]:
        """根据名字或ID获取干员"""
        self.load()

        # 直接ID匹配
        if name_or_id in self._characters:
            return self._characters[name_or_id]

        # 名字映射
        char_id = self._name_mapping.get(name_or_id)
        if char_id:
            return self._characters.get(char_id)

        # 模糊匹配
        for char_id, char in self._characters.items():
            if name_or_id in char.name or name_or_id in char.appellation:
                return char

        return None

    def get_skill(self, skill_id: str) -> Optional[Skill]:
        """获取技能数据"""
        self.load()
        return self._skills.get(skill_id)

    def get_character_skills(self, char: Character) -> List[Skill]:
        """获取干员的所有技能"""
        self.load()
        skills = []
        for skill_id in char.skill_ids:
            skill = self._skills.get(skill_id)
            if skill:
                skills.append(skill)
        return skills

    def get_module(self, module_id: str) -> Optional[Module]:
        """获取模组数据"""
        self.load()
        return self._modules.get(module_id)

    def get_character_modules(self, char_id: str) -> List[Module]:
        """获取干员的所有模组"""
        self.load()
        return self._char_modules.get(char_id, [])

    def get_enemy(self, name_or_id: str) -> Optional[Enemy]:
        """获取敌人数据"""
        self.load()

        if name_or_id in self._enemies:
            return self._enemies[name_or_id]

        # 名字匹配
        for enemy_id, enemy in self._enemies.items():
            if name_or_id in enemy.name:
                return enemy

        return None

    def search_characters(self, keyword: str) -> List[Character]:
        """搜索干员"""
        self.load()
        results = []
        keyword = keyword.lower()

        for char in self._characters.values():
            if (keyword in char.name.lower() or
                keyword in char.appellation.lower()):
                results.append(char)

        return results


# 单例
_loader_instance: Optional[GameDataLoader] = None


def get_gamedata_loader() -> GameDataLoader:
    """获取数据加载器单例"""
    global _loader_instance
    if _loader_instance is None:
        _loader_instance = GameDataLoader()
    return _loader_instance
