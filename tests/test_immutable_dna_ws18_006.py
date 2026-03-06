"""WS18-006 immutable DNA verification tests."""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

import pytest

from core.security.immutable_dna import DNAFileSpec, ImmutableDNALoader


def _make_case_root(prefix: str) -> Path:
    root = Path("scratch") / prefix / uuid.uuid4().hex[:12]
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_case_root(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


def _write_prompts(root: Path) -> None:
    (root / "conversation_style_prompt.md").write_text("STYLE_PROMPT", encoding="utf-8")
    (root / "conversation_analyzer_prompt.md").write_text("ANALYZER_PROMPT", encoding="utf-8")
    (root / "tool_dispatch_prompt.md").write_text("DISPATCH_PROMPT", encoding="utf-8")
    (root / "agentic_tool_prompt.md").write_text("AGENTIC_PROMPT", encoding="utf-8")


def test_immutable_dna_bootstrap_verify_and_inject_order() -> None:
    case_root = _make_case_root("test_immutable_dna_ws18_006")
    try:
        _write_prompts(case_root)
        loader = ImmutableDNALoader(root_dir=case_root)
        manifest = loader.bootstrap_manifest()
        assert manifest.injection_order == [
            "conversation_style_prompt.md",
            "agentic_tool_prompt.md",
        ]

        verify = loader.verify()
        assert verify.ok is True

        injected = loader.inject()
        assert injected["schema_version"] == loader.MANIFEST_SCHEMA_VERSION
        assert injected["injection_order"] == manifest.injection_order
        assert "[DNA:conversation_style_prompt.md]" in injected["dna_text"]
        assert "[DNA:agentic_tool_prompt.md]" in injected["dna_text"]
        assert injected["dna_hash"]
    finally:
        _cleanup_case_root(case_root)


def test_immutable_dna_rejects_unauthorized_tamper() -> None:
    case_root = _make_case_root("test_immutable_dna_ws18_006")
    try:
        _write_prompts(case_root)
        loader = ImmutableDNALoader(root_dir=case_root)
        loader.bootstrap_manifest()

        # Tamper prompt after manifest sealed.
        (case_root / "agentic_tool_prompt.md").write_text("AGENTIC_PROMPT_TAMPERED", encoding="utf-8")
        verify = loader.verify()
        assert verify.ok is False
        assert "agentic_tool_prompt.md" in verify.mismatch_files

        with pytest.raises(PermissionError):
            loader.inject()
    finally:
        _cleanup_case_root(case_root)


def test_immutable_dna_manifest_update_requires_approval_ticket() -> None:
    case_root = _make_case_root("test_immutable_dna_ws18_006")
    try:
        _write_prompts(case_root)
        loader = ImmutableDNALoader(root_dir=case_root)
        with pytest.raises(PermissionError):
            loader.approved_update_manifest(approval_ticket="")
        loader.approved_update_manifest(approval_ticket="CAB-2026-02-24")

        audits = [json.loads(line) for line in (case_root / "immutable_dna_audit.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        assert any(item.get("event") == "dna_manifest_update_rejected" for item in audits)
        assert any(item.get("event") == "dna_manifest_update_approved" for item in audits)
    finally:
        _cleanup_case_root(case_root)


def test_immutable_dna_supports_custom_file_order() -> None:
    case_root = _make_case_root("test_immutable_dna_ws18_006")
    try:
        _write_prompts(case_root)
        custom = [
            DNAFileSpec(path="tool_dispatch_prompt.md"),
            DNAFileSpec(path="conversation_style_prompt.md"),
        ]
        loader = ImmutableDNALoader(root_dir=case_root, dna_files=custom)
        manifest = loader.bootstrap_manifest()
        assert manifest.injection_order == ["tool_dispatch_prompt.md", "conversation_style_prompt.md"]
        injected = loader.inject()
        first_idx = injected["dna_text"].find("[DNA:tool_dispatch_prompt.md]")
        second_idx = injected["dna_text"].find("[DNA:conversation_style_prompt.md]")
        assert first_idx >= 0 and second_idx > first_idx
    finally:
        _cleanup_case_root(case_root)
