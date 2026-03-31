"""Tests for Phase 3.3/3.4 — L2 Sync, AST Chunker, and Hierarchical RAG."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents.memory.ast_chunker import (
    CodeChunk,
    chunk_by_lines,
    chunk_file,
    chunk_markdown_file,
    chunk_python_file,
)
from agents.memory.hierarchical_rag import HierarchicalIndex
from agents.memory.l1_to_l2_sync import (
    extract_entities_from_experience_md,
    sync_experience_to_graph,
    sync_all_experiences,
)


# ── AST Chunker ───────────────────────────────────────────────


SAMPLE_PYTHON = '''\
"""Module docstring."""

import os
from pathlib import Path

FOO = 42


def greet(name: str) -> str:
    """Say hello."""
    return f"Hello, {name}"


class Calculator:
    """Basic calculator."""

    def add(self, a: int, b: int) -> int:
        return a + b

    def sub(self, a: int, b: int) -> int:
        return a - b


async def fetch_data(url: str) -> bytes:
    """Async fetcher."""
    return b""
'''

SAMPLE_MARKDOWN = """\
# Architecture

Overview of the system.

## Shell Agent

Shell handles user interaction.

## Core Agent

Core handles execution.

### Expert Spawning

Core spawns experts.

## Memory System

Three layers of memory.
"""


class TestPythonChunker:

    def test_chunks_functions_and_classes(self) -> None:
        chunks = chunk_python_file("test.py", SAMPLE_PYTHON)
        names = [c.name for c in chunks]
        assert "greet" in names
        assert "Calculator" in names
        assert "fetch_data" in names

    def test_preserves_line_numbers(self) -> None:
        chunks = chunk_python_file("test.py", SAMPLE_PYTHON)
        greet = next(c for c in chunks if c.name == "greet")
        assert greet.start_line > 0
        assert greet.end_line >= greet.start_line

    def test_chunk_types(self) -> None:
        chunks = chunk_python_file("test.py", SAMPLE_PYTHON)
        types = {c.chunk_type for c in chunks}
        assert "function" in types
        assert "class" in types

    def test_has_top_level(self) -> None:
        chunks = chunk_python_file("test.py", SAMPLE_PYTHON)
        top_chunks = [c for c in chunks if c.chunk_type == "top_level"]
        assert len(top_chunks) >= 1  # imports + FOO = 42

    def test_token_estimate(self) -> None:
        chunks = chunk_python_file("test.py", SAMPLE_PYTHON)
        for chunk in chunks:
            assert chunk.token_estimate > 0

    def test_syntax_error_fallback(self) -> None:
        bad_python = "def broken(\n  pass  # missing closing paren"
        chunks = chunk_python_file("bad.py", bad_python)
        assert len(chunks) >= 1  # Falls back to line-based

    def test_chunk_ids_are_unique(self) -> None:
        chunks = chunk_python_file("test.py", SAMPLE_PYTHON)
        ids = [c.chunk_id for c in chunks]
        assert len(ids) == len(set(ids))


class TestMarkdownChunker:

    def test_chunks_by_headings(self) -> None:
        chunks = chunk_markdown_file("doc.md", SAMPLE_MARKDOWN)
        names = [c.name for c in chunks]
        assert "Architecture" in names
        assert "Shell Agent" in names
        assert "Core Agent" in names
        assert "Memory System" in names

    def test_heading_types(self) -> None:
        chunks = chunk_markdown_file("doc.md", SAMPLE_MARKDOWN)
        for chunk in chunks:
            assert chunk.chunk_type == "heading"

    def test_no_headings_fallback(self) -> None:
        plain_md = "Just some text without headings.\nLine two."
        chunks = chunk_markdown_file("plain.md", plain_md)
        assert len(chunks) == 1
        assert chunks[0].chunk_type == "block"


class TestLineChunker:

    def test_chunks_by_line_count(self) -> None:
        source = "\n".join(f"line {i}" for i in range(120))
        chunks = chunk_by_lines("big.txt", source, max_lines=50)
        assert len(chunks) == 3  # 120/50 = 2.4 → 3 blocks

    def test_empty_file(self) -> None:
        chunks = chunk_by_lines("empty.txt", "")
        assert len(chunks) == 0


class TestChunkFile:

    def test_auto_detect_python(self) -> None:
        chunks = chunk_file("test.py", SAMPLE_PYTHON)
        assert any(c.chunk_type == "function" for c in chunks)

    def test_auto_detect_markdown(self) -> None:
        chunks = chunk_file("doc.md", SAMPLE_MARKDOWN)
        assert any(c.chunk_type == "heading" for c in chunks)

    def test_auto_detect_other(self) -> None:
        chunks = chunk_file("data.csv", "col1,col2\na,b\nc,d")
        assert all(c.chunk_type == "block" for c in chunks)


# ── L1 → L2 Sync ──────────────────────────────────────────────


SAMPLE_EXPERIENCE_MD = """\
# 经验：Pipeline Refactoring

tags: #refactor #pipeline #agents
task: t-001
outcome: success
date: 20260303

## 问题
Old path routing was complex.

## 解决方案
Unified pipeline with `agents/pipeline.py` and `agents/shell_agent.py`.

