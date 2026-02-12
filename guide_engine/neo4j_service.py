from typing import List, Dict, Any, Optional

from neo4j import AsyncGraphDatabase

from .models import get_guide_engine_settings


class Neo4jService:
    """Neo4j 图数据库服务"""

    def __init__(self):
        self._driver = None

    async def connect(self):
        """连接 Neo4j"""
        if self._driver is None:
            settings = get_guide_engine_settings()
            self._driver = AsyncGraphDatabase.driver(
                settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
            )

    async def close(self):
        """关闭连接"""
        if self._driver:
            await self._driver.close()
            self._driver = None

    async def execute_query(self, query: str, parameters: Dict = None) -> List[Dict]:
        """执行 Cypher 查询"""
        await self.connect()
        async with self._driver.session() as session:
            result = await session.run(query, parameters or {})
            return [record.data() async for record in result]

    # ============ 干员相关查询 ============

    async def get_operator(self, game_id: str, operator_name: str) -> Optional[Dict[str, Any]]:
        """获取干员完整信息"""
        query = """
        MATCH (o:Operator {game_id: $game_id})
        WHERE o.name = $name OR o.name_en = $name OR $name IN o.aliases
        OPTIONAL MATCH (o)-[:HAS_SKILL]->(s:Skill)
        OPTIONAL MATCH (o)-[:HAS_TALENT]->(t:Talent)
        OPTIONAL MATCH (o)-[:BELONGS_TO]->(f:Faction)
        WITH o, collect(DISTINCT s {.*}) as skills, collect(DISTINCT t {.*}) as talents, collect(DISTINCT f.name)[0] as faction
        RETURN o {
            .*,
            skills: skills,
            talents: talents,
            faction: faction
        } as operator
        """
        results = await self.execute_query(query, {"game_id": game_id, "name": operator_name})
        if results and results[0].get("operator"):
            return results[0]["operator"]
        return None

    async def get_operator_synergies(self, game_id: str, operator_name: str, limit: int = 5) -> List[Dict[str, Any]]:
        """获取干员配合推荐"""
        query = """
        MATCH (o:Operator {game_id: $game_id})-[r:SYNERGY_WITH]->(partner:Operator)
        WHERE o.name = $name OR o.name_en = $name OR $name IN o.aliases
        RETURN partner {
            .name, .name_en, .rarity, .class,
            synergy_reason: r.reason,
            synergy_score: r.score
        } as partner
        ORDER BY r.score DESC
        LIMIT $limit
        """
        results = await self.execute_query(query, {"game_id": game_id, "name": operator_name, "limit": limit})
        return [r["partner"] for r in results if r.get("partner")]

    async def get_operator_counters(self, game_id: str, operator_name: str) -> Dict[str, List[Dict]]:
        """获取干员克制关系"""
        query = """
        MATCH (o:Operator {game_id: $game_id})
        WHERE o.name = $name OR $name IN o.aliases
        OPTIONAL MATCH (o)-[c1:COUNTERS]->(countered:Operator)
        OPTIONAL MATCH (counter:Operator)-[c2:COUNTERS]->(o)
        RETURN
            collect(DISTINCT countered {.name, reason: c1.reason}) as counters,
            collect(DISTINCT counter {.name, reason: c2.reason}) as countered_by
        """
        results = await self.execute_query(query, {"game_id": game_id, "name": operator_name})
        if results:
            return {
                "counters": [c for c in results[0].get("counters", []) if c.get("name")],
                "countered_by": [c for c in results[0].get("countered_by", []) if c.get("name")],
            }
        return {"counters": [], "countered_by": []}

    async def search_operators(self, game_id: str, keyword: str, limit: int = 10) -> List[Dict[str, Any]]:
        """搜索干员"""
        query = """
        MATCH (o:Operator {game_id: $game_id})
        WHERE o.name CONTAINS $keyword
           OR o.name_en CONTAINS $keyword
           OR ANY(alias IN o.aliases WHERE alias CONTAINS $keyword)
        RETURN o {.id, .name, .name_en, .rarity, .class, .branch} as operator
        LIMIT $limit
        """
        results = await self.execute_query(query, {"game_id": game_id, "keyword": keyword, "limit": limit})
        return [r["operator"] for r in results if r.get("operator")]

    # ============ 图谱初始化 ============

    async def init_constraints(self):
        """初始化图数据库约束和索引"""
        constraints = [
            "CREATE CONSTRAINT IF NOT EXISTS FOR (o:Operator) REQUIRE (o.game_id, o.id) IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (s:Skill) REQUIRE (s.game_id, s.id) IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (f:Faction) REQUIRE (f.game_id, f.id) IS UNIQUE",
            "CREATE INDEX IF NOT EXISTS FOR (o:Operator) ON (o.name)",
            "CREATE INDEX IF NOT EXISTS FOR (o:Operator) ON (o.name_en)",
            "CREATE INDEX IF NOT EXISTS FOR (o:Operator) ON (o.game_id)",
        ]

        for constraint in constraints:
            try:
                await self.execute_query(constraint)
            except Exception as e:
                # 忽略已存在的约束错误
                if "already exists" not in str(e).lower():
                    print(f"Warning: {e}")

    async def import_operator(self, game_id: str, operator: Dict[str, Any]):
        """导入单个干员数据"""
        # 创建干员节点
        await self.execute_query(
            """
            MERGE (o:Operator {game_id: $game_id, id: $id})
            SET o.name = $name,
                o.name_en = $name_en,
                o.rarity = $rarity,
                o.class = $class,
                o.branch = $branch,
                o.trait = $trait,
                o.obtain = $obtain,
                o.aliases = $aliases,
                o.tags = $tags
        """,
            {
                "game_id": game_id,
                "id": operator["id"],
                "name": operator["name"],
                "name_en": operator.get("name_en", ""),
                "rarity": operator.get("rarity", 0),
                "class": operator.get("class", ""),
                "branch": operator.get("branch", ""),
                "trait": operator.get("trait", ""),
                "obtain": operator.get("obtain", ""),
                "aliases": operator.get("aliases", []),
                "tags": operator.get("tags", []),
            },
        )

        # 创建技能节点和关系
        for i, skill in enumerate(operator.get("skills", []), 1):
            skill_id = f"{operator['id']}_skill_{i}"
            await self.execute_query(
                """
                MERGE (s:Skill {game_id: $game_id, id: $skill_id})
                SET s.name = $name,
                    s.type = $type,
                    s.charge_type = $charge_type,
                    s.description = $description,
                    s.mastery_recommendation = $mastery_recommendation,
                    s.skill_index = $skill_index
                WITH s
                MATCH (o:Operator {game_id: $game_id, id: $operator_id})
                MERGE (o)-[:HAS_SKILL]->(s)
            """,
                {
                    "game_id": game_id,
                    "skill_id": skill_id,
                    "operator_id": operator["id"],
                    "name": skill.get("name", ""),
                    "type": skill.get("type", ""),
                    "charge_type": skill.get("charge_type", ""),
                    "description": skill.get("description", ""),
                    "mastery_recommendation": skill.get("mastery_recommendation", ""),
                    "skill_index": i,
                },
            )

        # 创建天赋节点和关系
        for i, talent in enumerate(operator.get("talents", []), 1):
            talent_id = f"{operator['id']}_talent_{i}"
            await self.execute_query(
                """
                MERGE (t:Talent {game_id: $game_id, id: $talent_id})
                SET t.name = $name,
                    t.description = $description
                WITH t
                MATCH (o:Operator {game_id: $game_id, id: $operator_id})
                MERGE (o)-[:HAS_TALENT]->(t)
            """,
                {
                    "game_id": game_id,
                    "talent_id": talent_id,
                    "operator_id": operator["id"],
                    "name": talent.get("name", ""),
                    "description": talent.get("description", ""),
                },
            )

    async def import_operators(self, game_id: str, operators: List[Dict[str, Any]]) -> int:
        """批量导入干员数据"""
        count = 0
        for operator in operators:
            await self.import_operator(game_id, operator)
            count += 1
        return count

    async def create_synergy_relationship(
        self, game_id: str, operator1_name: str, operator2_name: str, reason: str, score: int = 5
    ):
        """创建干员配合关系"""
        await self.execute_query(
            """
            MATCH (o1:Operator {game_id: $game_id})
            WHERE o1.name = $op1 OR $op1 IN o1.aliases
            MATCH (o2:Operator {game_id: $game_id})
            WHERE o2.name = $op2 OR $op2 IN o2.aliases
            MERGE (o1)-[r:SYNERGY_WITH]->(o2)
            SET r.reason = $reason, r.score = $score
        """,
            {"game_id": game_id, "op1": operator1_name, "op2": operator2_name, "reason": reason, "score": score},
        )

    async def create_faction(self, game_id: str, faction_id: str, name: str, description: str = ""):
        """创建阵营"""
        await self.execute_query(
            """
            MERGE (f:Faction {game_id: $game_id, id: $id})
            SET f.name = $name, f.description = $description
        """,
            {"game_id": game_id, "id": faction_id, "name": name, "description": description},
        )

    async def assign_operator_to_faction(self, game_id: str, operator_name: str, faction_id: str):
        """分配干员到阵营"""
        await self.execute_query(
            """
            MATCH (o:Operator {game_id: $game_id})
            WHERE o.name = $op_name OR $op_name IN o.aliases
            MATCH (f:Faction {game_id: $game_id, id: $faction_id})
            MERGE (o)-[:BELONGS_TO]->(f)
        """,
            {"game_id": game_id, "op_name": operator_name, "faction_id": faction_id},
        )

    async def clear_game_data(self, game_id: str):
        """清除游戏的所有图数据"""
        await self.execute_query(
            """
            MATCH (n {game_id: $game_id})
            DETACH DELETE n
        """,
            {"game_id": game_id},
        )

    async def get_stats(self, game_id: str) -> Dict[str, int]:
        """获取图数据库统计信息"""
        query = """
        MATCH (o:Operator {game_id: $game_id})
        OPTIONAL MATCH (o)-[:HAS_SKILL]->(s:Skill)
        OPTIONAL MATCH (o)-[:SYNERGY_WITH]->(partner:Operator)
        RETURN
            count(DISTINCT o) as operator_count,
            count(DISTINCT s) as skill_count,
            count(DISTINCT partner) as synergy_count
        """
        results = await self.execute_query(query, {"game_id": game_id})
        if results:
            return results[0]
        return {"operator_count": 0, "skill_count": 0, "synergy_count": 0}

    # ============ Kantai Collection queries ============

    async def get_ship(self, game_id: str, ship_name: str) -> Optional[Dict[str, Any]]:
        """获取我方舰船信息"""
        query = """
        MATCH (s:Ship {game_id: $game_id})
        WHERE s.name = $name
        RETURN s {.*} as ship
        LIMIT 1
        """
        results = await self.execute_query(query, {"game_id": game_id, "name": ship_name})
        if results and results[0].get("ship"):
            return results[0]["ship"]
        return None

    async def get_enemy_ship(self, game_id: str, enemy_name: str) -> Optional[Dict[str, Any]]:
        """获取敌方舰船信息"""
        query = """
        MATCH (e:EnemyShip {game_id: $game_id})
        WHERE e.name = $name
        RETURN e {.*} as ship
        LIMIT 1
        """
        results = await self.execute_query(query, {"game_id": game_id, "name": enemy_name})
        if results and results[0].get("ship"):
            return results[0]["ship"]
        return None

    async def find_ship_in_text(self, game_id: str, text: str) -> Optional[Dict[str, Any]]:
        """在文本中匹配我方舰船名称"""
        query = """
        MATCH (s:Ship {game_id: $game_id})
        WHERE $text CONTAINS s.name
        RETURN s {.*} as ship
        LIMIT 1
        """
        results = await self.execute_query(query, {"game_id": game_id, "text": text})
        if results and results[0].get("ship"):
            return results[0]["ship"]
        return None

    async def find_enemy_in_text(self, game_id: str, text: str) -> Optional[Dict[str, Any]]:
        """在文本中匹配敌方舰船名称"""
        query = """
        MATCH (e:EnemyShip {game_id: $game_id})
        WHERE $text CONTAINS e.name
        RETURN e {.*} as ship
        LIMIT 1
        """
        results = await self.execute_query(query, {"game_id": game_id, "text": text})
        if results and results[0].get("ship"):
            return results[0]["ship"]
        return None
