from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from scripts.validate_immutable_dna_gate_ws23_003 import run_immutable_dna_gate


def _make_case_root(prefix: str) -> Path:
    root = Path("scratch") / prefix / uuid.uuid4().hex[:12]
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_case_root(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


def _write_prompt_files(prompts_root: Path) -> None:
    prompts_root.mkdir(parents=True, exist_ok=True)
    (prompts_root / "conversation_style_prompt.md").write_text("style-v1\n", encoding="utf-8")
    (prompts_root / "conversation_analyzer_prompt.md").write_text("analyzer-v1\n", encoding="utf-8")
    (prompts_root / "tool_dispatch_prompt.md").write_text("dispatch-v1\n", encoding="utf-8")
    (prompts_root / "agentic_tool_prompt.md").write_text("tool-v1\n", encoding="utf-8")
    (prompts_root / "shell_persona.md").write_text("shell-v1\n", encoding="utf-8")
    (prompts_root / "core_values.md").write_text("core-v1\n", encoding="utf-8")


def test_immutable_dna_gate_can_bootstrap_and_pass() -> None:
    case_root = _make_case_root("test_ws23_003_immutable_dna_gate")
    try:
        prompts_root = case_root / "prompts"
        _write_prompt_files(prompts_root)
        report = run_immutable_dna_gate(
            prompts_root=prompts_root,
            manifest_path=prompts_root / "immutable_dna_manifest.spec",
            audit_file=case_root / "audit.jsonl",
            output_file=case_root / "report.json",
            bootstrap_if_missing=True,
        )
        assert report["passed"] is True
        assert report["bootstrapped_manifest"] is True
        assert report["reason"] == "ok"
        assert report["missing_required_files"] == []
    finally:
        _cleanup_case_root(case_root)


def test_immutable_dna_gate_rejects_missing_manifest_without_bootstrap() -> None:
    case_root = _make_case_root("test_ws23_003_immutable_dna_gate")
    try:
        prompts_root = case_root / "prompts"
        _write_prompt_files(prompts_root)
        report = run_immutable_dna_gate(
            prompts_root=prompts_root,
            manifest_path=prompts_root / "immutable_dna_manifest.spec",
            audit_file=case_root / "audit.jsonl",
            output_file=case_root / "report.json",
            bootstrap_if_missing=False,
        )
        assert report["passed"] is False
        assert report["reason"] == "manifest_missing"
    finally:
        _cleanup_case_root(case_root)


def test_immutable_dna_gate_detects_prompt_tamper_after_manifest_bootstrap() -> None:
    case_root = _make_case_root("test_ws23_003_immutable_dna_gate")
    try:
        prompts_root = case_root / "prompts"
        _write_prompt_files(prompts_root)
        run_immutable_dna_gate(
            prompts_root=prompts_root,
            manifest_path=prompts_root / "immutable_dna_manifest.spec",
            audit_file=case_root / "audit.jsonl",
            output_file=case_root / "bootstrap.json",
            bootstrap_if_missing=True,
        )
        (prompts_root / "agentic_tool_prompt.md").write_text("tool-v2-tampered\n", encoding="utf-8")

        report = run_immutable_dna_gate(
            prompts_root=prompts_root,
            manifest_path=prompts_root / "immutable_dna_manifest.spec",
            audit_file=case_root / "audit.jsonl",
            output_file=case_root / "report.json",
            bootstrap_if_missing=False,
        )
        assert report["passed"] is False
        assert report["reason"] == "dna_hash_mismatch"
        assert "agentic_tool_prompt.md" in report["verify"]["mismatch_files"]
    finally:
        _cleanup_case_root(case_root)


def test_immutable_dna_gate_rejects_json_manifest_extension() -> None:
    case_root = _make_case_root("test_ws23_003_immutable_dna_gate")
    try:
        prompts_root = case_root / "prompts"
        _write_prompt_files(prompts_root)
        report = run_immutable_dna_gate(
            prompts_root=prompts_root,
            manifest_path=prompts_root / "immutable_dna_manifest.json",
            audit_file=case_root / "audit.jsonl",
            output_file=case_root / "report.json",
            bootstrap_if_missing=True,
        )
        assert report["passed"] is False
        assert report["reason"] == "manifest_extension_not_spec"
    finally:
        _cleanup_case_root(case_root)
