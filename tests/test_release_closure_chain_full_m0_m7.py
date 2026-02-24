from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import scripts.release_closure_chain_full_m0_m7 as full_chain


def _make_case_root(prefix: str) -> Path:
    root = Path("scratch") / prefix / uuid.uuid4().hex[:12]
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_case_root(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


def test_full_release_chain_runs_both_groups_when_green(monkeypatch) -> None:
    case_root = _make_case_root("test_release_closure_chain_full_m0_m7")
    try:
        monkeypatch.setattr(
            full_chain,
            "run_release_closure_chain_m0_m5",
            lambda **kwargs: {"passed": True, "group": "m0_m5", "kwargs": kwargs},
        )
        monkeypatch.setattr(
            full_chain,
            "run_phase3_release_closure_chain",
            lambda **kwargs: {"passed": True, "group": "m6_m7", "kwargs": kwargs},
        )

        report = full_chain.run_release_closure_chain_full_m0_m7(
            repo_root=Path("."),
            output_file=case_root / "full.json",
            m0_m5_output_file=case_root / "m0.json",
            m6_m7_output_file=case_root / "m6.json",
        )
        assert report["passed"] is True
        assert report["failed_groups"] == []
        assert "m0_m5" in report["group_results"]
        assert "m6_m7" in report["group_results"]
    finally:
        _cleanup_case_root(case_root)


def test_full_release_chain_stops_after_m0_m5_failure_by_default(monkeypatch) -> None:
    case_root = _make_case_root("test_release_closure_chain_full_m0_m7")
    try:
        monkeypatch.setattr(
            full_chain,
            "run_release_closure_chain_m0_m5",
            lambda **kwargs: {"passed": False, "failed_steps": ["T2"]},
        )
        phase3_called = {"value": False}

        def _phase3_stub(**kwargs):
            phase3_called["value"] = True
            return {"passed": True}

        monkeypatch.setattr(full_chain, "run_phase3_release_closure_chain", _phase3_stub)

        report = full_chain.run_release_closure_chain_full_m0_m7(
            repo_root=Path("."),
            output_file=case_root / "full.json",
            m0_m5_output_file=case_root / "m0.json",
            m6_m7_output_file=case_root / "m6.json",
            continue_on_failure=False,
        )
        assert report["passed"] is False
        assert report["failed_groups"] == ["m0_m5"]
        assert "m6_m7" not in report["group_results"]
        assert phase3_called["value"] is False
    finally:
        _cleanup_case_root(case_root)


def test_full_release_chain_quick_mode_forwards_skip_flags(monkeypatch) -> None:
    case_root = _make_case_root("test_release_closure_chain_full_m0_m7")
    try:
        captured = {"m0": None, "m6": None}

        def _m0_stub(**kwargs):
            captured["m0"] = kwargs
            return {"passed": True}

        def _m6_stub(**kwargs):
            captured["m6"] = kwargs
            return {"passed": True}

        monkeypatch.setattr(full_chain, "run_release_closure_chain_m0_m5", _m0_stub)
        monkeypatch.setattr(full_chain, "run_phase3_release_closure_chain", _m6_stub)

        report = full_chain.run_release_closure_chain_full_m0_m7(
            repo_root=Path("."),
            output_file=case_root / "full.json",
            m0_m5_output_file=case_root / "m0.json",
            m6_m7_output_file=case_root / "m6.json",
            quick_mode=True,
        )
        assert report["passed"] is True
        assert captured["m0"]["skip_t1"] is True
        assert captured["m0"]["skip_t5"] is True
        assert captured["m6"]["skip_tests"] is True
        assert captured["m6"]["skip_longrun"] is True
    finally:
        _cleanup_case_root(case_root)
