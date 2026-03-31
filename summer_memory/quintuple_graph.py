from __future__ import annotations

import json as _json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

try:
    from py2neo import Graph, Node, Relationship
    from py2neo.errors import ServiceUnavailable
except ImportError:
    Graph = None  # type: ignore[assignment,misc]
    Node = None  # type: ignore[assignment,misc]
    Relationship = None  # type: ignore[assignment,misc]
    ServiceUnavailable = Exception  # type: ignore[assignment,misc]

from .embedding_openai_compat import embed_texts_openai_compat, resolve_embedding_runtime_config

# 延迟加载的graph实例
_graph: Optional[Graph] = None

GRAG_ENABLED: bool = False

_VECTOR_INDEX_READY = False
_VECTOR_LAST_ERROR = ""

logger = logging.getLogger(__name__)
QUINTUPLES_FILE = "logs/knowledge_graph/quintuples.json"


def _resolve_quintuples_file_path() -> Path:
    return Path(QUINTUPLES_FILE)


def get_graph() -> Optional[Graph]:
    """获取graph实例（延迟加载）"""
    global _graph, GRAG_ENABLED

    if _graph is None:
        if Graph is None:
            GRAG_ENABLED = False
            return None

        try:
            from system.config import get_config

            grag_cfg = get_config().grag
            grag_enabled = bool(grag_cfg.enabled)
            neo4j_uri = str(grag_cfg.neo4j_uri or "").strip()
            neo4j_user = str(grag_cfg.neo4j_user or "").strip()
            neo4j_password = str(grag_cfg.neo4j_password or "").strip()
            neo4j_database = str(grag_cfg.neo4j_database or "neo4j").strip() or "neo4j"

            if grag_enabled and neo4j_uri and neo4j_user and neo4j_password:
                try:
                    _graph = Graph(neo4j_uri, auth=(neo4j_user, neo4j_password), name=neo4j_database)
                    _graph.service.kernel_version
                    logger.info("[GRAG] 成功连接到 Neo4j")
                    GRAG_ENABLED = True
                except ServiceUnavailable:
                    logger.warning("[GRAG] 未能连接到 Neo4j，图数据库功能已临时禁用")
                    _graph = None
                    GRAG_ENABLED = False
                except Exception as exc:
                    logger.warning("[GRAG] Neo4j 连接失败: %s", exc)
                    _graph = None
                    GRAG_ENABLED = False
            else:
                logger.info("[GRAG] GRAG 未启用或 Neo4j 配置不完整")
                GRAG_ENABLED = False
        except Exception as exc:
            logger.warning("[GRAG] 加载配置失败: %s", exc)
            GRAG_ENABLED = False

    return _graph


def _safe_index_name(raw_name: str) -> str:
    normalized = re.sub(r"[^0-9A-Za-z_]", "_", str(raw_name or "").strip())
    return normalized or "entity_embedding_index"


def _resolve_vector_runtime() -> Dict[str, Any]:
    from system.config import get_config

    cfg = get_config()
    grag_cfg = cfg.grag
    similarity = str(getattr(grag_cfg, "vector_similarity_function", "cosine") or "cosine").strip().lower()
    if similarity not in {"cosine", "euclidean"}:
        similarity = "cosine"

    return {
        "enabled": bool(getattr(grag_cfg, "vector_index_enabled", True)),
        "index_name": _safe_index_name(getattr(grag_cfg, "vector_index_name", "entity_embedding_index")),
        "top_k": max(1, int(getattr(grag_cfg, "vector_query_top_k", 8) or 8)),
        "similarity": similarity,
        "upsert_on_write": bool(getattr(grag_cfg, "vector_upsert_on_write", True)),
    }


def _ensure_vector_index(graph: Graph, *, index_name: str, dimensions: int, similarity: str) -> bool:
    global _VECTOR_INDEX_READY, _VECTOR_LAST_ERROR
    if _VECTOR_INDEX_READY:
        return True

    dims = max(1, int(dimensions))
    sim = similarity if similarity in {"cosine", "euclidean"} else "cosine"
    cypher = (
        f"CREATE VECTOR INDEX {index_name} IF NOT EXISTS "
        "FOR (e:Entity) ON (e.embedding) "
        "OPTIONS {indexConfig: {`vector.dimensions`: $dims, `vector.similarity_function`: $sim}}"
    )
    try:
        graph.run(cypher, dims=dims, sim=sim)
        _VECTOR_INDEX_READY = True
        _VECTOR_LAST_ERROR = ""
        return True
    except Exception as exc:
        _VECTOR_LAST_ERROR = str(exc)
        logger.warning("[GRAG] 创建/校验向量索引失败: %s", exc)
        return False


