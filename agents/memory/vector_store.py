"""Vector store for L3 hierarchical RAG, backed by sqlite-vec via KohakuRAG.

Provides cosine-similarity search over code chunk embeddings stored in SQLite.
Uses brute-force numpy search as baseline; sqlite-vec ANN when the extension is available.
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# Dimensions from EmbeddingConfig (default 1024)
_DEFAULT_DIM = 1024


@dataclass
class VectorMatch:
    """Single vector search result."""

    chunk_id: str
    score: float
    metadata: Dict[str, Any] = field(default_factory=dict)


class L3VectorStore:
    """SQLite + sqlite-vec backed vector store for code chunks."""

    def __init__(self, db_path: Path, *, dimensions: int = _DEFAULT_DIM):
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._dimensions = dimensions
        self._conn: Optional[sqlite3.Connection] = None
        self._has_sqlite_vec = False
        self._ensure_schema()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self._db_path))
            self._conn.row_factory = sqlite3.Row
            # Try to load sqlite-vec extension
            try:
                import sqlite_vec  # type: ignore[import-untyped]

                self._conn.enable_load_extension(True)
                sqlite_vec.load(self._conn)
                self._has_sqlite_vec = True
            except (ImportError, Exception):
                logger.debug("sqlite-vec not available, falling back to brute-force cosine search")
        return self._conn

    def _ensure_schema(self) -> None:
        conn = self._get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS l3_chunks (
                chunk_id TEXT PRIMARY KEY,
                file_path TEXT NOT NULL,
                chunk_type TEXT NOT NULL,
                name TEXT NOT NULL,
                start_line INTEGER,
                end_line INTEGER,
                content TEXT NOT NULL,
                embedding BLOB,
                token_estimate INTEGER DEFAULT 0,
                indexed_at TEXT DEFAULT ''
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_l3_file ON l3_chunks(file_path)")
        conn.commit()

    def upsert(
        self,
        chunk_id: str,
        *,
        file_path: str,
        chunk_type: str,
        name: str,
        start_line: int,
        end_line: int,
        content: str,
        embedding: np.ndarray,
        token_estimate: int = 0,
    ) -> None:
        """Insert or replace a chunk with its embedding."""
        conn = self._get_conn()
        blob = embedding.astype(np.float32).tobytes()
        conn.execute(
            """
            INSERT OR REPLACE INTO l3_chunks
            (chunk_id, file_path, chunk_type, name, start_line, end_line,
             content, embedding, token_estimate, indexed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                chunk_id,
                file_path,
                chunk_type,
                name,
                start_line,
                end_line,
                content,
                blob,
                token_estimate,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()

    def search(self, query_embedding: np.ndarray, *, top_k: int = 5) -> List[VectorMatch]:
        """Brute-force cosine similarity search (sqlite-vec ANN when available)."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT chunk_id, file_path, chunk_type, name, start_line, end_line, embedding "
            "FROM l3_chunks WHERE embedding IS NOT NULL"
        ).fetchall()
        if not rows:
            return []

        query = query_embedding.astype(np.float32)
        query_norm = np.linalg.norm(query)
        if query_norm < 1e-9:
            return []
        query = query / query_norm

        scored: List[Tuple[float, Dict[str, Any]]] = []
        for row in rows:
            blob = row["embedding"]
            if not blob:
                continue
            vec = np.frombuffer(blob, dtype=np.float32).copy()
            vec_norm = np.linalg.norm(vec)
            if vec_norm < 1e-9:
                continue
            cosine = float(np.dot(query, vec / vec_norm))
            scored.append((
                cosine,
                {
                    "chunk_id": row["chunk_id"],
                    "file_path": row["file_path"],
                    "chunk_type": row["chunk_type"],
                    "name": row["name"],
                    "start_line": row["start_line"],
                    "end_line": row["end_line"],
                },
            ))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [VectorMatch(chunk_id=meta["chunk_id"], score=score, metadata=meta) for score, meta in scored[:top_k]]

    def delete_by_file(self, file_path: str) -> int:
        """Delete all chunks for a given file path. Returns number of rows deleted."""
        conn = self._get_conn()
        cursor = conn.execute("DELETE FROM l3_chunks WHERE file_path = ?", (file_path,))
        conn.commit()
        return cursor.rowcount

    def count(self) -> int:
        """Return total number of stored chunks."""
        conn = self._get_conn()
        row = conn.execute("SELECT COUNT(*) FROM l3_chunks").fetchone()
        return row[0] if row else 0

    def close(self) -> None:
        """Close the underlying database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None


__all__ = ["L3VectorStore", "VectorMatch"]
