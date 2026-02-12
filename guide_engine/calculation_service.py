"""
伤害计算服务

基于 ArknightsGameData 的结构化数据进行精确的伤害/DPS计算。

公式参考：
- 攻击间隔 = 基础攻击间隔 / (攻击速度 / 100)
- 物理伤害 = MAX(0.05 × ATK × 倍率, ATK × 倍率 - DEF)
- 法术伤害 = MAX(0.05 × ATK × 倍率, ATK × 倍率 × (1 - 0.01 × RES))
- 真实伤害 = ATK × 倍率
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple
from enum import Enum

from .gamedata_loader import (
    get_gamedata_loader,
    GameDataLoader,
    Character,
    Skill,
    SkillLevel,
    PhaseAttributes,
)


class DamageType(str, Enum):
    """伤害类型"""
    PHYSICAL = "physical"  # 物理
    MAGICAL = "magical"    # 法术
    TRUE = "true"          # 真实
    HEALING = "healing"    # 治疗


@dataclass
class CalculationParams:
    """计算参数"""
    # 干员配置
    operator_name: str = ""
    elite: int = 2          # 精英等级 0/1/2
    level: int = 90         # 等级
    trust: int = 200        # 信赖度
    potential: int = 1      # 潜能 1-6

    # 技能配置
    skill_index: int = 2    # 技能索引 0/1/2 (对应S1/S2/S3)
    skill_level: int = 10   # 技能等级 1-10 (7=lv7, 8=M1, 9=M2, 10=M3)

    # 模组配置
    module_id: Optional[str] = None  # 模组ID
    module_level: int = 0            # 模组等级 0/1/2/3

    # 敌人配置
    enemy_defense: int = 0           # 敌人防御
    enemy_res: float = 0             # 敌人法抗

    # 额外buff（来自其他干员、天赋等）
    extra_atk_flat: int = 0          # 固定攻击加成
    extra_atk_percent: float = 0     # 百分比攻击加成
    extra_attack_speed: float = 0    # 额外攻击速度
    defense_ignore: float = 0        # 无视防御比例 (0-1)
    res_ignore: float = 0            # 无视法抗比例 (0-1)


@dataclass
class CalculationResult:
    """计算结果"""
    # 基础信息
    operator_name: str = ""
    skill_name: str = ""
    skill_level_str: str = ""  # "7级" / "专精一" / "专精三"

    # 最终属性
    final_atk: float = 0
    final_attack_interval: float = 1.0
    final_attack_speed: float = 100

    # 伤害数值
    damage_per_hit: float = 0
    damage_type: DamageType = DamageType.PHYSICAL
    hits_per_second: float = 1.0
    dps: float = 0

    # 技能相关
    skill_duration: float = 0
    total_skill_damage: float = 0
    sp_cost: int = 0
    init_sp: int = 0

    # 计算过程（用于解释）
    calculation_steps: List[str] = field(default_factory=list)

    # 原始数据
    raw_blackboard: Dict[str, float] = field(default_factory=dict)


class CalculationService:
    """伤害计算服务"""

    def __init__(self):
        self.loader: GameDataLoader = get_gamedata_loader()

    def calculate(self, params: CalculationParams) -> Optional[CalculationResult]:
        """
        执行伤害计算

        Args:
            params: 计算参数

        Returns:
            CalculationResult 或 None（如果找不到干员/技能）
        """
        # 1. 获取干员数据
        char = self.loader.get_character(params.operator_name)
        if not char:
            return None

        # 2. 获取技能数据
        skills = self.loader.get_character_skills(char)
        if params.skill_index >= len(skills):
            return None

        skill = skills[params.skill_index]
        skill_level = skill.get_level(params.skill_level)
        if not skill_level:
            return None

        # 3. 创建结果对象
        result = CalculationResult(
            operator_name=char.name,
            skill_name=skill_level.name,
            skill_level_str=self._level_to_str(params.skill_level),
            raw_blackboard=skill_level.blackboard.copy(),
        )

        # 4. 计算最终攻击力
        result.final_atk = self._calc_final_atk(char, params, skill_level)
        result.calculation_steps.append(
            f"最终攻击力: {result.final_atk:.0f}"
        )

        # 5. 计算攻击间隔
        base_attack_time = char.phases[params.elite].base_attack_time if params.elite < len(char.phases) else 1.0
        result.final_attack_speed, result.final_attack_interval = self._calc_attack_interval(
            base_attack_time, skill_level, params, char
        )
        result.calculation_steps.append(
            f"攻击间隔: {result.final_attack_interval:.3f}s (攻速{result.final_attack_speed:.0f})"
        )

        # 6. 计算单次伤害
        result.damage_per_hit, result.damage_type = self._calc_damage(
            result.final_atk, skill_level, params
        )
        result.calculation_steps.append(
            f"单次伤害: {result.damage_per_hit:.0f} ({result.damage_type.value})"
        )

        # 7. 计算DPS
        result.hits_per_second = 1.0 / result.final_attack_interval
        result.dps = result.damage_per_hit * result.hits_per_second
        result.calculation_steps.append(
            f"DPS: {result.dps:.0f}"
        )

        # 8. 技能信息
        result.skill_duration = skill_level.duration
        result.sp_cost = skill_level.sp_cost
        result.init_sp = skill_level.init_sp

        # 9. 解析攻击段数（每次攻击的伤害实例数）
        attack_multiplier = self._parse_attack_multiplier(skill_level)

        if skill_level.duration > 0:
            total_hits = skill_level.duration / result.final_attack_interval
            # 总伤害 = 单次伤害 × 攻击段数 × 攻击次数
            result.total_skill_damage = result.damage_per_hit * attack_multiplier * total_hits

            if attack_multiplier > 1:
                result.calculation_steps.append(
                    f"攻击段数: 每次攻击{attack_multiplier}段"
                )
                result.calculation_steps.append(
                    f"技能总伤: {result.total_skill_damage:.0f} ({skill_level.duration}s内约{total_hits:.1f}次攻击 × {attack_multiplier}段)"
                )
            else:
                result.calculation_steps.append(
                    f"技能总伤: {result.total_skill_damage:.0f} ({skill_level.duration}s内约{total_hits:.1f}次攻击)"
                )

        return result

    def _calc_final_atk(
        self,
        char: Character,
        params: CalculationParams,
        skill_level: SkillLevel
    ) -> float:
        """计算最终攻击力"""
        # 基础攻击力（精英阶段满级）
        if params.elite >= len(char.phases):
            return 0

        base_atk = char.phases[params.elite].atk

        # 信赖加成
        trust_bonus = char.get_trust_bonus(params.trust)
        trust_atk = trust_bonus.get("atk", 0)

        # 潜能加成（简化处理，实际需要解析 potential_ranks）
        potential_atk = 0
        for i, rank in enumerate(char.potential_ranks):
            if i < params.potential - 1:  # potential 1-6, index 0-4
                buff = rank.get("buff")
                if buff and buff.get("attributes"):
                    for attr in buff["attributes"].get("attributeModifiers", []):
                        if attr.get("attributeType") == "ATK":
                            potential_atk += attr.get("value", 0)

        # 模组加成
        module_atk = 0
        if params.module_id and params.module_level > 0:
            module = self.loader.get_module(params.module_id)
            if module and params.module_level <= len(module.levels):
                mod_level = module.levels[params.module_level - 1]
                module_atk = mod_level.attributes.get("atk", 0)

        # 技能攻击力加成
        skill_atk_percent = 0
        for key, value in skill_level.blackboard.items():
            if "atk" in key.lower() and "scale" not in key.lower():
                # attack@atk 表示攻击力倍率加成 (1.1 = +110%)
                if value > 0 and value < 10:  # 排除 atk_scale 类的大数值
                    skill_atk_percent = value - 1  # 1.1 -> 0.1 = +10%

        # 额外buff
        extra_flat = params.extra_atk_flat
        extra_percent = params.extra_atk_percent

        # 计算最终攻击力
        # 公式: (基础 + 信赖 + 潜能 + 模组 + 固定加成) × (1 + 百分比加成)
        flat_total = base_atk + trust_atk + potential_atk + module_atk + extra_flat
        percent_total = 1 + skill_atk_percent + extra_percent

        return flat_total * percent_total

    def _calc_attack_interval(
        self,
        base_attack_time: float,
        skill_level: SkillLevel,
        params: CalculationParams,
        char: Character = None
    ) -> Tuple[float, float]:
        """
        计算攻击间隔

        Returns:
            (attack_speed, attack_interval)
        """
        # 基础攻速 100
        attack_speed = 100.0

        # 技能攻速加成
        for key, value in skill_level.blackboard.items():
            if "attack_speed" in key.lower():
                attack_speed += value

        # 天赋攻速加成（如毋畏遗忘等给自身攻速的天赋）
        if char:
            for talent in char.talents:
                cand = talent.get_candidate(params.elite, params.potential)
                if cand and "attack_speed" in cand.blackboard:
                    talent_attack_speed = cand.blackboard.get("attack_speed", 0)
                    attack_speed += talent_attack_speed

        # 模组攻速加成（属性部分）
        if params.module_id and params.module_level > 0:
            module = self.loader.get_module(params.module_id)
            if module and params.module_level <= len(module.levels):
                mod_level = module.levels[params.module_level - 1]
                # 基础属性攻速加成
                module_attack_speed = mod_level.attributes.get("attack_speed", 0)
                attack_speed += module_attack_speed
                # 特性攻速加成（如"2敌人时攻速+12"，满配默认触发条件）
                trait_attack_speed = mod_level.trait_blackboard.get("attack_speed", 0)
                attack_speed += trait_attack_speed

        # 额外攻速
        attack_speed += params.extra_attack_speed

        # 攻速限制 10-600
        attack_speed = max(10, min(600, attack_speed))

        # 计算实际攻击间隔
        # 公式: 基础攻击间隔 / (攻速 / 100)
        attack_interval = base_attack_time / (attack_speed / 100)

        return attack_speed, attack_interval

    def _calc_damage(
        self,
        final_atk: float,
        skill_level: SkillLevel,
        params: CalculationParams
    ) -> Tuple[float, DamageType]:
        """
        计算单次伤害

        Returns:
            (damage, damage_type)
        """
        # 获取伤害倍率
        atk_scale = 1.0
        for key, value in skill_level.blackboard.items():
            if "atk_scale" in key.lower():
                atk_scale = max(atk_scale, value)  # 取最大倍率

        # 判断伤害类型（简化：默认物理，后续可根据技能描述判断）
        damage_type = DamageType.PHYSICAL

        # 计算敌人有效防御/法抗
        enemy_def = params.enemy_defense * (1 - params.defense_ignore)
        enemy_res = params.enemy_res * (1 - params.res_ignore)

        # 计算伤害
        raw_damage = final_atk * atk_scale

        if damage_type == DamageType.PHYSICAL:
            # 物理伤害 = MAX(5%基础伤害, 基础伤害 - 防御)
            damage = max(raw_damage * 0.05, raw_damage - enemy_def)
        elif damage_type == DamageType.MAGICAL:
            # 法术伤害 = MAX(5%基础伤害, 基础伤害 × (1 - 法抗%))
            damage = max(raw_damage * 0.05, raw_damage * (1 - enemy_res / 100))
        else:
            # 真实伤害，无视防御
            damage = raw_damage

        return damage, damage_type

    def _level_to_str(self, level: int) -> str:
        """技能等级转中文"""
        if level <= 7:
            return f"{level}级"
        elif level == 8:
            return "专精一"
        elif level == 9:
            return "专精二"
        elif level == 10:
            return "专精三"
        return f"{level}级"

    def _parse_attack_multiplier(self, skill_level: SkillLevel) -> int:
        """
        从技能描述中解析攻击段数/伤害实例数

        识别模式：
        1. "各自演奏X个" -> 需要累加
        2. "发射X个" -> 直接使用
        3. "攻击X次" -> 直接使用
        4. 默认返回1

        Returns:
            每次攻击造成的伤害实例数量
        """
        import re

        desc = skill_level.description
        if not desc:
            return 1

        # 移除HTML标签
        desc_clean = re.sub(r'<[^>]+>', '', desc)

        # 规则1: "各自演奏X个" 或 "各自X个" (需要识别有几组)
        # 例如: "钢琴和风琴音色演奏，各自演奏2个" -> 2组，每组2个 = 4个
        pattern_each = r'各自.*?(\d+)\s*个'
        matches_each = re.findall(pattern_each, desc_clean)
        if matches_each:
            count_per_group = int(matches_each[0])
            # 尝试识别有几组 (钢琴和风琴 = 2组)
            if '钢琴' in desc_clean and '风琴' in desc_clean:
                return count_per_group * 2
            elif '和' in desc_clean:  # 简化判断：有"和"可能是2组
                return count_per_group * 2
            else:
                return count_per_group

        # 规则2: "发射X个" 或 "X个子弹/音符"
        pattern_shoot = r'发射\s*(\d+)\s*个|(\d+)\s*个.*?(?:子弹|音符|飞弹|箭)'
        matches_shoot = re.findall(pattern_shoot, desc_clean)
        if matches_shoot:
            for match in matches_shoot:
                num = match[0] if match[0] else match[1]
                if num:
                    return int(num)

        # 规则3: "攻击X次" 或 "连续攻击X次"
        pattern_times = r'攻击\s*(\d+)\s*次|连续.*?(\d+)\s*次'
        matches_times = re.findall(pattern_times, desc_clean)
        if matches_times:
            for match in matches_times:
                num = match[0] if match[0] else match[1]
                if num:
                    return int(num)

        # 规则4: "双击" 或 "二连击"
        if '双击' in desc_clean or '二连' in desc_clean:
            return 2

        # 规则5: "三连击" 或 "三段攻击"
        if '三连' in desc_clean or '三段' in desc_clean:
            return 3

        # 默认：单次攻击
        return 1

    # ========== 便捷方法 ==========

    def quick_dps(
        self,
        operator_name: str,
        skill_index: int = 2,
        mastery: int = 3,
        enemy_def: int = 0,
        enemy_res: float = 0,
    ) -> Optional[CalculationResult]:
        """
        快速计算DPS

        Args:
            operator_name: 干员名
            skill_index: 技能索引 0/1/2
            mastery: 专精等级 0/1/2/3
            enemy_def: 敌人防御
            enemy_res: 敌人法抗
        """
        # 专精转技能等级: M0=7, M1=8, M2=9, M3=10
        skill_level = 7 + mastery

        params = CalculationParams(
            operator_name=operator_name,
            skill_index=skill_index,
            skill_level=skill_level,
            enemy_defense=enemy_def,
            enemy_res=enemy_res,
        )

        return self.calculate(params)

    def format_result(self, result: CalculationResult) -> str:
        """格式化计算结果为易读文本"""
        lines = [
            f"{result.operator_name} - {result.skill_name}（{result.skill_level_str}）",
            "",
            f"最终攻击力: {result.final_atk:.0f}",
            f"攻击间隔: {result.final_attack_interval:.3f}秒 (攻速{result.final_attack_speed:.0f})",
            f"单次伤害: {result.damage_per_hit:.0f} ({result.damage_type.value})",
            f"DPS: {result.dps:.0f}",
        ]

        if result.skill_duration > 0:
            lines.append(f"技能持续: {result.skill_duration}秒")
            lines.append(f"技能总伤: {result.total_skill_damage:.0f}")

        lines.append(f"SP消耗: {result.sp_cost}, 初始SP: {result.init_sp}")

        return "\n".join(lines)


# 单例
_service_instance: Optional[CalculationService] = None


def get_calculation_service() -> CalculationService:
    """获取计算服务单例"""
    global _service_instance
    if _service_instance is None:
        _service_instance = CalculationService()
    return _service_instance