def _build_entity_embedding_text(*, name: str, entity_type: str) -> str:
    normalized_name = str(name or "").strip()
    normalized_type = str(entity_type or "").strip()
    if normalized_type:
        return f"实体: {normalized_name}\n类型: {normalized_type}"
    return f"实体: {normalized_name}"


def _upsert_entity_embeddings(graph: Graph, entities: Sequence[Tuple[str, str]]) -> Dict[str, Any]:
    runtime = _resolve_vector_runtime()
    if not runtime.get("enabled", False):
        return {"ok": False, "reason": "vector_disabled"}

    if not entities:
        return {"ok": True, "updated": 0}

    unique_entities: List[Tuple[str, str]] = []
    seen: Set[Tuple[str, str]] = set()
    for name, entity_type in entities:
        key = (str(name or "").strip(), str(entity_type or "").strip())
        if not key[0] or key in seen:
            continue
        seen.add(key)
        unique_entities.append(key)

    if not unique_entities:
        return {"ok": True, "updated": 0}

    texts = [_build_entity_embedding_text(name=name, entity_type=entity_type) for name, entity_type in unique_entities]
    vectors, embed_meta = embed_texts_openai_compat(texts)
    if not embed_meta.get("ok"):
        return {
            "ok": False,
            "reason": "embedding_failed",
            "error": str(embed_meta.get("error") or ""),
        }

    first_vector = next((vector for vector in vectors if isinstance(vector, list) and vector), None)
    if not first_vector:
        return {"ok": False, "reason": "empty_embedding"}

    if not _ensure_vector_index(
        graph,
        index_name=str(runtime["index_name"]),
        dimensions=len(first_vector),
        similarity=str(runtime["similarity"]),
    ):
        return {"ok": False, "reason": "vector_index_unavailable", "error": _VECTOR_LAST_ERROR}

    updated = 0
    model_name = str(embed_meta.get("model") or resolve_embedding_runtime_config().model)
    for (name, entity_type), vector in zip(unique_entities, vectors):
        if not isinstance(vector, list) or not vector:
            continue
        try:
            graph.run(
                """
                MATCH (e:Entity {name: $name})
                SET e.embedding = $embedding,
                    e.embedding_model = $embedding_model,
                    e.embedding_updated_at = datetime(),
                    e.entity_type = coalesce(e.entity_type, $entity_type)
                """,
                name=name,
                entity_type=entity_type,
                embedding=[float(v) for v in vector],
                embedding_model=model_name,
            )
            updated += 1
        except Exception as exc:
            logger.warning("[GRAG] 更新实体向量失败 name=%s err=%s", name, exc)

    return {
        "ok": True,
        "updated": updated,
        "model": model_name,
        "usage": embed_meta.get("usage", {}),
    }


def load_quintuples() -> Set[Tuple[str, str, str, str, str]]:
    file_path = _resolve_quintuples_file_path()
    try:
        with file_path.open("r", encoding="utf-8") as file:
            return set(tuple(t) for t in _json.load(file))
    except FileNotFoundError:
        return set()


def save_quintuples(quintuples: Sequence[Tuple[str, str, str, str, str]]) -> None:
    file_path = _resolve_quintuples_file_path()
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("w", encoding="utf-8") as file:
        _json.dump(list(quintuples), file, ensure_ascii=False, indent=2)


def clear_quintuples_store() -> Dict[str, Any]:
    global _VECTOR_INDEX_READY, _VECTOR_LAST_ERROR

    status: Dict[str, Any] = {
        "ok": True,
        "file_cleared": False,
        "file_removed": False,
        "neo4j_cleared": False,
        "neo4j_state": "unavailable",
        "deleted_nodes": 0,
        "deleted_relationships": 0,
    }

    try:
        file_path = _resolve_quintuples_file_path()
        if file_path.exists():
            file_path.unlink()
            status["file_removed"] = True
        status["file_cleared"] = not file_path.exists()
    except FileNotFoundError:
        status["file_cleared"] = True
    except Exception as exc:
        status["ok"] = False
        status["file_error"] = str(exc)

    graph = get_graph()
    if graph is None:
        status["neo4j_state"] = "unavailable"
    else:
        try:
            count_rows = graph.run(
                """
                MATCH (n:Entity)
                OPTIONAL MATCH (n)-[r]-()
                RETURN count(DISTINCT n) AS deleted_nodes,
                       count(DISTINCT r) AS deleted_relationships
                """
            ).data()
            count_row = count_rows[0] if count_rows else {}
            graph.run("MATCH (n:Entity) DETACH DELETE n")
            status["neo4j_cleared"] = True
            status["neo4j_state"] = "cleared"
            status["deleted_nodes"] = int(count_row.get("deleted_nodes", 0) or 0)
            status["deleted_relationships"] = int(count_row.get("deleted_relationships", 0) or 0)
        except Exception as exc:
            status["ok"] = False
            status["neo4j_state"] = "clear_failed"
            status["neo4j_error"] = str(exc)

    _VECTOR_INDEX_READY = False
    _VECTOR_LAST_ERROR = ""
    return status


