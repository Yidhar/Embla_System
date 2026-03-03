from __future__ import annotations

from pathlib import Path

from scripts.check_legacy_shim_imports_ws28_030 import run_check_legacy_shim_imports_ws28_030


def test_runtime_scope_has_no_legacy_shim_imports() -> None:
    repo_root = Path(".").resolve()
    report = run_check_legacy_shim_imports_ws28_030(
        repo_root=repo_root,
        output_file=Path("scratch/reports/test_no_legacy_shim_imports_ws28_030.json"),
        include_tests=False,
    )
    assert report["passed"] is True
    assert int(report["hit_count"]) == 0


def test_checker_skips_tests_by_default_but_detects_when_enabled(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    (repo_root / "apiserver").mkdir(parents=True, exist_ok=True)
    (repo_root / "tests").mkdir(parents=True, exist_ok=True)

    (repo_root / "apiserver" / "safe.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo_root / "tests" / "test_legacy_import.py").write_text(
        "from system.global_mutex import GlobalMutexManager\n",
        encoding="utf-8",
    )

    runtime_report = run_check_legacy_shim_imports_ws28_030(
        repo_root=repo_root,
        output_file=repo_root / "scratch/reports/runtime_only.json",
        roots=["apiserver", "tests"],
        include_tests=False,
    )
    assert runtime_report["passed"] is True
    assert int(runtime_report["hit_count"]) == 0

    full_report = run_check_legacy_shim_imports_ws28_030(
        repo_root=repo_root,
        output_file=repo_root / "scratch/reports/include_tests.json",
        roots=["apiserver", "tests"],
        include_tests=True,
    )
    assert full_report["passed"] is False
    assert int(full_report["hit_count"]) == 1
    hit = full_report["hits"][0]
    assert hit["module"] == "system.global_mutex"
    assert hit["file_path"] == "tests/test_legacy_import.py"


def test_checker_flags_archived_autonomous_gateway_imports_when_tests_included(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    (repo_root / "tests").mkdir(parents=True, exist_ok=True)

    (repo_root / "tests" / "test_archived_import.py").write_text(
        "from autonomous.llm_gateway import LLMGateway\n"
        "from autonomous.router_arbiter_guard import RouterArbiterGuard\n",
        encoding="utf-8",
    )

    report = run_check_legacy_shim_imports_ws28_030(
        repo_root=repo_root,
        output_file=repo_root / "scratch/reports/include_tests_archived.json",
        roots=["tests"],
        include_tests=True,
    )
    assert report["passed"] is False
    assert int(report["hit_count"]) == 2
    modules = {str(hit.get("module") or "") for hit in report["hits"]}
    assert "autonomous.llm_gateway" in modules
    assert "autonomous.router_arbiter_guard" in modules
