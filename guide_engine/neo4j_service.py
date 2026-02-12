import asyncio
import json
from pathlib import Path
from typing import List, Dict, Any, Optional

from neo4j import AsyncGraphDatabase

from .models import get_guide_engine_settings


class Neo4jService:
    """Neo4j 图数据库服务"""

    AUTO_IMPORT_GAMES = {"arknights", "kantai-collection"}
    ENEMY_NAME_TOKENS = ("级", "鬼", "姬", "栖", "棲", "要塞", "砲台", "飞行场", "飛行場", "集积地", "集積地", "泊地")

    def __init__(self):
        self._driver = None
        self._seed_lock: asyncio.Lock = asyncio.Lock()
        self._seed_attempted_games: set[str] = set()

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

    async def ensure_seed_data(self, game_id: str) -> None:
        """检测并自动导入基础图数据（每个 game_id 仅尝试一次）"""
        if game_id not in self.AUTO_IMPORT_GAMES:
            return
        if game_id in self._seed_attempted_games:
            return

        async with self._seed_lock:
            if game_id in self._seed_attempted_games:
                return
            self._seed_attempted_games.add(game_id)

            try:
                already_has_data = await self._has_seed_data(game_id)
                if already_has_data:
                    return
                imported_count = await self._auto_import_seed_data(game_id)
                print(f"[Neo4j] auto import completed: game_id={game_id}, imported={imported_count}")
            except Exception as exc:
                print(f"[Neo4j] auto import failed: game_id={game_id}, error={exc}")

    async def _has_seed_data(self, game_id: str) -> bool:
        if game_id == "arknights":
            result = await self.execute_query(
                "MATCH (o:Operator {game_id: $game_id}) RETURN count(o) as c",
                {"game_id": game_id},
            )
            return bool(result and int(result[0].get("c", 0)) > 0)

        if game_id == "kantai-collection":
            result = await self.execute_query(
                "MATCH (n {game_id: $game_id}) WHERE n:Ship OR n:EnemyShip RETURN count(n) as c",
                {"game_id": game_id},
            )
            return bool(result and int(result[0].get("c", 0)) > 0)

        return True

    async def _auto_import_seed_data(self, game_id: str) -> int:
        if game_id == "arknights":
            return await self._import_arknights_seed_data(game_id)
        if game_id == "kantai-collection":
            return await self._import_kantai_seed_data(game_id)
        return 0

    async def _import_arknights_seed_data(self, game_id: str) -> int:
        file_path = self._find_seed_file(["arknights_cn_operators.json", "arknights/cn/operators.json"])
        if file_path is None:
            print("[Neo4j] arknights seed file not found, skip auto import")
            return 0

        with open(file_path, "r", encoding="utf-8") as f:
            payload = json.load(f)

        operators_raw = payload.get("operators", []) if isinstance(payload, dict) else []
        operators: List[Dict[str, Any]] = [
            item
            for item in operators_raw
            if isinstance(item, dict) and item.get("id") is not None and item.get("name") is not None
        ]

        if not operators:
            print("[Neo4j] arknights seed file is empty, skip auto import")
            return 0

        await self.init_constraints()
        return await self.import_operators(game_id, operators)

    async def _import_kantai_seed_data(self, game_id: str) -> int:
        file_path = self._find_seed_file(["kantai-collection_start2.json", "kantai_collection_start2.json"])
        if file_path is None:
            print("[Neo4j] kantai seed file not found, skip auto import")
            return 0

        with open(file_path, "r", encoding="utf-8") as f:
            payload = json.load(f)

        ship_types_raw = payload.get("api_mst_stype", []) if isinstance(payload, dict) else []
        ship_types: Dict[int, str] = {}
        for item in ship_types_raw:
            if not isinstance(item, dict):
                continue
            stype_id = self._to_int(item.get("api_id"))
            stype_name = str(item.get("api_name") or "")
            if stype_id is not None and stype_name:
                ship_types[stype_id] = stype_name

        ships_raw = payload.get("api_mst_ship", []) if isinstance(payload, dict) else []
        ships_rows: List[Dict[str, Any]] = []
        enemy_rows: List[Dict[str, Any]] = []

        for item in ships_raw:
            if not isinstance(item, dict):
                continue
            ship_id = self._to_int(item.get("api_id"))
            name = str(item.get("api_name") or "").strip()
            if ship_id is None or not name:
                continue

            stype = self._to_int(item.get("api_stype"))
            ctype = self._to_int(item.get("api_ctype"))
            row: Dict[str, Any] = {
                "id": str(ship_id),
                "name": name,
                "stype": stype,
                "stype_name": ship_types.get(stype or -1, ""),
                "ctype": ctype,
                "taik": item.get("api_taik"),
                "souk": item.get("api_souk"),
                "houg": item.get("api_houg"),
                "raig": item.get("api_raig"),
                "tyku": item.get("api_tyku"),
                "taisen": item.get("api_tais"),
                "soku": self._to_int(item.get("api_soku")),
                "leng": self._to_int(item.get("api_leng")),
            }

            if self._is_enemy_ship(name, ship_id, ctype):
                enemy_rows.append(row)
            else:
                ships_rows.append(row)

        imported_ship_count = await self._upsert_ship_rows(game_id, "Ship", ships_rows)
        imported_enemy_count = await self._upsert_ship_rows(game_id, "EnemyShip", enemy_rows)
        return imported_ship_count + imported_enemy_count

    async def _upsert_ship_rows(self, game_id: str, label: str, rows: List[Dict[str, Any]]) -> int:
        if label not in {"Ship", "EnemyShip"}:
            raise ValueError("invalid label")
        if not rows:
            return 0

        query = f"""
        UNWIND $rows AS row
        MERGE (n:{label} {{game_id: $game_id, id: row.id}})
        SET n += row
        """

        total = 0
        for batch in self._chunk_rows(rows, 300):
            await self.execute_query(query, {"game_id": game_id, "rows": batch})
            total += len(batch)
        return total

    @staticmethod
    def _chunk_rows(rows: List[Dict[str, Any]], size: int) -> List[List[Dict[str, Any]]]:
        return [rows[index : index + size] for index in range(0, len(rows), size)]

    @staticmethod
    def _to_int(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except Exception:
            return None

    @classmethod
    def _is_enemy_ship(cls, name: str, ship_id: int, ctype: int | None) -> bool:
        if any(token in name for token in cls.ENEMY_NAME_TOKENS):
            return True
        if ctype == 1 and ship_id >= 1000:
            return True
        return False

    @staticmethod
    def _candidate_seed_roots() -> List[Path]:
        repo_root = Path(__file__).resolve().parent.parent
        return [
            repo_root / "data",
            repo_root.parent / "guide_engine_backend" / "backend" / "app" / "data",
        ]

    def _find_seed_file(self, relative_paths: List[str]) -> Path | None:
        for root in self._candidate_seed_roots():
            for relative in relative_paths:
                file_path = root / relative
                if file_path.exists():
                    return file_path
        return None

    # ============ 干员相关查询 ============

    async def get_operator(self, game_id: str, operator_name: str) -> Optional[Dict[str, Any]]:
        """获取干员完整信息"""
        await self.ensure_seed_data(game_id)
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
        await self.ensure_seed_data(game_id)
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
        await self.ensure_seed_data(game_id)
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
        await self.ensure_seed_data(game_id)
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
            "CREATE CONSTRAINT IF NOT EXISTS FOR (s:Ship) REQUIRE (s.game_id, s.id) IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (e:EnemyShip) REQUIRE (e.game_id, e.id) IS UNIQUE",
            "CREATE INDEX IF NOT EXISTS FOR (o:Operator) ON (o.name)",
            "CREATE INDEX IF NOT EXISTS FOR (o:Operator) ON (o.name_en)",
            "CREATE INDEX IF NOT EXISTS FOR (o:Operator) ON (o.game_id)",
            "CREATE INDEX IF NOT EXISTS FOR (s:Ship) ON (s.name)",
            "CREATE INDEX IF NOT EXISTS FOR (e:EnemyShip) ON (e.name)",
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
        await self.ensure_seed_data(game_id)
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
        await self.ensure_seed_data(game_id)
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
        await self.ensure_seed_data(game_id)
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
        await self.ensure_seed_data(game_id)
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