def store_quintuples(new_quintuples: Sequence[Tuple[str, str, str, str, str]]) -> bool:
    """存储五元组到文件和Neo4j，返回是否成功。"""
    try:
        all_quintuples = load_quintuples()
        all_quintuples.update(new_quintuples)
        save_quintuples(all_quintuples)

        graph = get_graph()
        if graph is None:
            logger.info("跳过Neo4j存储（未启用），保存 %s 个五元组到文件", len(new_quintuples))
            return True

        success_count = 0
        entities: Set[Tuple[str, str]] = set()
        for head, head_type, rel, tail, tail_type in new_quintuples:
            if not head or not tail:
                logger.warning("跳过无效五元组，head或tail为空: %s", (head, head_type, rel, tail, tail_type))
                continue

            try:
                h_node = Node("Entity", name=head, entity_type=head_type)
                t_node = Node("Entity", name=tail, entity_type=tail_type)
                relation = Relationship(h_node, rel, t_node, head_type=head_type, tail_type=tail_type)

                graph.merge(h_node, "Entity", "name")
                graph.merge(t_node, "Entity", "name")
                graph.merge(relation)

                entities.add((str(head), str(head_type or "")))
                entities.add((str(tail), str(tail_type or "")))
                success_count += 1
            except Exception as exc:
                logger.error("存储五元组失败: %s-%s-%s, 错误: %s", head, rel, tail, exc)

        logger.info("成功存储 %s/%s 个五元组到Neo4j", success_count, len(new_quintuples))

        vector_runtime = _resolve_vector_runtime()
        if success_count > 0 and bool(vector_runtime.get("upsert_on_write", True)):
            vector_result = _upsert_entity_embeddings(graph, list(entities))
            if vector_result.get("ok"):
                logger.info(
                    "[GRAG] 向量写入完成 updated=%s model=%s",
                    int(vector_result.get("updated", 0) or 0),
                    str(vector_result.get("model", "") or ""),
                )
            else:
                logger.warning("[GRAG] 向量写入跳过/失败: %s", vector_result)

        return success_count > 0
    except Exception as exc:
        logger.error("存储五元组失败: %s", exc)
        return False


def get_all_quintuples() -> Set[Tuple[str, str, str, str, str]]:
    return load_quintuples()


def _run_keyword_query(graph: Graph, keyword: str, *, limit: int = 5) -> List[Tuple[str, str, str, str, str]]:
    if not keyword:
        return []
    cypher = """
    MATCH (e1:Entity)-[r]->(e2:Entity)
    WHERE e1.name CONTAINS $kw
       OR e2.name CONTAINS $kw
       OR type(r) CONTAINS $kw
       OR coalesce(e1.entity_type, "") CONTAINS $kw
       OR coalesce(e2.entity_type, "") CONTAINS $kw
    RETURN e1.name AS head,
           coalesce(e1.entity_type, "") AS head_type,
           type(r) AS rel,
           e2.name AS tail,
           coalesce(e2.entity_type, "") AS tail_type
    LIMIT $limit
    """
    rows = graph.run(cypher, kw=keyword, limit=max(1, int(limit))).data()
    return [
        (
            str(row.get("head", "")),
            str(row.get("head_type", "")),
            str(row.get("rel", "")),
            str(row.get("tail", "")),
            str(row.get("tail_type", "")),
        )
        for row in rows
    ]


def _run_vector_entity_query(graph: Graph, *, index_name: str, top_k: int, embedding: Sequence[float]) -> List[Dict[str, Any]]:
    query = """
    CALL db.index.vector.queryNodes($index_name, $k, $embedding)
    YIELD node, score
    RETURN node.name AS name,
           coalesce(node.entity_type, "") AS entity_type,
           score
    ORDER BY score DESC
    LIMIT $k
    """
    return graph.run(
        query,
        index_name=index_name,
        k=max(1, int(top_k)),
        embedding=[float(v) for v in embedding],
    ).data()


