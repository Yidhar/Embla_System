"""Tests for Phase 3.2 — L1 Memory Manager."""

from __future__ import annotations

from pathlib import Path

import pytest

from agents.memory.l1_memory import L1MemoryManager


@pytest.fixture
def memory_dir(tmp_path: Path) -> Path:
    return tmp_path / "memory"


@pytest.fixture
def mgr(memory_dir: Path) -> L1MemoryManager:
    return L1MemoryManager(memory_root=str(memory_dir))


# ── Working Memory ─────────────────────────────────────────────


class TestWorkingMemory:

    def test_init_session_creates_files(self, mgr: L1MemoryManager) -> None:
        session_dir = mgr.init_working_session("sess-001")
        assert session_dir.exists()
        assert (session_dir / "context.md").exists()
        assert (session_dir / "findings.md").exists()
        assert (session_dir / "decisions.md").exists()

    def test_write_context(self, mgr: L1MemoryManager) -> None:
        mgr.write_context("sess-001", "Working on pipeline refactoring.")
        data = mgr.read_working("sess-001")
        assert "pipeline refactoring" in data["context"]

    def test_write_findings(self, mgr: L1MemoryManager) -> None:
        mgr.write_findings("sess-001", "Found dead code in router.")
        data = mgr.read_working("sess-001")
        assert "dead code" in data["findings"]

    def test_write_decisions(self, mgr: L1MemoryManager) -> None:
        mgr.write_decisions("sess-001", "Decided to use PromptAssembler.")
        data = mgr.read_working("sess-001")
        assert "PromptAssembler" in data["decisions"]

    def test_append_adds_separator(self, mgr: L1MemoryManager) -> None:
        mgr.write_context("sess-001", "First entry.")
        mgr.write_context("sess-001", "Second entry.")
        data = mgr.read_working("sess-001")
        assert "First entry" in data["context"]
        assert "Second entry" in data["context"]
        assert "---" in data["context"]

    def test_read_nonexistent_session(self, mgr: L1MemoryManager) -> None:
        data = mgr.read_working("nonexistent")
        assert data["context"] == ""
        assert data["findings"] == ""
        assert data["decisions"] == ""

    def test_cleanup_session(self, mgr: L1MemoryManager) -> None:
        mgr.init_working_session("sess-del")
        assert mgr.cleanup_working_session("sess-del")
        assert not mgr.cleanup_working_session("sess-del")  # Already gone

    def test_init_session_idempotent(self, mgr: L1MemoryManager) -> None:
        mgr.init_working_session("sess-002")
        mgr.write_context("sess-002", "Important context.")
        mgr.init_working_session("sess-002")  # Should not overwrite
        data = mgr.read_working("sess-002")
        assert "Important context" in data["context"]


# ── Episodic Memory ────────────────────────────────────────────


