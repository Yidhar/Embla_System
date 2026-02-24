import shutil
import uuid
from pathlib import Path

from autonomous.scaffold_engine import ScaffoldEngine, ScaffoldPatch
from autonomous.scaffold_verify_pipeline import ScaffoldVerifyPipeline, VerifyStep
from system.subagent_contract import build_contract_checksum


def _make_case_root(prefix: str) -> Path:
    root = Path("scratch") / prefix / uuid.uuid4().hex[:12]
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_case_root(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


def test_scaffold_engine_contract_gate_fail_fast_without_file_pollution() -> None:
    case_root = _make_case_root("test_scaffold_engine")
    repo = case_root / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    a = repo / "a.txt"
    b = repo / "b.txt"
    a.write_text("A_BASE", encoding="utf-8")
    b.write_text("B_BASE", encoding="utf-8")

    engine = ScaffoldEngine(project_root=repo)
    result = engine.apply(
        patches=[
            ScaffoldPatch(path="a.txt", content="A_NEW"),
            ScaffoldPatch(path="b.txt", content="B_NEW"),
        ],
        contract_id="contract-demo",
        contract_checksum="bad-checksum",
    )

    try:
        assert result.committed is False
        assert result.gate == "contract"
        assert "contract_checksum mismatch" in result.error.lower()
        assert a.read_text(encoding="utf-8") == "A_BASE"
        assert b.read_text(encoding="utf-8") == "B_BASE"
    finally:
        _cleanup_case_root(case_root)


def test_scaffold_engine_verify_failure_rolls_back_and_returns_clean_state() -> None:
    case_root = _make_case_root("test_scaffold_engine")
    repo = case_root / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    a = repo / "a.txt"
    a.write_text("A_BASE", encoding="utf-8")

    pipeline = ScaffoldVerifyPipeline([VerifyStep(name="tests", fn=lambda ctx: (False, "tests failed"), severity="error")])
    engine = ScaffoldEngine(project_root=repo, verify_pipeline=pipeline)
    result = engine.apply(
        patches=[ScaffoldPatch(path="a.txt", content="A_NEW")],
    )

    try:
        assert result.committed is False
        assert result.gate == "scaffold"
        assert result.clean_state is True
        assert a.read_text(encoding="utf-8") == "A_BASE"
    finally:
        _cleanup_case_root(case_root)


def test_scaffold_engine_commits_with_contract_fingerprint() -> None:
    case_root = _make_case_root("test_scaffold_engine")
    repo = case_root / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    a = repo / "a.txt"
    b = repo / "b.txt"
    a.write_text("A_BASE", encoding="utf-8")
    b.write_text("B_BASE", encoding="utf-8")

    changed_paths = ["a.txt", "b.txt"]
    contract_id = "contract-demo"
    checksum = build_contract_checksum(contract_id, schema={"paths": changed_paths})

    engine = ScaffoldEngine(project_root=repo)
    result = engine.apply(
        patches=[
            ScaffoldPatch(path="a.txt", content="A_NEW"),
            ScaffoldPatch(path="b.txt", content="B_NEW"),
        ],
        contract_id=contract_id,
        contract_checksum=checksum,
    )

    try:
        assert result.committed is True
        assert result.contract_id == contract_id
        assert result.contract_checksum == checksum
        assert bool(result.scaffold_fingerprint)
        assert a.read_text(encoding="utf-8") == "A_NEW"
        assert b.read_text(encoding="utf-8") == "B_NEW"
    finally:
        _cleanup_case_root(case_root)
