"""
舰队Collection数据导入脚本

从 start2 API 缓存和海域数据导入到 ChromaDB

使用方法（在项目根目录）:
    uv run python -m guide_engine.rag.import_kantai_data
    uv run python -m guide_engine.rag.import_kantai_data --dry-run
    uv run python -m guide_engine.rag.import_kantai_data --maps-only
    uv run python -m guide_engine.rag.import_kantai_data --ships-only
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..chroma_service import ChromaService
from ..models import get_guide_engine_settings

GAME_ID = "kantai-collection"


# ── ship / equipment / enemy 文档构建 ──────────────────────────

def _build_ship_type_map(start2: Dict[str, Any]) -> Dict[int, str]:
    return {
        int(t["api_id"]): t["api_name"]
        for t in start2.get("api_mst_stype", [])
        if t.get("api_id") is not None and t.get("api_name")
    }


def _build_equip_type_map(start2: Dict[str, Any]) -> Dict[int, str]:
    return {
        int(t["api_id"]): t["api_name"]
        for t in start2.get("api_mst_slotitem_equiptype", [])
        if t.get("api_id") is not None and t.get("api_name")
    }


def _normalize_ships(
    start2: Dict[str, Any], stype_map: Dict[int, str]
) -> List[Dict[str, Any]]:
    ships = start2.get("api_mst_ship", [])
    result: List[Dict[str, Any]] = []
    for ship in ships:
        ship_id = ship.get("api_id")
        name = ship.get("api_name")
        if ship_id is None or not name:
            continue
        stype_id = ship.get("api_stype")
        stype_name = stype_map.get(int(stype_id)) if stype_id is not None else ""
        result.append({
            "id": int(ship_id),
            "name": name,
            "yomi": ship.get("api_yomi", ""),
            "stype_name": stype_name,
            "slot_num": ship.get("api_slot_num"),
            "taik": ship.get("api_taik", []),
            "souk": ship.get("api_souk", []),
            "houg": ship.get("api_houg", []),
            "raig": ship.get("api_raig", []),
            "tyku": ship.get("api_tyku", []),
            "luck": ship.get("api_luck", []),
            "is_enemy": int(ship_id) >= 1500,
        })
    return result


def _normalize_slotitems(
    start2: Dict[str, Any], equip_type_map: Dict[int, str]
) -> List[Dict[str, Any]]:
    items = start2.get("api_mst_slotitem", [])
    result: List[Dict[str, Any]] = []
    for item in items:
        item_id = item.get("api_id")
        name = item.get("api_name")
        if item_id is None or not name:
            continue
        type_info = item.get("api_type", [])
        equip_type_id = type_info[2] if len(type_info) > 2 else None
        equip_type_name = (
            equip_type_map.get(int(equip_type_id)) if equip_type_id is not None else ""
        )
        result.append({
            "id": int(item_id),
            "name": name,
            "equip_type_name": equip_type_name,
            "houg": item.get("api_houg", 0),
            "raig": item.get("api_raig", 0),
            "tyku": item.get("api_tyku", 0),
            "taisen": item.get("api_taisen", 0),
            "bomb": item.get("api_baku", 0),
            "saku": item.get("api_saku", 0),
            "leng": item.get("api_leng", 0),
            "raim": item.get("api_raim", 0),
            "houm": item.get("api_houm", 0),
        })
    return result


def _build_ship_docs(ships: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    docs: List[Dict[str, Any]] = []
    for ship in ships:
        stats = json.dumps(
            {k: ship.get(k, []) for k in ("taik", "souk", "houg", "raig", "tyku", "luck")},
            ensure_ascii=False,
        )
        content = f"Ship: {ship['name']}\nType: {ship.get('stype_name', '')}\nStats: {stats}\nSlots: {ship.get('slot_num')}"
        docs.append({
            "id": f"ship_{ship['id']}",
            "title": ship["name"],
            "content": content,
            "doc_type": "ship",
            "source_url": "",
            "metadata": {"stype": ship.get("stype_name", ""), "topic": "ship"},
        })
    return docs


def _build_enemy_docs(enemies: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    docs: List[Dict[str, Any]] = []
    for ship in enemies:
        stats = json.dumps(
            {k: ship.get(k, []) for k in ("taik", "souk", "houg", "raig", "tyku", "luck")},
            ensure_ascii=False,
        )
        content = f"Enemy: {ship['name']}\nType: {ship.get('stype_name', '')}\nStats: {stats}"
        docs.append({
            "id": f"enemy_{ship['id']}",
            "title": ship["name"],
            "content": content,
            "doc_type": "enemy",
            "source_url": "",
            "metadata": {"stype": ship.get("stype_name", ""), "is_enemy": True, "topic": "enemy"},
        })
    return docs


def _build_equip_docs(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    docs: List[Dict[str, Any]] = []
    for item in items:
        stat_keys = ("houg", "raig", "tyku", "taisen", "bomb", "saku", "leng", "raim", "houm")
        stats = json.dumps({k: item.get(k, 0) for k in stat_keys}, ensure_ascii=False)
        content = f"Equipment: {item['name']}\nEquipType: {item.get('equip_type_name', '')}\nStats: {stats}"
        docs.append({
            "id": f"equip_{item['id']}",
            "title": item["name"],
            "content": content,
            "doc_type": "equipment",
            "source_url": "",
            "metadata": {"equip_type": item.get("equip_type_name", ""), "topic": "equipment"},
        })
    return docs


# ── 海域攻略文档构建 ──────────────────────────

def _build_map_doc(map_id: str, map_data: Dict[str, Any]) -> Dict[str, Any]:
    lines: List[str] = []
    name = map_data.get("cn_name") or map_data.get("jp_name") or map_id
    lines.append(f"# {map_id} {name}")

    if map_data.get("operation_cn") or map_data.get("operation_jp"):
        lines.append(f"作战名: {map_data.get('operation_cn') or map_data.get('operation_jp')}")
    if map_data.get("difficulty"):
        lines.append(f"难度: {map_data['difficulty']}")
    if map_data.get("exp_range"):
        lines.append(f"经验值: {map_data['exp_range']}")
    if map_data.get("clear_reward"):
        lines.append(f"通关奖励: {map_data['clear_reward']}")

    air_info = map_data.get("air_power_info", {})
    if air_info:
        air_parts: List[str] = []
        if air_info.get("enemy"):
            air_parts.append(f"敌制空: {air_info['enemy']}")
        if air_info.get("superiority"):
            air_parts.append(f"优势: {air_info['superiority']}")
        if air_info.get("supremacy"):
            air_parts.append(f"确保: {air_info['supremacy']}")
        if air_parts:
            lines.append("制空值: " + ", ".join(air_parts))

    lines.append("")

    if map_data.get("guide_text"):
        lines.append("## 攻略")
        lines.append(map_data["guide_text"])
        lines.append("")

    routes = map_data.get("routes", [])
    if routes:
        lines.append("## 带路条件")
        for route in routes:
            lines.append(f"- {route['from']}→{route['to']}: {route['condition']}")
        lines.append("")

    nodes = map_data.get("nodes", {})
    if nodes:
        lines.append("## 节点信息")
        for node_name, node in sorted(nodes.items()):
            node_type = node.get("type", "normal")
            node_display = node_name
            if node_type == "boss":
                node_display += "(BOSS)"
            elif node_type == "night":
                node_display += "(夜战)"
            elif node_type == "airstrike":
                node_display += "(空袭)"
            if node.get("cn_name") or node.get("jp_name"):
                node_display += f" {node.get('cn_name') or node.get('jp_name')}"
            lines.append(f"\n### {node_display}")

            for config in node.get("configs", []):
                formation = config.get("formation", "")
                enemies = config.get("enemies", [])
                enemy_names = [e.get("name", f"ID:{e.get('id')}") for e in enemies]
                config_line = f"配置{config['pattern']}"
                if config.get("is_final"):
                    config_line += "(斩杀)"
                config_line += f": {formation}"
                if config.get("air_power"):
                    config_line += f" (制空:{config['air_power']})"
                lines.append(config_line)
                if enemy_names:
                    lines.append(f"  敌舰: {', '.join(enemy_names)}")

            drops = node.get("drops", [])
            if drops:
                lines.append(f"  掉落: {', '.join(drops[:10])}")

    content = "\n".join(lines)
    return {
        "id": f"kantai_map_{map_id}",
        "title": f"{map_id} {name}",
        "content": content,
        "doc_type": "map_guide",
        "source_url": f"https://zh.kcwiki.cn/wiki/{map_id}",
        "metadata": {"topic": "海域攻略"},
    }


# ── 伤害计算公式提取 ──────────────────────────

FORMULA_FUNCTIONS = [
    "getDayBattlePower", "getTorpedoPower", "getNightBattlePower",
    "getRadarShootingPower", "getAttackTypeAtDay", "getAttackTypeAtNight",
    "isSubMarine", "isGround", "isPtImpPack", "getItems", "getItemNum",
    "AntiSubmarinePower",
]
FORMULA_CONSTANTS = [
    "STYPE", "GERMAN_SHIPS", "ITALIAN_SHIPS", "AMERICAN_SHIPS",
    "BRITISH_SHIPS", "FRENCH_SHIPS", "RUSSIAN_SHIPS", "SWEDISH_SHIPS",
    "DUTCH_SHIPS", "AUSTRALIAN_SHIPS", "OVERSEA_SHIPS", "JAPANESE_DD_SHIPS",
]


def _find_jsdoc_before(text: str, start_idx: int) -> str:
    block_start = text.rfind("/**", 0, start_idx)
    if block_start == -1:
        return ""
    block_end = text.find("*/", block_start)
    if block_end == -1 or block_end >= start_idx:
        return ""
    return text[block_start:block_end + 2].strip()


def _extract_brace_block(text: str, start_idx: int) -> Optional[str]:
    i = text.find("{", start_idx)
    if i == -1:
        return None
    depth = 0
    in_str: Optional[str] = None
    in_line_comment = False
    in_block_comment = False
    escaped = False
    for j in range(i, len(text)):
        ch = text[j]
        nxt = text[j + 1] if j + 1 < len(text) else ""
        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
            continue
        if in_block_comment:
            if ch == "*" and nxt == "/":
                in_block_comment = False
            continue
        if in_str:
            if escaped:
                escaped = False
                continue
            if ch == "\\":
                escaped = True
                continue
            if ch == in_str:
                in_str = None
            continue
        if ch == "/" and nxt == "/":
            in_line_comment = True
            continue
        if ch == "/" and nxt == "*":
            in_block_comment = True
            continue
        if ch in ("'", '"', "`"):
            in_str = ch
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start_idx:j + 1]
    return None


def _extract_bracket_block(text: str, start_idx: int) -> Optional[str]:
    i = text.find("[", start_idx)
    if i == -1:
        return None
    depth = 0
    in_str: Optional[str] = None
    in_line_comment = False
    in_block_comment = False
    escaped = False
    for j in range(i, len(text)):
        ch = text[j]
        nxt = text[j + 1] if j + 1 < len(text) else ""
        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
            continue
        if in_block_comment:
            if ch == "*" and nxt == "/":
                in_block_comment = False
            continue
        if in_str:
            if escaped:
                escaped = False
                continue
            if ch == "\\":
                escaped = True
                continue
            if ch == in_str:
                in_str = None
            continue
        if ch == "/" and nxt == "/":
            in_line_comment = True
            continue
        if ch == "/" and nxt == "*":
            in_block_comment = True
            continue
        if ch in ("'", '"', "`"):
            in_str = ch
            continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return text[start_idx:j + 1]
    return None


def _extract_formulas(text: str) -> List[Dict[str, Any]]:
    rules: List[Dict[str, Any]] = []
    max_content_len = 60000

    for name in FORMULA_FUNCTIONS:
        start = None
        for marker in (f"var {name} = function", f"function {name}(", f"{name} = function"):
            idx = text.find(marker)
            if idx != -1:
                start = idx
                break
        if start is None:
            continue
        jsdoc = _find_jsdoc_before(text, start)
        block = _extract_brace_block(text, start)
        if not block:
            continue
        content = "\n".join([jsdoc, block]).strip()[:max_content_len]
        rules.append({"id": f"formula_{name}", "title": name, "category": "function", "content": content})

    for name in FORMULA_CONSTANTS:
        marker = f"var {name} ="
        idx = text.find(marker)
        if idx == -1:
            continue
        block = _extract_brace_block(text, idx) or _extract_bracket_block(text, idx)
        if not block:
            continue
        content = block[:max_content_len]
        rules.append({"id": f"constant_{name}", "title": name, "category": "constant", "content": content})

    return rules


def _build_formula_docs(rules: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    docs: List[Dict[str, Any]] = []
    for rule in rules:
        docs.append({
            "id": rule["id"],
            "title": rule["title"],
            "content": rule["content"],
            "doc_type": rule["category"],
            "source_url": "",
            "metadata": {"category": rule["category"], "topic": "damage_formula"},
        })
    return docs


# ── 主导入流程 ──────────────────────────

async def import_ships_and_enemies(
    chroma: ChromaService,
    data_dir: Path,
    dry_run: bool = False,
    clear: bool = True,
    include_formulas: bool = True,
) -> Dict[str, int]:
    """导入舰娘/装备/公式(wiki) + 深海栖舰(enemies)"""
    start2_path = data_dir / "kantai-collection_start2.json"
    if not start2_path.exists():
        print(f"start2 缓存不存在: {start2_path}")
        return {"ships": 0, "equipment": 0, "enemies": 0}

    with open(start2_path, "r", encoding="utf-8") as f:
        start2 = json.load(f)

    stype_map = _build_ship_type_map(start2)
    equip_map = _build_equip_type_map(start2)
    all_ships = _normalize_ships(start2, stype_map)
    items = _normalize_slotitems(start2, equip_map)

    friendly = [s for s in all_ships if not s["is_enemy"]]
    enemies = [s for s in all_ships if s["is_enemy"]]

    ship_docs = _build_ship_docs(friendly)
    equip_docs = _build_equip_docs(items)
    enemy_docs = _build_enemy_docs(enemies)

    wiki_docs = ship_docs + equip_docs  # → game_kantai_collection

    # 公式文档
    formula_docs: List[Dict[str, Any]] = []
    if include_formulas:
        formula_path = data_dir / "kantai-collection_formulas.js"
        if formula_path.exists():
            formula_text = formula_path.read_text(encoding="utf-8")
            rules = _extract_formulas(formula_text)
            formula_docs = _build_formula_docs(rules)
            wiki_docs += formula_docs

    print(f"  舰娘: {len(ship_docs)}, 装备: {len(equip_docs)}, 公式: {len(formula_docs)}, 深海: {len(enemy_docs)}")

    if dry_run:
        return {"ships": len(ship_docs), "equipment": len(equip_docs), "formulas": len(formula_docs), "enemies": len(enemy_docs)}

    # 清除旧数据后重建
    if clear:
        try:
            await chroma.delete_collection(GAME_ID, "wiki")
        except Exception:
            pass
        try:
            await chroma.delete_collection(GAME_ID, "enemies")
        except Exception:
            pass

    wiki_count = await chroma.insert_documents(GAME_ID, wiki_docs, "wiki")
    enemy_count = await chroma.insert_documents(GAME_ID, enemy_docs, "enemies")
    print(f"  Wiki collection: {wiki_count} docs, Enemies collection: {enemy_count} docs")

    return {"ships": len(ship_docs), "equipment": len(equip_docs), "formulas": len(formula_docs), "enemies": len(enemy_docs)}


async def import_maps(
    chroma: ChromaService,
    data_dir: Path,
    dry_run: bool = False,
) -> int:
    """导入海域攻略到 wiki collection（追加）"""
    maps_path = data_dir / "kantai_maps.json"
    if not maps_path.exists():
        print(f"海域数据不存在: {maps_path}")
        return 0

    with open(maps_path, "r", encoding="utf-8") as f:
        maps_data = json.load(f)

    docs: List[Dict[str, Any]] = []
    for map_id, map_data in maps_data.items():
        docs.append(_build_map_doc(map_id, map_data))

    print(f"  海域攻略: {len(docs)} 个")

    if dry_run:
        return len(docs)

    # 追加到 wiki collection（不清除，ships/equip 已在里面）
    count = await chroma.insert_documents(GAME_ID, docs, "wiki")
    print(f"  Maps appended to wiki collection: {count} docs")
    return count


async def main() -> None:
    parser = argparse.ArgumentParser(description="Import Kantai Collection data to ChromaDB")
    parser.add_argument("--dry-run", "-d", action="store_true", help="Process without importing")
    parser.add_argument("--ships-only", action="store_true", help="Only import ships/equipment/enemies")
    parser.add_argument("--maps-only", action="store_true", help="Only import maps")
    parser.add_argument("--no-clear", action="store_true", help="Don't clear existing data first")
    args = parser.parse_args()

    settings = get_guide_engine_settings()
    data_dir = Path(settings.gamedata_dir)
    chroma = ChromaService()

    print(f"{'='*50}")
    print(f"Kantai Collection Data Import")
    print(f"Data dir: {data_dir}")
    print(f"{'='*50}")

    import_all = not args.ships_only and not args.maps_only

    if import_all or args.ships_only:
        print("\n[1/2] Importing ships, equipment, enemies...")
        await import_ships_and_enemies(chroma, data_dir, args.dry_run, clear=not args.no_clear)

    if import_all or args.maps_only:
        print("\n[2/2] Importing map guides...")
        await import_maps(chroma, data_dir, args.dry_run)

    # 验证
    if not args.dry_run:
        print(f"\n{'='*50}")
        print("Verification:")
        for col_type in ("wiki", "enemies"):
            col_name = chroma._get_collection_name(GAME_ID, col_type)
            try:
                col = chroma.client.get_collection(col_name)
                print(f"  {col_name}: {col.count()} docs")
            except Exception:
                print(f"  {col_name}: not found")

    if args.dry_run:
        print("\n(Dry run - no data was imported)")


if __name__ == "__main__":
    asyncio.run(main())
