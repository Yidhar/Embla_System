from __future__ import annotations

from system.subagent_contract import (
    build_contract_checksum,
    build_scaffold_fingerprint,
    validate_parallel_contract,
)


def test_build_contract_checksum_is_stable_for_schema_key_order() -> None:
    checksum_a = build_contract_checksum(
        "contract-demo",
        schema={"mode": "strict", "paths": ["a.py", "b.py"]},
    )
    checksum_b = build_contract_checksum(
        "contract-demo",
        schema={"paths": ["a.py", "b.py"], "mode": "strict"},
    )

    assert checksum_a == checksum_b


def test_build_scaffold_fingerprint_normalizes_and_deduplicates_paths() -> None:
    fp_a = build_scaffold_fingerprint("contract-demo", ["src\\main.py", "src/util.py", "src/main.py"])
    fp_b = build_scaffold_fingerprint("contract-demo", ["src/main.py", "src/util.py"])

    assert fp_a == fp_b


def test_validate_parallel_contract_requires_contract_id_for_parallel_paths() -> None:
    result = validate_parallel_contract(
        contract_id="",
        contract_checksum="",
        changed_paths=["a.py", "b.py"],
    )

    assert result.ok is False
    assert "require contract_id" in result.message


def test_validate_parallel_contract_rejects_checksum_mismatch() -> None:
    result = validate_parallel_contract(
        contract_id="contract-demo",
        contract_checksum="bad-checksum",
        changed_paths=["a.py", "b.py"],
    )

    assert result.ok is False
    assert "mismatch" in result.message
    assert result.expected_checksum
    assert result.normalized_contract_id == "contract-demo"


def test_validate_parallel_contract_returns_fingerprint_when_valid() -> None:
    changed_paths = ["b.py", "a.py"]
    checksum = build_contract_checksum("contract-demo", schema={"paths": sorted(changed_paths)})
    result = validate_parallel_contract(
        contract_id="contract-demo",
        contract_checksum=checksum,
        changed_paths=changed_paths,
    )

    assert result.ok is True
    assert result.expected_checksum == checksum
    assert result.normalized_contract_id == "contract-demo"
    assert bool(result.scaffold_fingerprint)