def _expand_entity_neighbors(graph: Graph, *, entity_name: str, limit: int = 5) -> List[Tuple[str, str, str, str, str]]:
    cypher = """
    MATCH (e1:Entity)-[r]->(e2:Entity)
    WHERE e1.name = $name OR e2.name = $name
    RETURN e1.name AS head,
           coalesce(e1.entity_type, "") AS head_type,
           type(r) AS rel,
           e2.name AS tail,
           coalesce(e2.entity_type, "") AS tail_type
    LIMIT $limit
    """
    rows = graph.run(cypher, name=entity_name, limit=max(1, int(limit))).data()
    return [
        (
            str(row.get("head", "")),
            str(row.get("head_type", "")),
            str(row.get("rel", "")),
            str(row.get("tail", "")),
            str(row.get("tail_type", "")),
        )
        for row in rows
    ]


def get_vector_index_status() -> Dict[str, Any]:
    runtime = _resolve_vector_runtime()
    status: Dict[str, Any] = {
        "enabled": bool(runtime.get("enabled", False)),
        "index_name": str(runtime.get("index_name", "")),
        "top_k": int(runtime.get("top_k", 0) or 0),
        "similarity": str(runtime.get("similarity", "cosine")),
        "ready": bool(_VECTOR_INDEX_READY),
        "last_error": str(_VECTOR_LAST_ERROR or ""),
    }

    if not status["enabled"]:
        status["state"] = "disabled"
        return status

    graph = get_graph()
    if graph is None:
        status["state"] = "neo4j_unavailable"
        return status

    try:
        rows = graph.run(
            """
            SHOW INDEXES YIELD name, type, state
            WHERE name = $name
            RETURN name, type, state
            """,
            name=status["index_name"],
        ).data()
        if not rows:
            status["state"] = "missing"
            return status

        row = rows[0]
        idx_type = str(row.get("type", "")).upper()
        idx_state = str(row.get("state", "")).upper()
        status["index_type"] = idx_type
        status["index_state"] = idx_state
        status["ready"] = "VECTOR" in idx_type and idx_state == "ONLINE"
        status["state"] = "online" if status["ready"] else "not_ready"
        return status
    except Exception as exc:
        status["state"] = "probe_failed"
        status["last_error"] = str(exc)
        return status


def query_graph_by_keywords(keywords: Sequence[str]) -> List[Tuple[str, str, str, str, str]]:
    graph = get_graph()
    if graph is None:
        return []

    runtime = _resolve_vector_runtime()
    dedup: Set[Tuple[str, str, str, str, str]] = set()
    ordered_results: List[Tuple[str, str, str, str, str]] = []

    def _append_rows(rows: Sequence[Tuple[str, str, str, str, str]]) -> None:
        for row in rows:
            if row in dedup:
                continue
            dedup.add(row)
            ordered_results.append(row)

    for kw in keywords:
        normalized_kw = str(kw or "").strip()
        if not normalized_kw:
            continue
        _append_rows(_run_keyword_query(graph, normalized_kw, limit=5))

    if bool(runtime.get("enabled", False)):
        query_text = " ".join(str(kw or "").strip() for kw in keywords if str(kw or "").strip())
        if query_text:
            vectors, meta = embed_texts_openai_compat([query_text])
            query_vector = vectors[0] if vectors else None
            if isinstance(query_vector, list) and query_vector:
                if _ensure_vector_index(
                    graph,
                    index_name=str(runtime["index_name"]),
                    dimensions=len(query_vector),
                    similarity=str(runtime["similarity"]),
                ):
                    try:
                        entity_rows = _run_vector_entity_query(
                            graph,
                            index_name=str(runtime["index_name"]),
                            top_k=int(runtime["top_k"]),
                            embedding=query_vector,
                        )
                        for entity_row in entity_rows:
                            entity_name = str(entity_row.get("name", "")).strip()
                            if not entity_name:
                                continue
                            _append_rows(_expand_entity_neighbors(graph, entity_name=entity_name, limit=5))
                    except Exception as exc:
                        logger.warning("[GRAG] 向量检索失败，回退关键词检索: %s", exc)
                else:
                    logger.warning("[GRAG] 向量索引不可用，回退关键词检索")
            elif not meta.get("ok"):
                logger.warning("[GRAG] 向量检索embedding失败，回退关键词检索: %s", meta)

    return ordered_results
