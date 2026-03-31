"""Tests for L3 vector store and hybrid search integration.

WS33-016: Vector search capability for L3 HierarchicalIndex.
Uses synthetic numpy vectors — does NOT call real embedding API.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from unittest.mock import MagicMock, patch

import numpy as np
import pytest


def _import_module_directly(module_name: str, file_path: str):
    """Import a module directly from its file without triggering package __init__.py."""
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


# Import modules directly from files, bypassing the heavy agents.memory.__init__.py
# which has transitive dependencies not available in the test worktree.
_base = Path(__file__).resolve().parent.parent / "agents" / "memory"

# Ensure agents and agents.memory are registered as namespace packages so
# submodule imports (used inside the modules themselves) resolve correctly.
if "agents" not in sys.modules:
    import types as _types

    _agents_pkg = _types.ModuleType("agents")
    _agents_pkg.__path__ = [str(_base.parent)]
    _agents_pkg.__package__ = "agents"
    sys.modules["agents"] = _agents_pkg

    _mem_pkg = _types.ModuleType("agents.memory")
    _mem_pkg.__path__ = [str(_base)]
    _mem_pkg.__package__ = "agents.memory"
    sys.modules["agents.memory"] = _mem_pkg

_ast_mod = _import_module_directly("agents.memory.ast_chunker", str(_base / "ast_chunker.py"))
_vs_mod = _import_module_directly("agents.memory.vector_store", str(_base / "vector_store.py"))
_hrag_mod = _import_module_directly("agents.memory.hierarchical_rag", str(_base / "hierarchical_rag.py"))

L3VectorStore = _vs_mod.L3VectorStore
VectorMatch = _vs_mod.VectorMatch
HierarchicalIndex = _hrag_mod.HierarchicalIndex


# ── L3VectorStore unit tests ──────────────────────────────────────


class TestL3VectorStoreBasic:
    """Core upsert / search / delete operations."""

    def _make_store(self, tmp_path: Path, dim: int = 8) -> L3VectorStore:
        db = tmp_path / "test_vectors.db"
        return L3VectorStore(db_path=db, dimensions=dim)

    def test_upsert_and_count(self, tmp_path: Path) -> None:
        store = self._make_store(tmp_path)
        vec = np.random.randn(8).astype(np.float32)
        store.upsert(
            chunk_id="chunk_1",
            file_path="foo.py",
            chunk_type="function",
            name="my_func",
            start_line=1,
            end_line=10,
            content="def my_func(): pass",
            embedding=vec,
        )
        assert store.count() == 1
        store.close()

    def test_upsert_replace(self, tmp_path: Path) -> None:
        store = self._make_store(tmp_path)
        vec1 = np.random.randn(8).astype(np.float32)
        vec2 = np.random.randn(8).astype(np.float32)
        for vec in (vec1, vec2):
            store.upsert(
                chunk_id="chunk_1",
                file_path="foo.py",
                chunk_type="function",
                name="my_func",
                start_line=1,
                end_line=10,
                content="def my_func(): pass",
                embedding=vec,
            )
        assert store.count() == 1
        store.close()

    def test_search_returns_sorted_by_cosine(self, tmp_path: Path) -> None:
        dim = 8
        store = self._make_store(tmp_path, dim=dim)

        # Create a query vector
        query = np.array([1.0, 0, 0, 0, 0, 0, 0, 0], dtype=np.float32)

        # Chunk A: very similar to query (aligned with dim 0)
        vec_a = np.array([0.9, 0.1, 0, 0, 0, 0, 0, 0], dtype=np.float32)
        # Chunk B: orthogonal to query
        vec_b = np.array([0, 1.0, 0, 0, 0, 0, 0, 0], dtype=np.float32)
        # Chunk C: somewhat similar
        vec_c = np.array([0.5, 0.5, 0, 0, 0, 0, 0, 0], dtype=np.float32)

        for cid, vec in [("a", vec_a), ("b", vec_b), ("c", vec_c)]:
            store.upsert(
                chunk_id=cid,
                file_path="test.py",
                chunk_type="function",
                name=f"func_{cid}",
                start_line=1,
                end_line=5,
                content=f"def func_{cid}(): pass",
                embedding=vec,
            )

        results = store.search(query, top_k=3)
        assert len(results) == 3
        assert results[0].chunk_id == "a"
        assert results[1].chunk_id == "c"
        assert results[2].chunk_id == "b"
        # Scores should be descending
        assert results[0].score > results[1].score > results[2].score
        store.close()

    def test_search_top_k_limits_results(self, tmp_path: Path) -> None:
        store = self._make_store(tmp_path)
        for i in range(10):
            store.upsert(
                chunk_id=f"chunk_{i}",
                file_path="test.py",
                chunk_type="block",
                name=f"block_{i}",
                start_line=i * 10,
                end_line=i * 10 + 9,
                content=f"block {i}",
                embedding=np.random.randn(8).astype(np.float32),
            )
        query = np.random.randn(8).astype(np.float32)
        results = store.search(query, top_k=3)
        assert len(results) == 3
        store.close()

    def test_search_empty_store(self, tmp_path: Path) -> None:
        store = self._make_store(tmp_path)
        results = store.search(np.random.randn(8).astype(np.float32), top_k=5)
        assert results == []
        store.close()

    def test_search_zero_vector_query(self, tmp_path: Path) -> None:
        store = self._make_store(tmp_path)
        store.upsert(
            chunk_id="c1",
            file_path="f.py",
            chunk_type="function",
            name="fn",
            start_line=1,
            end_line=2,
            content="pass",
            embedding=np.ones(8, dtype=np.float32),
        )
        results = store.search(np.zeros(8, dtype=np.float32), top_k=5)
        assert results == []
        store.close()

    def test_delete_by_file(self, tmp_path: Path) -> None:
        store = self._make_store(tmp_path)
        for i, fp in enumerate(["a.py", "a.py", "b.py"]):
            store.upsert(
                chunk_id=f"chunk_{i}",
                file_path=fp,
                chunk_type="block",
                name=f"block_{i}",
                start_line=1,
                end_line=5,
                content="pass",
                embedding=np.random.randn(8).astype(np.float32),
            )
        assert store.count() == 3
        deleted = store.delete_by_file("a.py")
        assert deleted == 2
        assert store.count() == 1
        store.close()

    def test_delete_by_file_nonexistent(self, tmp_path: Path) -> None:
        store = self._make_store(tmp_path)
        deleted = store.delete_by_file("nonexistent.py")
        assert deleted == 0
        store.close()

    def test_metadata_in_search_results(self, tmp_path: Path) -> None:
        store = self._make_store(tmp_path)
        store.upsert(
            chunk_id="my_chunk",
            file_path="src/lib.py",
            chunk_type="class",
            name="MyClass",
            start_line=10,
            end_line=50,
            content="class MyClass: ...",
            embedding=np.ones(8, dtype=np.float32),
        )
        results = store.search(np.ones(8, dtype=np.float32), top_k=1)
        assert len(results) == 1
        m = results[0]
        assert m.chunk_id == "my_chunk"
        assert m.metadata["file_path"] == "src/lib.py"
        assert m.metadata["chunk_type"] == "class"
        assert m.metadata["name"] == "MyClass"
        assert m.metadata["start_line"] == 10
        assert m.metadata["end_line"] == 50
        assert m.score == pytest.approx(1.0, abs=1e-5)
        store.close()


# ── HierarchicalIndex hybrid search tests ─────────────────────────


def _make_fake_embed(dim: int = 8):
    """Return a mock embed_texts_openai_compat that produces deterministic vectors."""
    call_count = 0

    def fake_embed(texts: Sequence[str]) -> Tuple[List[Optional[List[float]]], Dict[str, Any]]:
        nonlocal call_count
        result = []
        for i, t in enumerate(texts):
            # Produce a deterministic vector seeded by text hash
            seed = hash(t) % (2**31)
            rng = np.random.RandomState(seed)
            vec = rng.randn(dim).astype(np.float32).tolist()
            result.append(vec)
        call_count += 1
        return result, {"ok": True, "count": len(texts)}

    return fake_embed


class TestHierarchicalIndexHybridSearch:
    """Test hybrid keyword + vector search in HierarchicalIndex."""

    def _setup_index(self, tmp_path: Path) -> Any:
        """Create a HierarchicalIndex with a small indexed file."""
        index_root = tmp_path / "idx"
        idx = HierarchicalIndex(index_root=str(index_root))
        return idx

    def test_keyword_search_still_works(self, tmp_path: Path) -> None:
        """Keyword search should work even without vector store."""
        idx = self._setup_index(tmp_path)
        source = "def hello_world():\n    pass\n\ndef goodbye_world():\n    pass\n"
        idx.index_file("example.py", source=source)

        results = idx._keyword_search("hello", top_k=5)
        assert any(r.get("name") == "hello_world" for r in results)

    @patch("agents.memory.hierarchical_rag.np", np)
    def test_hybrid_search_merges_results(self, tmp_path: Path) -> None:
        """Hybrid search should merge vector and keyword results, deduplicating."""
        idx = self._setup_index(tmp_path)
        source = "def alpha():\n    pass\n\ndef beta():\n    pass\n"
        fake_embed = _make_fake_embed(dim=8)

        with patch("summer_memory.embedding_openai_compat.embed_texts_openai_compat", fake_embed):
            # Manually set up vector store
            vs = L3VectorStore(db_path=tmp_path / "idx" / "vectors" / "l3_code_index.db", dimensions=8)
            idx._vector_store = vs

            # Index chunks into vector store
            chunks = _ast_mod.chunk_file("example.py", source)
            idx._index_chunks_to_vector_store(vs, chunks, "example.py")

            # Also persist JSON index for keyword search
            idx.index_file("example.py", source=source)

            # Now search — mock the embedding call for the query
            with patch("agents.memory.hierarchical_rag.embed_texts_openai_compat", fake_embed, create=True):
                # Patch at the import location inside search()
                import summer_memory.embedding_openai_compat as emb_mod

                original = emb_mod.embed_texts_openai_compat
                emb_mod.embed_texts_openai_compat = fake_embed
                try:
                    results = idx.search("alpha", top_k=10)
                finally:
                    emb_mod.embed_texts_openai_compat = original

        # At minimum keyword should find "alpha"
        assert len(results) > 0

        # Check deduplication: no duplicate chunk_ids
        chunk_ids = [r.get("chunk_id") for r in results if r.get("chunk_id")]
        assert len(chunk_ids) == len(set(chunk_ids))

    def test_hybrid_search_graceful_when_no_vector_store(self, tmp_path: Path) -> None:
        """search() should still return keyword results if vector store fails."""
        idx = self._setup_index(tmp_path)
        source = "def foo_bar():\n    pass\n"
        idx.index_file("test.py", source=source)

        # Force vector store to None
        idx._vector_store = None

        # Patch _get_vector_store to return None (simulating failure)
        with patch.object(idx, "_get_vector_store", return_value=None):
            results = idx.search("foo_bar", top_k=5)

        assert len(results) >= 1
        assert any(r.get("name") == "foo_bar" for r in results)

    def test_deduplication_prefers_vector_results(self, tmp_path: Path) -> None:
        """When same chunk_id appears in both vector and keyword results,
        the vector result should appear (it comes first in merge order)."""
        idx = self._setup_index(tmp_path)
        source = "def target_func():\n    pass\n"
        idx.index_file("t.py", source=source)

        # Create a mock vector store that returns a result for target_func
        mock_store = MagicMock()
        mock_store.search.return_value = [
            VectorMatch(
                chunk_id="t_function_target_func",
                score=0.95,
                metadata={
                    "file_path": "t.py",
                    "chunk_type": "function",
                    "name": "target_func",
                    "start_line": 1,
                    "end_line": 2,
                },
            )
        ]
        idx._vector_store = mock_store

        fake_embed = _make_fake_embed(dim=8)
        import summer_memory.embedding_openai_compat as emb_mod

        original = emb_mod.embed_texts_openai_compat
        emb_mod.embed_texts_openai_compat = fake_embed
        try:
            results = idx.search("target_func", top_k=10)
        finally:
            emb_mod.embed_texts_openai_compat = original

        # The first result for chunk_id "t_function_target_func" should be the vector one
        target_results = [r for r in results if r.get("chunk_id") == "t_function_target_func"]
        assert len(target_results) == 1  # deduplicated
        assert target_results[0].get("match_type") == "vector"
        assert target_results[0].get("score") == pytest.approx(0.95)
