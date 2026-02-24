"""Workspace transaction e2e regression tests for NGA-WS13-006."""

from __future__ import annotations

import asyncio
from pathlib import Path

from apiserver.native_tools import NativeToolExecutor
from system.subagent_contract import build_contract_checksum, validate_parallel_contract


def _normalized_paths(paths: list[Path]) -> list[str]:
    return sorted(str(path).replace("\\", "/") for path in paths)


def _build_valid_contract(contract_id: str, paths: list[Path]) -> tuple[str, str]:
    normalized_paths = _normalized_paths(paths)
    checksum = build_contract_checksum(contract_id, schema={"paths": normalized_paths})
    validation = validate_parallel_contract(
        contract_id=contract_id,
        contract_checksum=checksum,
        changed_paths=normalized_paths,
    )
    assert validation.ok is True
    assert validation.expected_checksum == checksum
    return checksum, validation.scaffold_fingerprint


def _prepare_case_files(case_id: str, *, a_content: str = "A_BASE", b_content: str = "B_BASE") -> tuple[Path, Path]:
    a_path = Path(f"scratch/ws13_txn_e2e_{case_id}_a.txt")
    b_path = Path(f"scratch/ws13_txn_e2e_{case_id}_b.txt")
    a_path.parent.mkdir(parents=True, exist_ok=True)
    a_path.write_text(a_content, encoding="utf-8")
    b_path.write_text(b_content, encoding="utf-8")
    return a_path, b_path


def _run_workspace_txn_apply(
    executor: NativeToolExecutor,
    *,
    session_id: str,
    contract_id: str,
    contract_checksum: str,
    changes: list[dict[str, str]],
) -> dict:
    return asyncio.run(
        executor.execute(
            {
                "tool_name": "workspace_txn_apply",
                "contract_id": contract_id,
                "contract_checksum": contract_checksum,
                "changes": changes,
            },
            session_id=session_id,
        )
    )


def test_workspace_txn_apply_e2e_commits_multi_file_when_contract_consistent():
    executor = NativeToolExecutor()
    a_path, b_path = _prepare_case_files("contract_consistent")
    contract_id = "contract_ws13_e2e_consistent_001"
    contract_checksum, scaffold_fingerprint = _build_valid_contract(contract_id, [a_path, b_path])

    result = _run_workspace_txn_apply(
        executor,
        session_id="sess-ws13-e2e-contract-consistent",
        contract_id=contract_id,
        contract_checksum=contract_checksum,
        changes=[
            {"path": str(a_path).replace("\\", "/"), "content": "A_NEW", "mode": "overwrite"},
            {"path": str(b_path).replace("\\", "/"), "content": "B_NEW", "mode": "overwrite"},
        ],
    )

    assert result["status"] == "success"
    result_text = str(result["result"])
    result_text_lower = result_text.lower()
    assert "[committed] true" in result_text_lower
    assert f"[contract_id] {contract_id}" in result_text
    assert f"[contract_checksum] {contract_checksum}" in result_text
    assert f"[scaffold_fingerprint] {scaffold_fingerprint}" in result_text
    assert a_path.read_text(encoding="utf-8") == "A_NEW"
    assert b_path.read_text(encoding="utf-8") == "B_NEW"


def test_workspace_txn_apply_e2e_fail_fast_on_contract_checksum_mismatch_without_writes():
    executor = NativeToolExecutor()
    a_path, b_path = _prepare_case_files("contract_mismatch")
    contract_id = "contract_ws13_e2e_mismatch_001"
    wrong_checksum = build_contract_checksum(
        contract_id,
        schema={"paths": [str(a_path).replace("\\", "/")]},
    )

    preflight = validate_parallel_contract(
        contract_id=contract_id,
        contract_checksum=wrong_checksum,
        changed_paths=_normalized_paths([a_path, b_path]),
    )
    assert preflight.ok is False
    assert "contract_checksum mismatch" in preflight.message.lower()

    result = _run_workspace_txn_apply(
        executor,
        session_id="sess-ws13-e2e-contract-mismatch",
        contract_id=contract_id,
        contract_checksum=wrong_checksum,
        changes=[
            {"path": str(a_path).replace("\\", "/"), "content": "A_NEW", "mode": "overwrite"},
            {"path": str(b_path).replace("\\", "/"), "content": "B_NEW", "mode": "overwrite"},
        ],
    )

    assert result["status"] == "error"
    assert "contract gate blocked: contract_checksum mismatch" in str(result["result"]).lower()
    assert a_path.read_text(encoding="utf-8") == "A_BASE"
    assert b_path.read_text(encoding="utf-8") == "B_BASE"


def test_workspace_txn_apply_e2e_rolls_back_all_writes_when_second_file_change_fails():
    executor = NativeToolExecutor()
    a_path, b_path = _prepare_case_files("second_file_fail")
    contract_id = "contract_ws13_e2e_second_file_fail_001"
    contract_checksum, _ = _build_valid_contract(contract_id, [a_path, b_path])

    result = _run_workspace_txn_apply(
        executor,
        session_id="sess-ws13-e2e-second-file-fail",
        contract_id=contract_id,
        contract_checksum=contract_checksum,
        changes=[
            {"path": str(a_path).replace("\\", "/"), "content": "A_NEW", "mode": "overwrite"},
            {"path": str(b_path).replace("\\", "/"), "content": "B_NEW", "mode": "invalid_mode"},
        ],
    )

    assert result["status"] == "error"
    result_text = str(result["result"]).lower()
    assert "workspace transaction failed" in result_text
    assert "clean_state=true" in result_text
    assert "rolled_back_files=1" in result_text
    assert a_path.read_text(encoding="utf-8") == "A_BASE"
    assert b_path.read_text(encoding="utf-8") == "B_BASE"


def test_workspace_txn_apply_e2e_retry_succeeds_with_same_contract_after_rollback():
    executor = NativeToolExecutor()
    a_path, b_path = _prepare_case_files("retry_after_rollback")
    contract_id = "contract_ws13_e2e_retry_001"
    contract_checksum, _ = _build_valid_contract(contract_id, [a_path, b_path])

    failed = _run_workspace_txn_apply(
        executor,
        session_id="sess-ws13-e2e-retry-failed",
        contract_id=contract_id,
        contract_checksum=contract_checksum,
        changes=[
            {"path": str(a_path).replace("\\", "/"), "content": "A_NEW", "mode": "overwrite"},
            {"path": str(b_path).replace("\\", "/"), "content": "B_NEW", "mode": "invalid_mode"},
        ],
    )
    assert failed["status"] == "error"
    assert "clean_state=true" in str(failed["result"]).lower()
    assert a_path.read_text(encoding="utf-8") == "A_BASE"
    assert b_path.read_text(encoding="utf-8") == "B_BASE"

    retried = _run_workspace_txn_apply(
        executor,
        session_id="sess-ws13-e2e-retry-success",
        contract_id=contract_id,
        contract_checksum=contract_checksum,
        changes=[
            {"path": str(a_path).replace("\\", "/"), "content": "A_NEW", "mode": "overwrite"},
            {"path": str(b_path).replace("\\", "/"), "content": "B_NEW", "mode": "overwrite"},
        ],
    )

    assert retried["status"] == "success"
    retried_text = str(retried["result"]).lower()
    assert "[committed] true" in retried_text
    assert "[clean_state] true" in retried_text
    assert a_path.read_text(encoding="utf-8") == "A_NEW"
    assert b_path.read_text(encoding="utf-8") == "B_NEW"
