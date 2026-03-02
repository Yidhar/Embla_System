from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from typing import Any, Dict, List

from core.security import DNAFileSpec, ImmutableDNAIntegrityMonitor, ImmutableDNALoader


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


class _CaptureEmitter:
    def __init__(self) -> None:
        self.events: List[Dict[str, Any]] = []

    def emit(
        self,
        event_type: str,
        payload: Dict[str, Any],
        *,
        source: str | None = None,
        severity: str | None = None,
        idempotency_key: str | None = None,
    ) -> None:
        self.events.append(
            {
                "event_type": event_type,
                "payload": dict(payload or {}),
                "source": source,
                "severity": severity,
                "idempotency_key": idempotency_key,
            }
        )


def test_immutable_dna_loader_supports_encrypted_manifest_loading() -> None:
    case_root = _make_case_root("test_core_immutable_dna_monitor_ws30_001")
    try:
        _write_prompts(case_root)
        loader = ImmutableDNALoader(
            root_dir=case_root,
            dna_files=[
                DNAFileSpec(path="conversation_style_prompt.md"),
                DNAFileSpec(path="conversation_analyzer_prompt.md"),
                DNAFileSpec(path="tool_dispatch_prompt.md"),
                DNAFileSpec(path="agentic_tool_prompt.md"),
            ],
            manifest_path=case_root / "immutable_dna_manifest.spec",
            audit_file=case_root / "immutable_dna_audit.jsonl",
            encryption_key="base64:QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo0NTY3ODkwMTI=",
            encrypt_manifest_on_bootstrap=True,
        )
        loader.bootstrap_manifest()
        raw_manifest = (case_root / "immutable_dna_manifest.spec").read_text(encoding="utf-8")
        assert raw_manifest.startswith(ImmutableDNALoader.ENCRYPTED_PREFIX)

        verify = loader.verify()
        assert verify.ok is True
        injected = loader.inject()
        assert "STYLE_PROMPT" in str(injected.get("dna_text") or "")
    finally:
        _cleanup_case_root(case_root)


def test_immutable_dna_integrity_monitor_emits_tamper_event() -> None:
    case_root = _make_case_root("test_core_immutable_dna_monitor_ws30_001")
    try:
        _write_prompts(case_root)
        loader = ImmutableDNALoader(
            root_dir=case_root,
            manifest_path=case_root / "immutable_dna_manifest.spec",
            audit_file=case_root / "immutable_dna_audit.jsonl",
        )
        loader.bootstrap_manifest()
        emitter = _CaptureEmitter()
        monitor = ImmutableDNAIntegrityMonitor(
            loader=loader,
            event_emitter=emitter,
            state_file=case_root / "immutable_dna_integrity_state.json",
            interval_seconds=5.0,
        )

        first = monitor.run_once()
        assert first["status"] == "ok"
        assert first["tamper_detected"] is False

        (case_root / "agentic_tool_prompt.md").write_text("AGENTIC_PROMPT_TAMPERED", encoding="utf-8")
        second = monitor.run_once()
        assert second["status"] == "critical"
        assert second["tamper_detected"] is True
        assert second["reason_code"] == "IMMUTABLE_DNA_TAMPER_DETECTED"

        tamper_events = [item for item in emitter.events if item.get("event_type") == "ImmutableDNATamperDetected"]
        assert tamper_events
        state_payload = json.loads((case_root / "immutable_dna_integrity_state.json").read_text(encoding="utf-8"))
        assert state_payload["tamper_detected"] is True
    finally:
        _cleanup_case_root(case_root)
