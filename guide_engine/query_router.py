"""
查询路由模块 - 智能判断用户问题应该查询哪些数据源

三层查询模式：
- wiki_only: 基础信息查询（干员属性、技能描述等）
- calculation: 精确计算（DPS、伤害计算，需要层级1数据+计算服务）
- full: 攻略建议（需要层级1+2+攻略内容）
"""

import re
from typing import Dict, Any, Optional, List, Tuple
from enum import Enum
from dataclasses import dataclass, field


class QueryMode(str, Enum):
    """查询模式枚举"""
    WIKI_ONLY = "wiki_only"      # 层级1：基础信息查询
    CALCULATION = "calculation"  # 层级2：精确计算
    FULL = "full"                # 层级3：攻略建议


@dataclass
class ExtractedEntities:
    """从用户问题中提取的实体"""
    # 干员相关
    operator_names: List[str] = field(default_factory=list)

    # 技能相关
    skill_index: Optional[int] = None      # 0/1/2 对应 S1/S2/S3
    skill_level: Optional[int] = None      # 1-7 普通等级
    mastery: Optional[int] = None          # 0/1/2/3 专精等级

    # 敌人相关
    enemy_defense: Optional[int] = None    # 敌人防御
    enemy_res: Optional[float] = None      # 敌人法抗
    enemy_name: Optional[str] = None       # 敌人名称

    # 其他
    elite: Optional[int] = None            # 精英等级 0/1/2
    trust: Optional[int] = None            # 信赖度
    potential: Optional[int] = None        # 潜能 1-6
    module_level: Optional[int] = None     # 模组等级 0/1/2/3

    def get_final_skill_level(self) -> int:
        """获取最终技能等级（1-10）"""
        if self.mastery is not None:
            return 7 + self.mastery  # M0=7, M1=8, M2=9, M3=10
        if self.skill_level is not None:
            return self.skill_level
        return 10  # 默认M3


@dataclass
class RouteResult:
    """路由结果"""
    mode: QueryMode
    reason: str
    entities: ExtractedEntities = field(default_factory=ExtractedEntities)


