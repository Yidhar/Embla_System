"""WS34 Phase 1 — Self-introspection tools for self-evolution.

Tests for agents/evolution/ package: ACL checking, list_my_prompts, read_my_prompt.
"""
import json
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Helpers — build a minimal prompt tree inside tmp_path
# ---------------------------------------------------------------------------

ACL_SPEC = json.dumps({
    "enforcement_mode": "block",
    "rules": [
        {"path_pattern": "dna/shell_persona.md", "level": "S1_CONTROLLED", "allow_ai_direct_write": False},
        {"path_pattern": "dna/core_values.md", "level": "S1_CONTROLLED", "allow_ai_direct_write": False},
        {"path_pattern": "core/dna/agentic_tool_prompt.md", "level": "S1_CONTROLLED", "allow_ai_direct_write": False},
        {"path_pattern": "*.md", "level": "S2_FLEXIBLE", "allow_ai_direct_write": True},
    ],
})

# Patch targets: get_system_prompts_root is defined in agents.prompt_engine and
# re-imported by system.config.  Both acl_checker.py and self_tools.py do
# `from system.config import get_system_prompts_root` inside functions, which
# resolves through system.config's namespace.  We patch both locations so
# that any lazy import sees the override.
_PATCH_TARGETS = [
    "agents.prompt_engine.get_system_prompts_root",
    "system.config.get_system_prompts_root",
]


def _build_prompt_tree(tmp: Path) -> Path:
    """Create a minimal prompt directory tree for testing."""
    root = tmp / "prompts"

    # specs/
    specs = root / "specs"
    specs.mkdir(parents=True)
    (specs / "prompt_acl.spec").write_text(ACL_SPEC, encoding="utf-8")

    # dna/
    dna = root / "dna"
    dna.mkdir()
    (dna / "shell_persona.md").write_text("# Shell Persona DNA\nImmutable shell identity.", encoding="utf-8")
    (dna / "core_values.md").write_text("# Core Values DNA\nImmutable core values.", encoding="utf-8")

    # core/dna/
    core_dna = root / "core" / "dna"
    core_dna.mkdir(parents=True)
    (core_dna / "agentic_tool_prompt.md").write_text("# Agentic Tool DNA\nTool contract.", encoding="utf-8")

    # roles/
    roles = root / "roles"
    roles.mkdir()
    (roles / "backend_expert.md").write_text("# Backend Expert\nRole prompt.", encoding="utf-8")
    (roles / "frontend_expert.md").write_text("# Frontend Expert\nRole prompt.", encoding="utf-8")

    # skills/
    skills = root / "skills"
    skills.mkdir()
    (skills / "python_ast.md").write_text("# Python AST Skill\nSkill prompt.", encoding="utf-8")

    return root


# ---------------------------------------------------------------------------
# ACL checker unit tests
# ---------------------------------------------------------------------------


class TestPromptACLChecker:
    def test_acl_checker_dna_path_not_writable(self, tmp_path):
        """DNA paths must be immutable and not writable regardless of ACL level."""
        root = _build_prompt_tree(tmp_path)
        from agents.evolution.acl_checker import PromptACLChecker

        checker = PromptACLChecker(prompts_root=root)

        perm_shell = checker.check("dna/shell_persona.md")
        assert perm_shell.immutable is True
        assert perm_shell.writable is False
        assert perm_shell.readable is True
        assert perm_shell.acl_level == "S1_CONTROLLED"

        perm_core = checker.check("core/dna/agentic_tool_prompt.md")
        assert perm_core.immutable is True
        assert perm_core.writable is False

    def test_acl_checker_roles_path_writable(self, tmp_path):
        """Non-DNA S2_FLEXIBLE paths should be writable."""
        root = _build_prompt_tree(tmp_path)
        from agents.evolution.acl_checker import PromptACLChecker

        checker = PromptACLChecker(prompts_root=root)

        perm = checker.check("roles/backend_expert.md")
        assert perm.immutable is False
        assert perm.writable is True
        assert perm.acl_level == "S2_FLEXIBLE"
        assert perm.readable is True


# ---------------------------------------------------------------------------
# list_my_prompts tests
# ---------------------------------------------------------------------------