class TestEpisodicMemory:

    def test_write_experience_creates_file(self, mgr: L1MemoryManager) -> None:
        path = mgr.write_experience(
            name="pipeline_refactoring",
            task_id="t-001",
            title="Pipeline Refactoring",
            outcome="success",
            problem="Old path routing.",
            solution="Unified pipeline.",
            files=["agents/pipeline.py"],
            tags=["refactor", "pipeline"],
        )
        assert path.exists()
        assert "pipeline_refactoring" in path.name
        content = path.read_text(encoding="utf-8")
        assert "Pipeline Refactoring" in content
        assert "#refactor" in content

    def test_filename_is_descriptive(self, mgr: L1MemoryManager) -> None:
        """File name must contain the slug, not just an opaque ID."""
        path = mgr.write_experience(
            name="ssh permission fix",
            task_id="t-002",
            title="SSH Permission Fix",
            outcome="success",
        )
        assert "ssh_permission_fix" in path.name
        assert path.name.startswith("exp_")
        assert path.name.endswith(".md")

    def test_name_required(self, mgr: L1MemoryManager) -> None:
        with pytest.raises(ValueError, match="name"):
            mgr.write_experience(
                name="",
                task_id="t-x",
                title="No Name",
                outcome="fail",
            )

    def test_duplicate_name_gets_counter(self, mgr: L1MemoryManager) -> None:
        p1 = mgr.write_experience(
            name="same_topic",
            task_id="t-1",
            title="Same Topic Round 1",
            outcome="success",
        )
        p2 = mgr.write_experience(
            name="same_topic",
            task_id="t-2",
            title="Same Topic Round 2",
            outcome="success",
        )
        assert p1 != p2
        assert p2.exists()
        assert "_2" in p2.name

    def test_index_updated(self, mgr: L1MemoryManager) -> None:
        mgr.write_experience(
            name="index_test",
            task_id="t-003",
            title="Index Test Experiment",
            outcome="success",
            tags=["test", "index"],
        )
        index_path = mgr._episodic_dir / "_index.md"
        assert index_path.exists()
        content = index_path.read_text(encoding="utf-8")
        assert "Index Test Experiment" in content
        assert "#test" in content

    def test_scan_index_by_tags(self, mgr: L1MemoryManager) -> None:
        mgr.write_experience(
            name="backend_api_fix",
            task_id="t-010",
            title="Backend API Fix",
            outcome="success",
            tags=["backend", "api"],
        )
        mgr.write_experience(
            name="frontend_ui_bug",
            task_id="t-011",
            title="Frontend UI Bug",
            outcome="success",
            tags=["frontend", "ui"],
        )
        results = mgr.scan_index(tags=["backend"])
        assert len(results) >= 1
        assert any("Backend" in r for r in results)

    def test_scan_index_no_tags(self, mgr: L1MemoryManager) -> None:
        mgr.write_experience(
            name="all_scan_a",
            task_id="t-020",
            title="All Scan A",
            outcome="success",
            tags=["alpha"],
        )
        mgr.write_experience(
            name="all_scan_b",
            task_id="t-021",
            title="All Scan B",
            outcome="success",
            tags=["beta"],
        )
        results = mgr.scan_index()
        assert len(results) >= 2

    def test_rebuild_index(self, mgr: L1MemoryManager) -> None:
        mgr.write_experience(
            name="rebuild_test",
            task_id="t-030",
            title="Rebuild Test",
            outcome="success",
            tags=["rebuild"],
        )
        count = mgr.rebuild_index()
        assert count >= 1


# ── Domain Memory ──────────────────────────────────────────────


class TestDomainMemory:

    def test_write_domain_knowledge(self, mgr: L1MemoryManager) -> None:
        path = mgr.write_domain_knowledge(
            "Python AST Patterns",
            "# Python AST Patterns\n\nContent...",
            tags=["python", "ast"],
        )
        assert path.exists()
        assert "python_ast_patterns" in path.name

    def test_domain_index_updated(self, mgr: L1MemoryManager) -> None:
        mgr.write_domain_knowledge(
            "API Design",
            "# API Design\nBest practices...",
            tags=["api", "design"],
        )
        index_path = mgr._domain_dir / "_index.md"
        assert index_path.exists()
        content = index_path.read_text(encoding="utf-8")
        assert "API Design" in content

    def test_search_domain(self, mgr: L1MemoryManager) -> None:
        mgr.write_domain_knowledge(
            "Docker Ops",
            "# Docker Ops\nContainer management...",
            tags=["docker", "ops"],
        )
        results = mgr.search_domain("docker")
        assert len(results) >= 1

    def test_search_domain_empty(self, mgr: L1MemoryManager) -> None:
        results = mgr.search_domain("nonexistent_query")
        assert results == []


# ── Slug Sanitization ──────────────────────────────────────────


class TestSlugSanitization:

    def test_spaces_to_underscores(self, mgr: L1MemoryManager) -> None:
        assert mgr._sanitize_slug("pipeline refactoring") == "pipeline_refactoring"

    def test_dashes_to_underscores(self, mgr: L1MemoryManager) -> None:
        assert mgr._sanitize_slug("ssh-permission-fix") == "ssh_permission_fix"

    def test_special_chars_removed(self, mgr: L1MemoryManager) -> None:
        assert mgr._sanitize_slug("API (v2.0)") == "api_v20"

    def test_collapses_underscores(self, mgr: L1MemoryManager) -> None:
        assert mgr._sanitize_slug("a    b___c") == "a_b_c"

    def test_empty_becomes_unnamed(self, mgr: L1MemoryManager) -> None:
        assert mgr._sanitize_slug("") == "unnamed"

    def test_cjk_preserved(self, mgr: L1MemoryManager) -> None:
        slug = mgr._sanitize_slug("管线重构")
        assert "管线重构" in slug