class QueryRouter:
    """查询路由器 - 根据用户问题决定查询模式并提取实体"""

    def __init__(self, llm_service=None):
        self.llm = llm_service

        # ========== 计算类关键词（最高优先级）==========
        self.calculation_keywords = {
            "DPS": ["dps", "DPS", "秒伤", "每秒伤害"],
            "伤害": ["总伤", "伤害是多少", "能打多少", "打多少伤害",
                    "伤害计算", "计算伤害", "输出是多少"],
            "攻击": ["实际攻击力", "面板攻击", "最终攻击"],
        }

        # 强制计算模式的正则
        self.force_calculation_patterns = [
            r"(dps|DPS|秒伤)",
            r"(总伤|伤害).*(是多少|多少|计算)",
            r"打(\d+)(防|法抗).*敌人",
            r"对(\d+)(防御|法抗)",
            r"(S[123]|[一二三]技能).*(M[0-3]|专精|专[一二三满])?.*(dps|DPS|伤害)",
        ]

        # ========== Wiki类关键词 ==========
        self.wiki_keywords = {
            "属性": ["攻击力", "防御力", "生命值", "血量", "攻速", "攻击间隔",
                    "法抗", "物抗", "暴击", "爆伤", "面板", "数值", "属性"],
            "技能": ["技能是什么", "技能效果", "技能描述", "天赋是什么", "天赋效果",
                    "被动是什么", "被动效果", "固有技能"],
            "基础": ["稀有度", "星级", "几星", "职业是", "定位是", "获取方式",
                    "怎么获得", "哪里获取", "分支", "阵营"],
            "疑问": ["是什么", "有哪些", "是多少", "多少钱", "需要什么材料"],
        }

        self.force_wiki_patterns = [
            r"^.{0,5}(技能|天赋|被动)是什么",
            r"(攻击力|防御力|生命值|血量)是?多少",
            r"^(查|查询|查一下).{0,10}(数据|属性|面板)",
            r"(稀有度|星级|职业)是什么",
        ]

        # ========== 攻略类关键词 ==========
        self.guide_keywords = {
            "培养": ["怎么养", "怎么练", "培养", "练度", "优先级", "值不值",
                    "值得吗", "要不要", "该不该", "先练谁", "练谁", "养谁",
                    "先抽谁", "抽谁", "新手"],
            "配队": ["配队", "阵容", "搭配", "组队", "带什么", "配什么",
                    "队伍", "编队", "组合"],
            "策略": ["怎么打", "怎么用", "怎么玩", "技巧", "手法", "打法",
                    "思路", "攻略", "教程", "机制"],
            "评价": ["强不强", "好不好", "厉害吗", "推荐", "建议", "评价",
                    "评测", "分析", "对比", "比较", "哪个好", "和.*比"],
            "抽卡": ["抽不抽", "要抽吗", "抽吗", "up", "卡池", "必抽"],
            "装备": ["带什么", "用什么", "选什么", "毕业", "最强", "最好"],
        }

        self.force_full_patterns = [
            r"怎么(养|练|培养|玩|用|打)",
            r"(配队|阵容|搭配|编队)",
            r"(值不值|值得|该不该|要不要)",
            r"(推荐|建议).*(养|练|抽|用)",
            r"(强不强|厉害|好用)",
        ]

        # ========== 实体提取正则 ==========
        self.skill_patterns = [
            # S1/S2/S3 格式
            (r"[Ss]([123])", "skill_index"),
            # 一技能/二技能/三技能
            (r"([一二三1-3])技能", "skill_index"),
            # 第X个技能
            (r"第([一二三1-3])个?技能", "skill_index"),
        ]

        self.mastery_patterns = [
            # M0/M1/M2/M3
            (r"[Mm]([0-3])", "mastery"),
            # 专精一/专精二/专精三
            (r"专精([一二三零0-3])", "mastery"),
            # 专一/专二/专三
            (r"专([一二三零0-3])", "mastery"),
            # 满专/满专精
            (r"(满专精?|专满)", "mastery_max"),
            # 7级（未专精）
            (r"(\d)级", "skill_level"),
        ]

        self.defense_patterns = [
            # 800防/800防御
            (r"(\d+)\s*防(?:御)?", "defense"),
            # 打800防敌人
            (r"打\s*(\d+)\s*防", "defense"),
            # 对800防御
            (r"对\s*(\d+)\s*防御?", "defense"),
        ]

        self.res_patterns = [
            # 50法抗/50%法抗
            (r"(\d+)%?\s*法抗", "res"),
        ]

        # 中文数字映射
        self.cn_num_map = {
            "零": 0, "一": 1, "二": 2, "三": 3,
            "0": 0, "1": 1, "2": 2, "3": 3,
        }

    def extract_entities(self, query: str) -> ExtractedEntities:
        """从用户问题中提取实体"""
        entities = ExtractedEntities()

        # 提取技能索引
        for pattern, _ in self.skill_patterns:
            match = re.search(pattern, query)
            if match:
                val = match.group(1)
                num = self.cn_num_map.get(val, int(val) if val.isdigit() else None)
                if num is not None:
                    entities.skill_index = num - 1  # 转为0-based索引
                break

        # 提取专精等级
        for pattern, ptype in self.mastery_patterns:
            match = re.search(pattern, query)
            if match:
                if ptype == "mastery_max":
                    entities.mastery = 3
                elif ptype == "skill_level":
                    level = int(match.group(1))
                    if level <= 7:
                        entities.skill_level = level
                else:
                    val = match.group(1)
                    num = self.cn_num_map.get(val, int(val) if val.isdigit() else None)
                    if num is not None:
                        entities.mastery = num
                break

        # 提取敌人防御
        for pattern, _ in self.defense_patterns:
            match = re.search(pattern, query)
            if match:
                entities.enemy_defense = int(match.group(1))
                break

        # 提取敌人法抗
        for pattern, _ in self.res_patterns:
            match = re.search(pattern, query)
            if match:
                entities.enemy_res = float(match.group(1))
                break

        # 默认值
        if entities.skill_index is None:
            entities.skill_index = 2  # 默认S3
        if entities.mastery is None and entities.skill_level is None:
            entities.mastery = 3  # 默认M3

        return entities

    def _check_keywords(self, query: str, keyword_dict: Dict[str, list]) -> Tuple[bool, list]:
        """检查问题是否命中关键词"""
        matched = []
        for category, keywords in keyword_dict.items():
            for kw in keywords:
                if ".*" in kw or "^" in kw:
                    if re.search(kw, query):
                        matched.append((category, kw))
                elif kw.lower() in query.lower():
                    matched.append((category, kw))
        return len(matched) > 0, matched

    def _check_patterns(self, query: str, patterns: list) -> bool:
        """检查是否命中正则模式"""
        for pattern in patterns:
            if re.search(pattern, query, re.IGNORECASE):
                return True
        return False

    def route_by_rules(self, query: str) -> Tuple[Optional[QueryMode], str]:
        """使用规则匹配判断查询模式"""
        query = query.strip()

        # 1. 最高优先级：检查计算模式
        if self._check_patterns(query, self.force_calculation_patterns):
            return QueryMode.CALCULATION, "命中计算模式"

        calc_hit, calc_matches = self._check_keywords(query, self.calculation_keywords)
        if calc_hit:
            return QueryMode.CALCULATION, f"命中计算关键词: {calc_matches[0]}"

        # 2. 检查强制wiki模式
        if self._check_patterns(query, self.force_wiki_patterns):
            return QueryMode.WIKI_ONLY, "命中强制wiki模式"

        # 3. 检查强制攻略模式
        if self._check_patterns(query, self.force_full_patterns):
            return QueryMode.FULL, "命中强制全查询模式"

        # 4. 检查关键词
        wiki_hit, wiki_matches = self._check_keywords(query, self.wiki_keywords)
        guide_hit, guide_matches = self._check_keywords(query, self.guide_keywords)

        if wiki_hit and not guide_hit:
            return QueryMode.WIKI_ONLY, f"命中wiki关键词: {wiki_matches[0]}"

        if guide_hit and not wiki_hit:
            return QueryMode.FULL, f"命中攻略关键词: {guide_matches[0]}"

        if wiki_hit and guide_hit:
            return None, f"关键词冲突: wiki={wiki_matches}, guide={guide_matches}"

        return None, "未命中任何关键词"

    async def route_by_llm(self, query: str) -> Tuple[QueryMode, str]:
        """使用LLM判断查询模式"""
        if not self.llm:
            return QueryMode.FULL, "无LLM服务，默认全查询"

        prompt = """判断用户问题的类型，只回复A、B或C：

A = 查询基础数据（角色属性、技能描述、数值、星级等客观信息）
B = 需要精确计算（DPS计算、伤害计算、数值对比等需要计算的问题）
C = 需要攻略建议（培养建议、配队推荐、打法技巧、评价对比等主观建议）

用户问题："""

        try:
            import google.generativeai as genai

            model = genai.GenerativeModel('gemini-2.0-flash')

            response = await self._call_llm(model, prompt + query)
            result = response.strip().upper()

            if "A" in result and "B" not in result and "C" not in result:
                return QueryMode.WIKI_ONLY, "LLM判断为基础数据查询"
            elif "B" in result:
                return QueryMode.CALCULATION, "LLM判断为精确计算"
            else:
                return QueryMode.FULL, "LLM判断为攻略建议查询"

        except Exception as e:
            print(f"LLM路由判断失败: {e}")
            return QueryMode.FULL, f"LLM判断失败，默认全查询: {e}"

    async def _call_llm(self, model, prompt: str) -> str:
        """调用LLM"""
        import asyncio

        response = await asyncio.to_thread(
            model.generate_content,
            prompt,
            generation_config={
                "temperature": 0,
                "max_output_tokens": 10,
            }
        )
        return response.text

    async def route(self, query: str) -> RouteResult:
        """
        主路由方法 - 判断查询模式并提取实体

        Returns:
            RouteResult - 包含查询模式、原因和提取的实体
        """
        # 1. 提取实体
        entities = self.extract_entities(query)

        # 2. 规则匹配
        mode, reason = self.route_by_rules(query)

        if mode is not None:
            print(f"[QueryRouter] 规则匹配: {mode.value} - {reason}")
            return RouteResult(mode=mode, reason=reason, entities=entities)

        # 3. LLM判断
        print(f"[QueryRouter] 规则无法确定，调用LLM: {reason}")
        mode, reason = await self.route_by_llm(query)
        print(f"[QueryRouter] LLM判断: {mode.value} - {reason}")

        return RouteResult(mode=mode, reason=reason, entities=entities)

    def route_sync(self, query: str) -> RouteResult:
        """同步路由方法（仅使用规则，不调用LLM）"""
        entities = self.extract_entities(query)
        mode, reason = self.route_by_rules(query)

        if mode is None:
            mode = QueryMode.FULL
            reason = "规则无法确定，默认全查询"

        return RouteResult(mode=mode, reason=reason, entities=entities)


# 单例
_router_instance = None


def get_query_router(llm_service=None) -> QueryRouter:
    """获取查询路由器单例"""
    global _router_instance
    if _router_instance is None:
        _router_instance = QueryRouter(llm_service)
    return _router_instance
