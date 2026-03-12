from __future__ import annotations

import asyncio
import shutil
import uuid
from pathlib import Path

import pytest

import apiserver.llm_service as llm_service_module
from core.security.immutable_dna import DNAFileSpec, ImmutableDNALoader


def _make_case_root(prefix: str) -> Path:
    root = Path("scratch") / prefix / uuid.uuid4().hex[:12]
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_case_root(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


_DNA_ENV_KEYS = (
    "EMBLA_IMMUTABLE_DNA_RUNTIME_INJECTION",
    "EMBLA_IMMUTABLE_DNA_PROMPTS_ROOT",
    "EMBLA_IMMUTABLE_DNA_MANIFEST_PATH",
    "EMBLA_IMMUTABLE_DNA_AUDIT_PATH",
)


@pytest.fixture(autouse=True)
def _isolate_immutable_dna_env(monkeypatch) -> None:
    for env_name in _DNA_ENV_KEYS:
        monkeypatch.delenv(env_name, raising=False)


def _write_required_prompts(root: Path) -> None:
    (root / "conversation_style_prompt.md").write_text("STYLE_PROMPT", encoding="utf-8")
    (root / "agentic_tool_prompt.md").write_text("AGENTIC_PROMPT", encoding="utf-8")
    (root / "shell_persona.md").write_text("SHELL_PERSONA_PROMPT", encoding="utf-8")
    (root / "core_values.md").write_text("CORE_VALUES_PROMPT", encoding="utf-8")


def _bootstrap_manifest(prompts_root: Path, manifest_path: Path, audit_path: Path) -> None:
    loader = ImmutableDNALoader(
        root_dir=prompts_root,
        dna_files=[
            DNAFileSpec(path="conversation_style_prompt.md", required=True),
            DNAFileSpec(path="agentic_tool_prompt.md", required=True),
            DNAFileSpec(path="shell_persona.md", required=True),
            DNAFileSpec(path="core_values.md", required=True),
        ],
        manifest_path=manifest_path,
        audit_file=audit_path,
    )
    loader.bootstrap_manifest()


def test_llm_service_injects_immutable_dna_runtime_prompt(monkeypatch) -> None:
    case_root = _make_case_root("test_llm_service_immutable_dna_runtime_injection")
    try:
        prompts_root = case_root / "prompts"
        prompts_root.mkdir(parents=True, exist_ok=True)
        manifest_path = prompts_root / "immutable_dna_manifest.spec"
        audit_path = case_root / "immutable_dna_runtime_injection_audit.jsonl"
        _write_required_prompts(prompts_root)
        _bootstrap_manifest(prompts_root, manifest_path, audit_path)

        monkeypatch.setenv(llm_service_module.LLMService.DNA_RUNTIME_ENABLED_ENV, "1")
        monkeypatch.setenv(llm_service_module.LLMService.DNA_PROMPTS_ROOT_ENV, str(prompts_root))
        monkeypatch.setenv(llm_service_module.LLMService.DNA_MANIFEST_PATH_ENV, str(manifest_path))
        monkeypatch.setenv(llm_service_module.LLMService.DNA_AUDIT_PATH_ENV, str(audit_path))

        captured_messages: dict[str, object] = {}

        async def _fake_completion(**kwargs):  # type: ignore[no-untyped-def]
            captured_messages["messages"] = kwargs.get("messages")

            class _Message:
                content = "ok"
                reasoning_content = None

            class _Choice:
                message = _Message()

            class _Response:
                choices = [_Choice()]

            return _Response()

        monkeypatch.setattr(llm_service_module, "acompletion", _fake_completion)
        service = llm_service_module.LLMService()
        response = asyncio.run(
            service.chat_with_context_and_reasoning_with_overrides(
                messages=[{"role": "user", "content": "hello"}],
                temperature=0.7,
                model_override="gpt-5.2",
                api_key_override="sk-test",
                api_base_override="https://api.openai.com/v1",
            )
        )

        assert response.content == "ok"
        prepared = captured_messages.get("messages")
        assert isinstance(prepared, list)
        assert prepared
        assert prepared[0]["role"] == "system"
        assert str(prepared[0]["content"]).startswith(llm_service_module.LLMService.DNA_RUNTIME_HEADER)
        assert "STYLE_PROMPT" in str(prepared[0]["content"])
        assert prepared[1]["role"] == "user"
    finally:
        _cleanup_case_root(case_root)


def test_llm_service_blocks_chat_when_immutable_dna_verification_fails(monkeypatch) -> None:
    case_root = _make_case_root("test_llm_service_immutable_dna_runtime_injection")
    try:
        prompts_root = case_root / "prompts"
        prompts_root.mkdir(parents=True, exist_ok=True)
        manifest_path = prompts_root / "immutable_dna_manifest.spec"
        audit_path = case_root / "immutable_dna_runtime_injection_audit.jsonl"
        _write_required_prompts(prompts_root)
        _bootstrap_manifest(prompts_root, manifest_path, audit_path)

        # Tamper after manifest bootstrap; runtime injection must fail closed.
        (prompts_root / "agentic_tool_prompt.md").write_text("AGENTIC_PROMPT_TAMPERED", encoding="utf-8")

        monkeypatch.setenv(llm_service_module.LLMService.DNA_RUNTIME_ENABLED_ENV, "1")
        monkeypatch.setenv(llm_service_module.LLMService.DNA_PROMPTS_ROOT_ENV, str(prompts_root))
        monkeypatch.setenv(llm_service_module.LLMService.DNA_MANIFEST_PATH_ENV, str(manifest_path))
        monkeypatch.setenv(llm_service_module.LLMService.DNA_AUDIT_PATH_ENV, str(audit_path))

        called = {"value": False}

        async def _fake_completion(**kwargs):  # type: ignore[no-untyped-def]
            called["value"] = True
            raise AssertionError("acompletion should not be called when DNA verification fails")

        monkeypatch.setattr(llm_service_module, "acompletion", _fake_completion)
        service = llm_service_module.LLMService()
        response = asyncio.run(
            service.chat_with_context_and_reasoning_with_overrides(
                messages=[{"role": "user", "content": "hello"}],
                temperature=0.7,
                model_override="gpt-5.2",
                api_key_override="sk-test",
                api_base_override="https://api.openai.com/v1",
            )
        )

        assert called["value"] is False
        assert str(response.content).startswith("Chat call blocked:")
        assert "dna_hash_mismatch" in str(response.content)
    finally:
        _cleanup_case_root(case_root)


def test_llm_service_immutable_dna_preflight_reports_pass(monkeypatch) -> None:
    case_root = _make_case_root("test_llm_service_immutable_dna_preflight")
    try:
        prompts_root = case_root / "prompts"
        prompts_root.mkdir(parents=True, exist_ok=True)
        manifest_path = prompts_root / "immutable_dna_manifest.spec"
        audit_path = case_root / "immutable_dna_runtime_injection_audit.jsonl"
        _write_required_prompts(prompts_root)
        _bootstrap_manifest(prompts_root, manifest_path, audit_path)

        monkeypatch.setenv(llm_service_module.LLMService.DNA_RUNTIME_ENABLED_ENV, "1")
        monkeypatch.setenv(llm_service_module.LLMService.DNA_PROMPTS_ROOT_ENV, str(prompts_root))
        monkeypatch.setenv(llm_service_module.LLMService.DNA_MANIFEST_PATH_ENV, str(manifest_path))
        monkeypatch.setenv(llm_service_module.LLMService.DNA_AUDIT_PATH_ENV, str(audit_path))

        service = llm_service_module.LLMService()
        report = service.immutable_dna_preflight()

        assert report["enabled"] is True
        assert report["passed"] is True
        assert report["reason"] == "ok"
        assert str(report.get("manifest_path") or "").endswith("immutable_dna_manifest.spec")
        verify = report.get("verify")
        assert isinstance(verify, dict)
        assert verify.get("ok") is True
        identity_verify = report.get("identity_verify")
        assert isinstance(identity_verify, dict)
        assert identity_verify.get("ok") is True
    finally:
        _cleanup_case_root(case_root)


def test_llm_service_immutable_dna_preflight_reports_failure_on_mismatch(monkeypatch) -> None:
    case_root = _make_case_root("test_llm_service_immutable_dna_preflight")
    try:
        prompts_root = case_root / "prompts"
        prompts_root.mkdir(parents=True, exist_ok=True)
        manifest_path = prompts_root / "immutable_dna_manifest.spec"
        audit_path = case_root / "immutable_dna_runtime_injection_audit.jsonl"
        _write_required_prompts(prompts_root)
        _bootstrap_manifest(prompts_root, manifest_path, audit_path)
        (prompts_root / "agentic_tool_prompt.md").write_text("AGENTIC_PROMPT_TAMPERED", encoding="utf-8")

        monkeypatch.setenv(llm_service_module.LLMService.DNA_RUNTIME_ENABLED_ENV, "1")
        monkeypatch.setenv(llm_service_module.LLMService.DNA_PROMPTS_ROOT_ENV, str(prompts_root))
        monkeypatch.setenv(llm_service_module.LLMService.DNA_MANIFEST_PATH_ENV, str(manifest_path))
        monkeypatch.setenv(llm_service_module.LLMService.DNA_AUDIT_PATH_ENV, str(audit_path))

        service = llm_service_module.LLMService()
        report = service.immutable_dna_preflight()

        assert report["enabled"] is True
        assert report["passed"] is False
        assert report["reason"] == "dna_hash_mismatch"
        verify = report.get("verify")
        assert isinstance(verify, dict)
        assert verify.get("ok") is False
        assert "agentic_tool_prompt.md" in list(verify.get("mismatch_files") or [])
    finally:
        _cleanup_case_root(case_root)


def test_llm_service_immutable_dna_preflight_reports_identity_failure_on_mismatch(monkeypatch) -> None:
    case_root = _make_case_root("test_llm_service_immutable_dna_preflight_identity")
    try:
        prompts_root = case_root / "prompts"
        prompts_root.mkdir(parents=True, exist_ok=True)
        manifest_path = prompts_root / "immutable_dna_manifest.spec"
        audit_path = case_root / "immutable_dna_runtime_injection_audit.jsonl"
        _write_required_prompts(prompts_root)
        _bootstrap_manifest(prompts_root, manifest_path, audit_path)
        (prompts_root / "core_values.md").write_text("CORE_VALUES_PROMPT_TAMPERED", encoding="utf-8")

        monkeypatch.setenv(llm_service_module.LLMService.DNA_RUNTIME_ENABLED_ENV, "1")
        monkeypatch.setenv(llm_service_module.LLMService.DNA_PROMPTS_ROOT_ENV, str(prompts_root))
        monkeypatch.setenv(llm_service_module.LLMService.DNA_MANIFEST_PATH_ENV, str(manifest_path))
        monkeypatch.setenv(llm_service_module.LLMService.DNA_AUDIT_PATH_ENV, str(audit_path))

        service = llm_service_module.LLMService()
        report = service.immutable_dna_preflight()

        assert report["enabled"] is True
        assert report["passed"] is False
        assert report["runtime_passed"] is True
        assert report["identity_passed"] is False
        identity_verify = report.get("identity_verify")
        assert isinstance(identity_verify, dict)
        assert "core_values.md" in list(identity_verify.get("mismatch_files") or [])
    finally:
        _cleanup_case_root(case_root)
