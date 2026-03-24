"""Hierarchical RAG Index — three-level file understanding.

Architecture ref: doc/14-multi-agent-architecture.md §5.3
  "文件 → L1 摘要 (~200 tokens) → L2 函数/段落索引 (~50 tokens/条) → L3 原始 Chunk"

Provides:
  - L1: File-level summary
  - L2: Section/function index with short descriptions
  - L3: Raw chunk content loaded on demand

Index is stored as JSON files in `memory/hierarchical/`.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import numpy as np

from agents.memory.ast_chunker import CodeChunk, chunk_file

if TYPE_CHECKING:
    from agents.memory.vector_store import L3VectorStore

logger = logging.getLogger(__name__)

_DEFAULT_INDEX_ROOT = Path(__file__).resolve().parent.parent.parent / "memory" / "hierarchical"


@dataclass
class IndexEntry:
    """Index entry for a single file."""

    file_path: str
    file_hash: str
    chunk_count: int
    total_lines: int
    total_tokens: int
    summary: str  # L1 summary
    sections: List[Dict[str, Any]]  # L2 section index


class HierarchicalIndex:
    """Three-level hierarchical index for large file understanding.

    - ``get_summary(path)``    → L1 file overview (~200 tokens)
    - ``get_section_index(path)`` → L2 function/section pointers
    - ``get_chunk(path, chunk_id)`` → L3 raw content on demand

    This allows navigating a 6000-line file using ~750 tokens.

    Usage::

        idx = HierarchicalIndex()
        idx.index_file("agents/pipeline.py")
        print(idx.get_summary("agents/pipeline.py"))
        sections = idx.get_section_index("agents/pipeline.py")
        content = idx.get_chunk("agents/pipeline.py", "pipeline_function_run")
    """

    def __init__(self, index_root: Optional[str] = None) -> None:
        self._root = Path(index_root) if index_root else _DEFAULT_INDEX_ROOT
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._vector_store: Optional[L3VectorStore] = None

    @property
    def root(self) -> Path:
        return self._root

    def index_file(self, file_path: str, *, source: Optional[str] = None) -> IndexEntry:
        """Build hierarchical index for a file.

        Chunks the file → builds L2 section index → generates L1 summary.
        Stores index data as JSON.

        Returns IndexEntry.
        """
        path = Path(file_path)
        if source is None:
            source = path.read_text(encoding="utf-8")

        file_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]
        chunks = chunk_file(file_path, source)

        # Build L2 section index
        sections: List[Dict[str, Any]] = []
        for chunk in chunks:
            sections.append({
                "chunk_id": chunk.chunk_id,
                "name": chunk.name,
                "type": chunk.chunk_type,
                "start_line": chunk.start_line,
                "end_line": chunk.end_line,
                "tokens": chunk.token_estimate,
            })

        # Build L1 summary (simple heuristic — top-level overview)
        total_lines = len(source.splitlines())
        total_tokens = sum(s["tokens"] for s in sections)
        summary = self._build_summary(path, chunks, total_lines)

        entry = IndexEntry(
            file_path=file_path,
            file_hash=file_hash,
            chunk_count=len(chunks),
            total_lines=total_lines,
            total_tokens=total_tokens,
            summary=summary,
            sections=sections,
        )

        # Persist index + chunks
        self._save_index(file_path, entry, chunks)

        # Index into vector store for semantic search
        store = self._get_vector_store()
        if store and chunks:
            self._index_chunks_to_vector_store(store, chunks, file_path)

        return entry

    def get_summary(self, file_path: str) -> str:
        """Get L1 file-level summary (~200 tokens).

        Returns empty string if file is not indexed.
        """
        data = self._load_index(file_path)
        if not data:
            return ""
        return data.get("summary", "")

    def get_section_index(self, file_path: str) -> List[Dict[str, Any]]:
        """Get L2 section/function index.

        Each section has: chunk_id, name, type, start_line, end_line, tokens.
        """
        data = self._load_index(file_path)
        if not data:
            return []
        return data.get("sections", [])

    def get_chunk(self, file_path: str, chunk_id: str) -> str:
        """Get L3 raw chunk content by ID.

        Returns empty string if chunk not found.
        """
        chunks_data = self._load_chunks(file_path)
        for chunk in chunks_data:
            if chunk.get("chunk_id") == chunk_id:
                return chunk.get("content", "")
        return ""

    def search(self, query: str, *, top_k: int = 5) -> List[Dict[str, Any]]:
        """Hybrid search: combines vector similarity with keyword matching.

        Vector results are preferred; keyword results fill remaining slots.
        Deduplicates by chunk_id.
        """
        # Keyword search (always available)
        keyword_results = self._keyword_search(query, top_k=top_k)

        # Vector search (when store + embedding API are available)
        vector_results: List[Dict[str, Any]] = []
        store = self._get_vector_store()
        if store:
            try:
                from summer_memory.embedding_openai_compat import embed_texts_openai_compat

                embeddings, meta = embed_texts_openai_compat([query])
                if meta.get("ok") and embeddings and embeddings[0] is not None:
                    query_vec = np.array(embeddings[0], dtype=np.float32)
                    matches = store.search(query_vec, top_k=top_k)
                    for m in matches:
                        vector_results.append({
                            "file_path": m.metadata.get("file_path", ""),
                            "match_type": "vector",
                            "chunk_id": m.chunk_id,
                            "name": m.metadata.get("name", ""),
                            "start_line": m.metadata.get("start_line", 0),
                            "end_line": m.metadata.get("end_line", 0),
                            "score": m.score,
                        })
            except Exception as exc:
                logger.debug("Vector search failed: %s", exc)

        # Merge: dedupe by chunk_id, prefer vector results first
        seen: set[str] = set()
        merged: List[Dict[str, Any]] = []
        for r in vector_results + keyword_results:
            key = r.get("chunk_id") or f"{r.get('file_path')}:{r.get('start_line')}"
            if key not in seen:
                seen.add(key)
                merged.append(r)
        return merged[:top_k]

    def _keyword_search(self, query: str, *, top_k: int = 5) -> List[Dict[str, Any]]:
        """Keyword search across section names and summaries."""
        query_lower = query.lower()
        results: List[Dict[str, Any]] = []

        if not self._root.exists():
            return []

        for index_file in self._root.glob("*_index.json"):
            try:
                data = json.loads(index_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue

            # Check summary
            if query_lower in data.get("summary", "").lower():
                results.append({
                    "file_path": data.get("file_path", ""),
                    "match_type": "summary",
                    "summary": data.get("summary", ""),
                })

            # Check sections
            for section in data.get("sections", []):
                if query_lower in section.get("name", "").lower():
                    results.append({
                        "file_path": data.get("file_path", ""),
                        "match_type": "section",
                        "chunk_id": section.get("chunk_id", ""),
                        "name": section.get("name", ""),
                        "start_line": section.get("start_line", 0),
                        "end_line": section.get("end_line", 0),
                    })

        return results[:top_k]

    def _get_vector_store(self) -> Optional[L3VectorStore]:
        """Lazily initialise and return the L3 vector store."""
        if self._vector_store is not None:
            return self._vector_store
        if getattr(self, "_vector_store_unavailable", False):
            return None  # skip repeated init attempts after first failure
        try:
            from agents.memory.vector_store import L3VectorStore as _L3VS

            db_path = self._root / "vectors" / "l3_code_index.db"
            try:
                from system.config import get_config

                cfg = get_config()
                dim = int(getattr(getattr(cfg, "embedding", None), "dimensions", 1024) or 1024)
            except Exception:
                dim = 1024
            self._vector_store = _L3VS(db_path=db_path, dimensions=dim)
        except Exception as exc:
            self._vector_store_unavailable = True
            logger.debug("Could not initialise L3 vector store: %s", exc)
        return self._vector_store

    def _index_chunks_to_vector_store(
        self,
        store: L3VectorStore,
        chunks: List[CodeChunk],
        file_path: str,
    ) -> None:
        """Embed and upsert code chunks into the vector store (runs in background thread)."""
        import threading

        def _do_index() -> None:
            try:
                from summer_memory.embedding_openai_compat import embed_texts_openai_compat

                texts = [c.content[:8000] for c in chunks]
                if not texts:
                    return
                embeddings, meta = embed_texts_openai_compat(texts)
                if not meta.get("ok") or embeddings is None or len(embeddings) != len(chunks):
                    logger.warning("Embedding API returned incomplete results for %s", file_path)
                    return
                store.delete_by_file(file_path)
                for chunk, emb in zip(chunks, embeddings):
                    if emb is None:
                        continue
                    store.upsert(
                        chunk_id=chunk.chunk_id,
                        file_path=file_path,
                        chunk_type=chunk.chunk_type,
                        name=chunk.name,
                        start_line=chunk.start_line,
                        end_line=chunk.end_line,
                        content=chunk.content,
                        embedding=np.array(emb, dtype=np.float32),
                        token_estimate=chunk.token_estimate,
                    )
            except Exception as exc:
                logger.warning("Vector indexing failed for %s: %s", file_path, exc)

        thread = threading.Thread(target=_do_index, daemon=True, name=f"l3-index-{file_path[-30:]}")
        thread.start()

    def is_indexed(self, file_path: str) -> bool:
        """Check if a file is already indexed."""
        index_path = self._index_path(file_path)
        return index_path.exists()

    def list_indexed(self) -> List[str]:
        """List all indexed file paths."""
        if not self._root.exists():
            return []
        paths = []
        for index_file in self._root.glob("*_index.json"):
            try:
                data = json.loads(index_file.read_text(encoding="utf-8"))
                paths.append(data.get("file_path", ""))
            except (json.JSONDecodeError, OSError):
                continue
        return paths

    # ── Internal ───────────────────────────────────────────────

    def _build_summary(
        self, path: Path, chunks: List[CodeChunk], total_lines: int
    ) -> str:
        """Build a concise L1 summary from chunks."""
        parts = [f"File: {path.name} ({total_lines} lines, {len(chunks)} sections)"]

        # List top-level elements
        named_chunks = [c for c in chunks if c.chunk_type in ("function", "class", "heading")]
        if named_chunks:
            names = [f"{c.chunk_type}:{c.name}" for c in named_chunks[:10]]
            parts.append("Contains: " + ", ".join(names))
            if len(named_chunks) > 10:
                parts.append(f"  ... and {len(named_chunks) - 10} more")

        return "\n".join(parts)

    def _index_path(self, file_path: str) -> Path:
        key = self._file_key(file_path)
        return self._root / f"{key}_index.json"

    def _chunks_path(self, file_path: str) -> Path:
        key = self._file_key(file_path)
        return self._root / f"{key}_chunks.json"

    @staticmethod
    def _file_key(file_path: str) -> str:
        """Generate a safe key from file path."""
        safe = file_path.replace("\\", "/").replace("/", "_").replace(".", "_")
        if len(safe) > 100:
            h = hashlib.md5(file_path.encode()).hexdigest()[:8]
            safe = safe[:92] + "_" + h
        return safe

    def _save_index(
        self, file_path: str, entry: IndexEntry, chunks: List[CodeChunk]
    ) -> None:
        self._root.mkdir(parents=True, exist_ok=True)

        index_data = {
            "file_path": entry.file_path,
            "file_hash": entry.file_hash,
            "chunk_count": entry.chunk_count,
            "total_lines": entry.total_lines,
            "total_tokens": entry.total_tokens,
            "summary": entry.summary,
            "sections": entry.sections,
        }
        self._index_path(file_path).write_text(
            json.dumps(index_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        chunks_data = [asdict(c) for c in chunks]
        self._chunks_path(file_path).write_text(
            json.dumps(chunks_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load_index(self, file_path: str) -> Dict[str, Any]:
        cache_key = f"idx:{file_path}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        index_path = self._index_path(file_path)
        if not index_path.exists():
            return {}

        try:
            data = json.loads(index_path.read_text(encoding="utf-8"))
            self._cache[cache_key] = data
            return data
        except (json.JSONDecodeError, OSError):
            return {}

    def _load_chunks(self, file_path: str) -> List[Dict[str, Any]]:
        chunks_path = self._chunks_path(file_path)
        if not chunks_path.exists():
            return []

        try:
            return json.loads(chunks_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []


__all__ = ["HierarchicalIndex", "IndexEntry"]