## 变更文件
- `agents/pipeline.py`
- `agents/shell_agent.py`
- `tests/test_agent_roles_ws30_005.py`
"""


class TestEntityExtraction:

    def test_extracts_title(self) -> None:
        result = extract_entities_from_experience_md(SAMPLE_EXPERIENCE_MD)
        assert "Pipeline Refactoring" in result["title"]

    def test_extracts_tags(self) -> None:
        result = extract_entities_from_experience_md(SAMPLE_EXPERIENCE_MD)
        assert "refactor" in result["tags"]
        assert "pipeline" in result["tags"]

    def test_extracts_task_id(self) -> None:
        result = extract_entities_from_experience_md(SAMPLE_EXPERIENCE_MD)
        assert result["task_id"] == "t-001"

    def test_extracts_outcome(self) -> None:
        result = extract_entities_from_experience_md(SAMPLE_EXPERIENCE_MD)
        assert result["outcome"] == "success"

    def test_extracts_file_references(self) -> None:
        result = extract_entities_from_experience_md(SAMPLE_EXPERIENCE_MD)
        assert "agents/pipeline.py" in result["files"]
        assert "agents/shell_agent.py" in result["files"]

    def test_derives_topics(self) -> None:
        result = extract_entities_from_experience_md(SAMPLE_EXPERIENCE_MD)
        assert len(result["topics"]) >= 3  # tags + title keywords


class TestSyncPipeline:

    def test_sync_single_experience(self, tmp_path: Path) -> None:
        exp_file = tmp_path / "exp_20260303_pipeline_refactoring.md"
        exp_file.write_text(SAMPLE_EXPERIENCE_MD, encoding="utf-8")

        from agents.memory.semantic_graph import SemanticGraphStore
        graph = SemanticGraphStore(graph_path=tmp_path / "graph.json")

        result = sync_experience_to_graph(
            exp_file,
            session_id="test_sync",
            graph=graph,
        )
        assert result["synced"]
        assert "entities" in result

    def test_sync_nonexistent_file(self, tmp_path: Path) -> None:
        result = sync_experience_to_graph(tmp_path / "nope.md")
        assert not result["synced"]

    def test_sync_all(self, tmp_path: Path) -> None:
        episodic = tmp_path / "episodic"
        episodic.mkdir()

        for i in range(3):
            (episodic / f"exp_20260303_test_experience_{i}.md").write_text(
                SAMPLE_EXPERIENCE_MD, encoding="utf-8"
            )

        from agents.memory.semantic_graph import SemanticGraphStore
        graph = SemanticGraphStore(graph_path=tmp_path / "graph.json")

        result = sync_all_experiences(episodic, graph=graph)
        assert result["total"] == 3
        assert result["synced"] == 3
        assert result["errors"] == 0


# ── Hierarchical RAG Index ─────────────────────────────────────


class TestHierarchicalIndex:

    @pytest.fixture
    def idx(self, tmp_path: Path) -> HierarchicalIndex:
        return HierarchicalIndex(index_root=str(tmp_path / "hierarchical"))

    @pytest.fixture
    def sample_py(self, tmp_path: Path) -> Path:
        f = tmp_path / "sample.py"
        f.write_text(SAMPLE_PYTHON, encoding="utf-8")
        return f

    @pytest.fixture
    def sample_md(self, tmp_path: Path) -> Path:
        f = tmp_path / "doc.md"
        f.write_text(SAMPLE_MARKDOWN, encoding="utf-8")
        return f

    def test_index_python_file(self, idx: HierarchicalIndex, sample_py: Path) -> None:
        entry = idx.index_file(str(sample_py))
        assert entry.chunk_count > 0
        assert "sample.py" in entry.summary

    def test_get_summary(self, idx: HierarchicalIndex, sample_py: Path) -> None:
        idx.index_file(str(sample_py))
        summary = idx.get_summary(str(sample_py))
        assert "sample.py" in summary
        assert len(summary) > 10

    def test_get_section_index(self, idx: HierarchicalIndex, sample_py: Path) -> None:
        idx.index_file(str(sample_py))
        sections = idx.get_section_index(str(sample_py))
        assert len(sections) > 0
        names = [s["name"] for s in sections]
        assert "greet" in names or "Calculator" in names

    def test_get_chunk_by_id(self, idx: HierarchicalIndex, sample_py: Path) -> None:
        idx.index_file(str(sample_py))
        sections = idx.get_section_index(str(sample_py))
        first_id = sections[0]["chunk_id"]
        content = idx.get_chunk(str(sample_py), first_id)
        assert len(content) > 0

    def test_get_chunk_not_found(self, idx: HierarchicalIndex, sample_py: Path) -> None:
        idx.index_file(str(sample_py))
        content = idx.get_chunk(str(sample_py), "nonexistent_chunk")
        assert content == ""

    def test_is_indexed(self, idx: HierarchicalIndex, sample_py: Path) -> None:
        assert not idx.is_indexed(str(sample_py))
        idx.index_file(str(sample_py))
        assert idx.is_indexed(str(sample_py))

    def test_list_indexed(self, idx: HierarchicalIndex, sample_py: Path, sample_md: Path) -> None:
        idx.index_file(str(sample_py))
        idx.index_file(str(sample_md))
        indexed = idx.list_indexed()
        assert len(indexed) == 2

    def test_search(self, idx: HierarchicalIndex, sample_py: Path) -> None:
        idx.index_file(str(sample_py))
        results = idx.search("greet")
        assert len(results) >= 1
        assert any("greet" in r.get("name", "").lower() for r in results)

    def test_search_no_results(self, idx: HierarchicalIndex, sample_py: Path) -> None:
        idx.index_file(str(sample_py))
        results = idx.search("xyznonexistent")
        assert len(results) == 0

    def test_markdown_index(self, idx: HierarchicalIndex, sample_md: Path) -> None:
        entry = idx.index_file(str(sample_md))
        assert entry.chunk_count > 0
        sections = idx.get_section_index(str(sample_md))
        names = [s["name"] for s in sections]
        assert "Architecture" in names or "Shell Agent" in names

    def test_summary_not_indexed(self, idx: HierarchicalIndex) -> None:
        assert idx.get_summary("nonexistent.py") == ""
