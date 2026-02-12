"""
ChromaDB 向量数据库服务

替代 Milvus，用于 Windows 本地开发
"""

import asyncio
from typing import List, Dict, Any, Optional
from datetime import datetime

try:
    import chromadb
    from chromadb.config import Settings
except Exception:
    chromadb = None  # type: ignore[assignment]
    Settings = None  # type: ignore[assignment]

from .models import get_guide_engine_settings


class ChromaService:
    """ChromaDB 向量数据库服务"""

    # 使用中文嵌入模型
    EMBEDDING_MODEL = "BAAI/bge-base-zh-v1.5"

    # 游戏ID到内部名称的映射（用于匹配导入时的collection名称）
    GAME_ID_MAP = {
        "honkai-star-rail": "starrail",
        "genshin-impact": "genshin",
        "arknights": "arknights",
        "punishing-gray-raven": "pgr",
        "wuthering-waves": "wutheringwaves",
        "zenless-zone-zero": "zenless",
        "uma-musume": "umamusume",
        "kantai-collection": "kantai_collection",
    }

    def __init__(self, persist_dir: Optional[str] = None):
        self._client = None
        self._model = None
        settings = get_guide_engine_settings()
        self._persist_dir = persist_dir or settings.chroma_persist_dir

    @property
    def client(self):
        """懒加载 ChromaDB 客户端"""
        if self._client is None:
            if chromadb is None or Settings is None:
                raise RuntimeError("chromadb 未安装，请先安装 requirements 中的 chromadb")
            self._client = chromadb.PersistentClient(
                path=self._persist_dir, settings=Settings(anonymized_telemetry=False)
            )
        return self._client

    @property
    def embedding_model(self):
        """懒加载嵌入模型"""
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            settings = get_guide_engine_settings()
            model_id = settings.embedding_model_path or self.EMBEDDING_MODEL
            print(f"Loading embedding model: {model_id}")
            # Force local-only to avoid accidental downloads.
            self._model = SentenceTransformer(model_id, local_files_only=True)
            print("Embedding model loaded successfully")
        return self._model

    def _get_collection_name(self, game_id: str, collection_type: str = "guides") -> str:
        """
        获取集合名称

        Args:
            game_id: 游戏ID (如 honkai-star-rail)
            collection_type: 集合类型
                - "guides": 视频攻略 -> game_{内部名}_guides
                - "wiki": Wiki数据 -> game_{内部名}
        """
        internal_name = self.GAME_ID_MAP.get(game_id, game_id.replace("-", "_"))
        if collection_type == "wiki":
            return f"game_{internal_name}"
        if collection_type == "enemies":
            return f"game_{internal_name}_enemies"
        return f"game_{internal_name}_guides"

    async def create_collection(self, game_id: str) -> bool:
        """创建或获取集合"""
        try:
            collection_name = self._get_collection_name(game_id)
            self.client.get_or_create_collection(
                name=collection_name, metadata={"game_id": game_id, "hnsw:space": "cosine"}
            )
            return True
        except Exception as e:
            print(f"Failed to create collection: {e}")
            return False

    async def delete_collection(self, game_id: str) -> bool:
        """删除集合"""
        try:
            collection_name = self._get_collection_name(game_id)
            self.client.delete_collection(collection_name)
            return True
        except Exception as e:
            print(f"Failed to delete collection: {e}")
            return False

    async def insert_documents(self, game_id: str, documents: List[Dict[str, Any]]) -> int:
        """插入文档"""
        if not documents:
            return 0

        collection_name = self._get_collection_name(game_id)
        collection = self.client.get_or_create_collection(
            name=collection_name, metadata={"game_id": game_id, "hnsw:space": "cosine"}
        )

        # 准备数据
        ids = []
        texts = []
        metadatas = []

        for doc in documents:
            doc_id = doc.get("id", str(datetime.now().timestamp()))
            content = doc.get("content", "")
            title = doc.get("title", "")

            # 组合标题和内容用于嵌入
            text = f"{title}\n{content}" if title else content

            ids.append(doc_id)
            texts.append(text)

            # 提取 metadata 中的额外信息
            extra_metadata = doc.get("metadata", {})

            metadatas.append(
                {
                    "title": title,
                    "doc_type": doc.get("doc_type", ""),
                    "source_url": doc.get("source_url", ""),
                    "version": doc.get("version", "1.0.0"),
                    "author": extra_metadata.get("author", ""),
                    "topic": extra_metadata.get("topic", ""),
                    "video_type": extra_metadata.get("video_type", ""),
                }
            )

        # 生成嵌入向量
        print(f"Generating embeddings for {len(texts)} documents...")
        embeddings = await asyncio.to_thread(self.embedding_model.encode, texts, normalize_embeddings=True)

        # 插入数据
        collection.add(ids=ids, embeddings=embeddings.tolist(), metadatas=metadatas, documents=texts)

        print(f"Inserted {len(documents)} documents")
        return len(documents)

    async def search(
        self,
        game_id: str,
        query: str,
        top_k: int = 5,
        score_threshold: float = 0.5,
        search_mode: str = "full",  # "full" | "wiki_only" | "guides_only" | "enemy_only"
        doc_type_filter: Optional[str] = None,  # 过滤特定文档类型
    ) -> List[Dict[str, Any]]:
        """
        语义搜索

        Args:
            game_id: 游戏ID
            query: 查询文本
            top_k: 返回结果数量
            score_threshold: 相似度阈值
            search_mode: 搜索模式
                - "full": 同时搜索 wiki 和 guides
                - "wiki_only": 只搜索 wiki
                - "guides_only": 只搜索 guides
            doc_type_filter: 只返回指定doc_type的文档（如 "map_guide"）
        """
        # 生成查询向量（只需要生成一次）
        query_embedding = await asyncio.to_thread(self.embedding_model.encode, query, normalize_embeddings=True)

        all_results = []

        # 根据搜索模式决定搜索哪些 collection
        if search_mode == "wiki_only":
            collection_types = ["wiki"]
        elif search_mode == "guides_only":
            collection_types = ["guides"]
        elif search_mode == "enemy_only":
            collection_types = ["enemies"]
        else:
            collection_types = ["guides", "wiki", "enemies"]

        for collection_type in collection_types:
            collection_name = self._get_collection_name(game_id, collection_type)

            try:
                collection = self.client.get_collection(collection_name)
            except Exception:
                print(f"Collection {collection_name} not found, skipping...")
                continue

            # 构建查询参数
            query_kwargs = {
                "query_embeddings": [query_embedding.tolist()],
                "n_results": top_k,
                "include": ["documents", "metadatas", "distances"],
            }

            # 如果指定了doc_type过滤，添加where条件
            if doc_type_filter:
                query_kwargs["where"] = {"doc_type": doc_type_filter}

            # 搜索（包含 documents 字段以获取完整内容）
            results = collection.query(**query_kwargs)

            # 格式化结果
            if results and results["ids"] and results["ids"][0]:
                for i, doc_id in enumerate(results["ids"][0]):
                    distance = results["distances"][0][i] if results["distances"] else 0
                    score = 1 - distance

                    if score >= score_threshold:
                        metadata = results["metadatas"][0][i] if results["metadatas"] else {}
                        # 从 documents 获取完整内容，而不是 metadata 中的截断内容
                        full_content = results["documents"][0][i] if results.get("documents") else ""

                        all_results.append(
                            {
                                "id": doc_id,
                                "title": metadata.get("title", ""),
                                "content": full_content,  # 使用完整的 document 内容
                                "doc_type": metadata.get("doc_type", collection_type),
                                "source_url": metadata.get("source_url", ""),
                                "author": metadata.get("author", ""),
                                "topic": metadata.get("topic", ""),
                                "score": round(score, 4),
                                "collection": collection_type,
                                "metadata": metadata,
                            }
                        )

        # 按相似度排序，取 top_k
        all_results.sort(key=lambda x: x["score"], reverse=True)
        top_results = all_results[:top_k]

        # 打印搜索结果（调试用）
        if top_results:
            print(f"[ChromaDB] Found {len(top_results)} results for query: {query}")
            for i, result in enumerate(top_results[:3]):  # 只打印前3个
                print(f"  [{i + 1}] {result['title']} (score: {result['score']}, collection: {result['collection']})")
        else:
            print(f"[ChromaDB] No results found for query: {query}")

        return top_results

    async def get_collection_stats(self, game_id: str) -> Dict[str, Any]:
        """获取集合统计信息"""
        collection_name = self._get_collection_name(game_id)

        try:
            collection = self.client.get_collection(collection_name)
            count = collection.count()
            return {"name": collection_name, "count": count, "game_id": game_id}
        except Exception as e:
            return {"error": str(e)}