class TestListMyPrompts:
    def _call(self, root: Path, **kwargs):
        with patch(_PATCH_TARGETS[0], return_value=root), patch(_PATCH_TARGETS[1], return_value=root):
            from agents.evolution.self_tools import list_my_prompts

            return list_my_prompts(**kwargs)

    def test_list_my_prompts_returns_all_md_files(self, tmp_path):
        """list_my_prompts(scope='all') returns all .md files except specs/."""
        root = _build_prompt_tree(tmp_path)
        results = self._call(root, scope="all")
        paths = [r["path"] for r in results]

        # Should include DNA, roles, skills, core/dna
        assert "dna/shell_persona.md" in paths
        assert "dna/core_values.md" in paths
        assert "roles/backend_expert.md" in paths
        assert "roles/frontend_expert.md" in paths
        assert "skills/python_ast.md" in paths
        assert "core/dna/agentic_tool_prompt.md" in paths

        # Should NOT include specs/ files
        for p in paths:
            assert not p.startswith("specs/"), f"specs file should be excluded: {p}"

    def test_list_my_prompts_scope_writable_excludes_dna(self, tmp_path):
        """scope='writable' should exclude DNA files (immutable, not writable)."""
        root = _build_prompt_tree(tmp_path)
        results = self._call(root, scope="writable")
        paths = [r["path"] for r in results]

        # DNA files must not appear
        assert "dna/shell_persona.md" not in paths
        assert "dna/core_values.md" not in paths
        assert "core/dna/agentic_tool_prompt.md" not in paths

        # Writable files should appear
        assert "roles/backend_expert.md" in paths
        assert "skills/python_ast.md" in paths

    def test_list_my_prompts_scope_dna_only_returns_dna_files(self, tmp_path):
        """scope='dna' should return only immutable DNA files."""
        root = _build_prompt_tree(tmp_path)
        results = self._call(root, scope="dna")
        paths = [r["path"] for r in results]

        # Only DNA files
        assert "dna/shell_persona.md" in paths
        assert "dna/core_values.md" in paths
        assert "core/dna/agentic_tool_prompt.md" in paths

        # Non-DNA must not appear
        assert "roles/backend_expert.md" not in paths
        assert "skills/python_ast.md" not in paths

        # Every result must be immutable
        for r in results:
            assert r["immutable"] is True


# ---------------------------------------------------------------------------
# read_my_prompt tests
# ---------------------------------------------------------------------------


class TestReadMyPrompt:
    def _call(self, root: Path, **kwargs):
        with patch(_PATCH_TARGETS[0], return_value=root), patch(_PATCH_TARGETS[1], return_value=root):
            from agents.evolution.self_tools import read_my_prompt

            return read_my_prompt(**kwargs)

    def test_read_my_prompt_returns_content_and_metadata(self, tmp_path):
        """Reading a valid prompt returns content, hash, size, and ACL info."""
        root = _build_prompt_tree(tmp_path)
        result = self._call(root, prompt_path="roles/backend_expert.md")

        assert result["found"] is True
        assert result["path"] == "roles/backend_expert.md"
        assert "# Backend Expert" in result["content"]
        assert result["acl_level"] == "S2_FLEXIBLE"
        assert result["writable"] is True
        assert result["immutable"] is False
        assert isinstance(result["content_sha256"], str)
        assert len(result["content_sha256"]) == 64  # SHA-256 hex length
        assert result["size_bytes"] > 0
        assert "last_modified" in result

    def test_read_my_prompt_dna_file_marked_immutable(self, tmp_path):
        """Reading a DNA file should mark it as immutable and not writable."""
        root = _build_prompt_tree(tmp_path)
        result = self._call(root, prompt_path="dna/shell_persona.md")

        assert result["found"] is True
        assert result["immutable"] is True
        assert result["writable"] is False
        assert "# Shell Persona DNA" in result["content"]

    def test_read_my_prompt_nonexistent_returns_error(self, tmp_path):
        """Reading a nonexistent prompt returns an error dict."""
        root = _build_prompt_tree(tmp_path)
        result = self._call(root, prompt_path="does/not/exist.md")

        assert result["found"] is False
        assert "error" in result
        assert "not found" in result["error"]
