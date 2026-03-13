from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from scripts.validate_immutable_dna_gate_ws23_003 import run_immutable_dna_gate
from system.config import resolve_prompt_file_reference


def _make_case_root(prefix: str) -> Path:
    root = Path("scratch") / prefix / uuid.uuid4().hex[:12]
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_case_root(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


_PROMPT_TEXT_BY_NAME = {
    "conversation_style_prompt": "style-v1\n",
    "conversation_analyzer_prompt": "analyzer-v1\n",
    "tool_dispatch_prompt": "dispatch-v1\n",
    "agentic_tool_prompt": "tool-v1\n",
    "shell_persona": "shell-v1\n",
    "core_values": "core-v1\n",
}


def _prompt_relative_path(prompts_root: Path, prompt_name: str) -> str:
    return resolve_prompt_file_reference(prompt_name=prompt_name, prompts_dir=prompts_root)


def _prompt_path(prompts_root: Path, prompt_name: str) -> Path:
    path = prompts_root / _prompt_relative_path(prompts_root, prompt_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _write_prompt_files(prompts_root: Path) -> None:
    prompts_root.mkdir(parents=True, exist_ok=True)
    for prompt_name, content in _PROMPT_TEXT_BY_NAME.items():
        _prompt_path(prompts_root, prompt_name).write_text(content, encoding="utf-8")


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
        _prompt_path(prompts_root, "agentic_tool_prompt").write_text("tool-v2-tampered\n", encoding="utf-8")

        report = run_immutable_dna_gate(
            prompts_root=prompts_root,
            manifest_path=prompts_root / "immutable_dna_manifest.spec",
            audit_file=case_root / "audit.jsonl",
            output_file=case_root / "report.json",
            bootstrap_if_missing=False,
        )
        assert report["passed"] is False
        assert report["reason"] == "dna_hash_mismatch"
        assert _prompt_relative_path(prompts_root, "agentic_tool_prompt") in report["verify"]["mismatch_files"]
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
