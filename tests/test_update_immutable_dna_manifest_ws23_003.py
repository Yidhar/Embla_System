from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

from scripts.update_immutable_dna_manifest_ws23_003 import run_update_immutable_dna_manifest


def _make_case_root(prefix: str) -> Path:
    root = Path("scratch") / prefix / uuid.uuid4().hex[:12]
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_case_root(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


def _write_prompt_files(prompts_root: Path) -> None:
    prompts_root.mkdir(parents=True, exist_ok=True)
    (prompts_root / "conversation_style_prompt.txt").write_text("style-v1\n", encoding="utf-8")
    (prompts_root / "conversation_analyzer_prompt.txt").write_text("analyzer-v1\n", encoding="utf-8")
    (prompts_root / "tool_dispatch_prompt.txt").write_text("dispatch-v1\n", encoding="utf-8")
    (prompts_root / "agentic_tool_prompt.txt").write_text("tool-v1\n", encoding="utf-8")


def test_update_immutable_dna_manifest_success_and_verify_passes() -> None:
    case_root = _make_case_root("test_update_immutable_dna_manifest_ws23_003")
    try:
        prompts_root = case_root / "prompts"
        _write_prompt_files(prompts_root)

        report = run_update_immutable_dna_manifest(
            prompts_root=prompts_root,
            manifest_path=prompts_root / "immutable_dna_manifest.spec",
            audit_file=case_root / "audit.jsonl",
            output_file=case_root / "report.json",
            approval_ticket="CHG-TEST-001",
            verify_after_update=True,
        )
        assert report["passed"] is True
        assert report["reason"] == "ok"
        assert report["manifest_file_count"] == 4
        assert report["gate_report"]["passed"] is True
        payload = json.loads((prompts_root / "immutable_dna_manifest.spec").read_text(encoding="utf-8"))
        assert payload["schema_version"] == "ws18-006-v1"
    finally:
        _cleanup_case_root(case_root)


def test_update_immutable_dna_manifest_fails_when_ticket_missing() -> None:
    case_root = _make_case_root("test_update_immutable_dna_manifest_ws23_003")
    try:
        prompts_root = case_root / "prompts"
        _write_prompt_files(prompts_root)

        report = run_update_immutable_dna_manifest(
            prompts_root=prompts_root,
            manifest_path=prompts_root / "immutable_dna_manifest.spec",
            audit_file=case_root / "audit.jsonl",
            output_file=case_root / "report.json",
            approval_ticket="",
            approval_ticket_env="",
            verify_after_update=True,
        )
        assert report["passed"] is False
        assert report["reason"] == "missing_approval_ticket"
        assert not (prompts_root / "immutable_dna_manifest.spec").exists()
    finally:
        _cleanup_case_root(case_root)


def test_update_immutable_dna_manifest_can_skip_verify() -> None:
    case_root = _make_case_root("test_update_immutable_dna_manifest_ws23_003")
    try:
        prompts_root = case_root / "prompts"
        _write_prompt_files(prompts_root)

        report = run_update_immutable_dna_manifest(
            prompts_root=prompts_root,
            manifest_path=prompts_root / "immutable_dna_manifest.spec",
            audit_file=case_root / "audit.jsonl",
            output_file=case_root / "report.json",
            approval_ticket="CHG-TEST-002",
            verify_after_update=False,
        )
        assert report["passed"] is True
        assert report["reason"] == "manifest_updated_without_verify"
        assert "gate_report" not in report
    finally:
        _cleanup_case_root(case_root)
