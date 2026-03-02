"""Tests for Phase 3.1 — Atomic Prompt Engine (PromptAssembler)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from agents.prompt_engine import (
    DNAIntegrityError,
    PromptAssembler,
    PromptBlockNotFoundError,
)


@pytest.fixture
def prompts_dir(tmp_path: Path) -> Path:
    """Create a minimal prompts directory for testing."""
    dna_dir = tmp_path / "dna"
    dna_dir.mkdir()
    (dna_dir / "shell_persona.md").write_text(
        "# Shell Persona DNA\nYou are Embla.", encoding="utf-8"
    )
    (dna_dir / "core_values.md").write_text(
        "# Core Values DNA\nQuality first.", encoding="utf-8"
    )

    roles_dir = tmp_path / "roles"
    roles_dir.mkdir()
    (roles_dir / "backend_expert.md").write_text(
        "# Role: Backend Expert\nBackend development.", encoding="utf-8"
    )

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "python_ast.md").write_text(
        "# Skill: Python AST\nAST analysis.", encoding="utf-8"
    )

    styles_dir = tmp_path / "styles"
    styles_dir.mkdir()
    (styles_dir / "code_with_tests.md").write_text(
        "# Style: Code + Tests\nAlways write tests.", encoding="utf-8"
    )

    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    (rules_dir / "conventional_commit.md").write_text(
        "# Rule: Conventional Commit\nfeat/fix/refactor.", encoding="utf-8"
    )

    return tmp_path


@pytest.fixture
def assembler(prompts_dir: Path) -> PromptAssembler:
    return PromptAssembler(prompts_root=str(prompts_dir))


# ── DNA Loading ────────────────────────────────────────────────


class TestDNALoading:

    def test_load_dna_success(self, assembler: PromptAssembler) -> None:
        content = assembler.load_dna("shell_persona")
        assert "Embla" in content
        assert "# Shell Persona DNA" in content

    def test_load_dna_not_found(self, assembler: PromptAssembler) -> None:
        with pytest.raises(PromptBlockNotFoundError):
            assembler.load_dna("nonexistent_dna")

    def test_load_dna_integrity_pass(self, prompts_dir: Path) -> None:
        content = (prompts_dir / "dna" / "shell_persona.md").read_text(encoding="utf-8")
        correct_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        assembler = PromptAssembler(
            prompts_root=str(prompts_dir),
            dna_checksums={"shell_persona": correct_hash},
            strict_dna=True,
        )
        result = assembler.load_dna("shell_persona")
        assert "Embla" in result

    def test_load_dna_integrity_fail_strict(self, prompts_dir: Path) -> None:
        assembler = PromptAssembler(
            prompts_root=str(prompts_dir),
            dna_checksums={"shell_persona": "bad_hash"},
            strict_dna=True,
        )
        with pytest.raises(DNAIntegrityError):
            assembler.load_dna("shell_persona")

    def test_load_dna_integrity_fail_non_strict(self, prompts_dir: Path) -> None:
        assembler = PromptAssembler(
            prompts_root=str(prompts_dir),
            dna_checksums={"shell_persona": "bad_hash"},
            strict_dna=False,
        )
        # Should warn but not raise
        result = assembler.load_dna("shell_persona")
        assert "Embla" in result


# ── Block Loading ──────────────────────────────────────────────


class TestBlockLoading:

    def test_load_block_success(self, assembler: PromptAssembler) -> None:
        content = assembler.load_block("roles/backend_expert.md")
        assert "Backend" in content

    def test_load_block_not_found(self, assembler: PromptAssembler) -> None:
        with pytest.raises(PromptBlockNotFoundError):
            assembler.load_block("roles/nonexistent.md")

    def test_load_multiple_blocks(self, assembler: PromptAssembler) -> None:
        role = assembler.load_block("roles/backend_expert.md")
        skill = assembler.load_block("skills/python_ast.md")
        assert "Backend" in role
        assert "AST" in skill


# ── Assembly ───────────────────────────────────────────────────


class TestAssembly:

    def test_assemble_dna_only(self, assembler: PromptAssembler) -> None:
        prompt = assembler.assemble(dna="shell_persona")
        assert "Embla" in prompt

    def test_assemble_dna_and_blocks(self, assembler: PromptAssembler) -> None:
        prompt = assembler.assemble(
            dna="core_values",
            blocks=["roles/backend_expert.md", "skills/python_ast.md"],
        )
        assert "Quality first" in prompt
        assert "Backend" in prompt
        assert "AST" in prompt

    def test_assemble_with_memory_hints(self, assembler: PromptAssembler) -> None:
        prompt = assembler.assemble(
            dna="shell_persona",
            memory_hints=["memory/episodic/exp_20260303_001.md"],
        )
        assert "相关经验" in prompt
        assert "exp_20260303_001.md" in prompt

    def test_assemble_with_extra_sections(self, assembler: PromptAssembler) -> None:
        prompt = assembler.assemble(
            dna="shell_persona",
            extra_sections=["## Custom Section\nCustom content here."],
        )
        assert "Custom Section" in prompt
        assert "Custom content here." in prompt

    def test_assemble_skips_missing_blocks(self, assembler: PromptAssembler) -> None:
        prompt = assembler.assemble(
            dna="shell_persona",
            blocks=["roles/backend_expert.md", "roles/nonexistent.md"],
        )
        assert "Backend" in prompt
        assert "Embla" in prompt

    def test_assemble_no_dna(self, assembler: PromptAssembler) -> None:
        prompt = assembler.assemble(blocks=["roles/backend_expert.md"])
        assert "Backend" in prompt

    def test_assemble_full_pipeline(self, assembler: PromptAssembler) -> None:
        prompt = assembler.assemble(
            dna="core_values",
            blocks=[
                "roles/backend_expert.md",
                "skills/python_ast.md",
                "styles/code_with_tests.md",
                "rules/conventional_commit.md",
            ],
            memory_hints=[
                "memory/episodic/exp_20260301_001.md",
                "memory/domain/python_ast_patterns.md",
            ],
            extra_sections=["## Task\nImplement REST API."],
        )
        assert "Quality first" in prompt
        assert "Backend" in prompt
        assert "AST" in prompt
        assert "Always write tests" in prompt
        assert "Conventional Commit" in prompt
        assert "exp_20260301_001.md" in prompt
        assert "REST API" in prompt


# ── Listing ────────────────────────────────────────────────────


class TestListing:

    def test_list_blocks_all(self, assembler: PromptAssembler) -> None:
        blocks = assembler.list_blocks()
        assert "roles/backend_expert.md" in blocks
        assert "skills/python_ast.md" in blocks
        assert "styles/code_with_tests.md" in blocks
        # DNA should NOT be in general list
        assert all(not b.startswith("dna") for b in blocks)

    def test_list_blocks_by_category(self, assembler: PromptAssembler) -> None:
        roles = assembler.list_blocks("roles")
        assert "roles/backend_expert.md" in roles
        assert all(b.startswith("roles/") for b in roles)

    def test_list_dna(self, assembler: PromptAssembler) -> None:
        dna_list = assembler.list_dna()
        assert "shell_persona" in dna_list
        assert "core_values" in dna_list

    def test_list_blocks_nonexistent_category(self, assembler: PromptAssembler) -> None:
        blocks = assembler.list_blocks("nonexistent")
        assert blocks == []


# ── Caching ────────────────────────────────────────────────────


class TestCaching:

    def test_cached_read_returns_same_content(self, assembler: PromptAssembler) -> None:
        content1 = assembler.load_dna("shell_persona")
        content2 = assembler.load_dna("shell_persona")
        assert content1 == content2
        assert content1 is content2  # Same object from cache


# ── Integration with Real Prompts ──────────────────────────────


class TestRealPrompts:
    """Test with the actual prompts/ directory if it exists."""

    def test_real_dna_files_exist(self) -> None:
        assembler = PromptAssembler()
        dna_list = assembler.list_dna()
        assert "shell_persona" in dna_list
        assert "core_values" in dna_list

    def test_real_shell_persona_loads(self) -> None:
        assembler = PromptAssembler()
        content = assembler.load_dna("shell_persona")
        assert "恩布拉" in content or "Embla" in content

    def test_real_core_values_loads(self) -> None:
        assembler = PromptAssembler()
        content = assembler.load_dna("core_values")
        assert "使命" in content or "质量" in content

    def test_real_blocks_exist(self) -> None:
        assembler = PromptAssembler()
        blocks = assembler.list_blocks()
        assert len(blocks) >= 4  # roles, skills, styles, rules each have at least 1
