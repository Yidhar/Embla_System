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
        monkeypatch.setattr(
            full_chain,
            "run_release_closure_chain_m8_ws23_006",
            lambda **kwargs: {"passed": True, "group": "m8", "kwargs": kwargs},
        )
        monkeypatch.setattr(
            full_chain,
            "run_release_closure_chain_m9_ws24_006",
            lambda **kwargs: {"passed": True, "group": "m9", "kwargs": kwargs},
        )
        monkeypatch.setattr(
            full_chain,
            "run_release_closure_chain_m10_ws25_006",
            lambda **kwargs: {"passed": True, "group": "m10", "kwargs": kwargs},
        )
        monkeypatch.setattr(
            full_chain,
            "run_release_closure_chain_m11_ws26_006",
            lambda **kwargs: {"passed": True, "group": "m11", "kwargs": kwargs},
        )

        report = full_chain.run_release_closure_chain_full_m0_m7(
            repo_root=Path("."),
            output_file=case_root / "full.json",
            m0_m5_output_file=case_root / "m0.json",
            m6_m7_output_file=case_root / "m6.json",
            m8_output_file=case_root / "m8.json",
            m9_output_file=case_root / "m9.json",
            m10_output_file=case_root / "m10.json",
            m11_output_file=case_root / "m11.json",
        )
        assert report["passed"] is True
        assert report["failed_groups"] == []
        assert "m0_m5" in report["group_results"]
        assert "m6_m7" in report["group_results"]
        assert "m8" in report["group_results"]
        assert "m9" in report["group_results"]
        assert "m10" in report["group_results"]
        assert "m11" in report["group_results"]
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
        m8_called = {"value": False}
        m9_called = {"value": False}
        m10_called = {"value": False}
        m11_called = {"value": False}

        def _phase3_stub(**kwargs):
            phase3_called["value"] = True
            return {"passed": True}

        monkeypatch.setattr(full_chain, "run_phase3_release_closure_chain", _phase3_stub)
        
        def _m8_stub(**kwargs):
            m8_called["value"] = True
            return {"passed": True}

        monkeypatch.setattr(full_chain, "run_release_closure_chain_m8_ws23_006", _m8_stub)

        def _m9_stub(**kwargs):
            m9_called["value"] = True
            return {"passed": True}

        monkeypatch.setattr(full_chain, "run_release_closure_chain_m9_ws24_006", _m9_stub)

        def _m10_stub(**kwargs):
            m10_called["value"] = True
            return {"passed": True}

        monkeypatch.setattr(full_chain, "run_release_closure_chain_m10_ws25_006", _m10_stub)

        def _m11_stub(**kwargs):
            m11_called["value"] = True
            return {"passed": True}

        monkeypatch.setattr(full_chain, "run_release_closure_chain_m11_ws26_006", _m11_stub)

        report = full_chain.run_release_closure_chain_full_m0_m7(
            repo_root=Path("."),
            output_file=case_root / "full.json",
            m0_m5_output_file=case_root / "m0.json",
            m6_m7_output_file=case_root / "m6.json",
            m8_output_file=case_root / "m8.json",
            m9_output_file=case_root / "m9.json",
            m10_output_file=case_root / "m10.json",
            m11_output_file=case_root / "m11.json",
            continue_on_failure=False,
        )
        assert report["passed"] is False
        assert report["failed_groups"] == ["m0_m5"]
        assert "m6_m7" not in report["group_results"]
        assert "m8" not in report["group_results"]
        assert "m9" not in report["group_results"]
        assert "m10" not in report["group_results"]
        assert "m11" not in report["group_results"]
        assert phase3_called["value"] is False
        assert m8_called["value"] is False
        assert m9_called["value"] is False
        assert m10_called["value"] is False
        assert m11_called["value"] is False
    finally:
        _cleanup_case_root(case_root)


def test_full_release_chain_quick_mode_forwards_skip_flags(monkeypatch) -> None:
    case_root = _make_case_root("test_release_closure_chain_full_m0_m7")
    try:
        captured = {"m0": None, "m6": None, "m8": None, "m9": None, "m10": None, "m11": None}

        def _m0_stub(**kwargs):
            captured["m0"] = kwargs
            return {"passed": True}

        def _m6_stub(**kwargs):
            captured["m6"] = kwargs
            return {"passed": True}
        
        def _m8_stub(**kwargs):
            captured["m8"] = kwargs
            return {"passed": True}

        def _m9_stub(**kwargs):
            captured["m9"] = kwargs
            return {"passed": True}

        def _m10_stub(**kwargs):
            captured["m10"] = kwargs
            return {"passed": True}

        def _m11_stub(**kwargs):
            captured["m11"] = kwargs
            return {"passed": True}

        monkeypatch.setattr(full_chain, "run_release_closure_chain_m0_m5", _m0_stub)
        monkeypatch.setattr(full_chain, "run_phase3_release_closure_chain", _m6_stub)
        monkeypatch.setattr(full_chain, "run_release_closure_chain_m8_ws23_006", _m8_stub)
        monkeypatch.setattr(full_chain, "run_release_closure_chain_m9_ws24_006", _m9_stub)
        monkeypatch.setattr(full_chain, "run_release_closure_chain_m10_ws25_006", _m10_stub)
        monkeypatch.setattr(full_chain, "run_release_closure_chain_m11_ws26_006", _m11_stub)

        report = full_chain.run_release_closure_chain_full_m0_m7(
            repo_root=Path("."),
            output_file=case_root / "full.json",
            m0_m5_output_file=case_root / "m0.json",
            m6_m7_output_file=case_root / "m6.json",
            m8_output_file=case_root / "m8.json",
            m9_output_file=case_root / "m9.json",
            m10_output_file=case_root / "m10.json",
            m11_output_file=case_root / "m11.json",
            quick_mode=True,
        )
        assert report["passed"] is True
        assert captured["m0"]["skip_t1"] is True
        assert captured["m0"]["skip_t5"] is True
        assert captured["m6"]["skip_tests"] is True
        assert captured["m6"]["skip_longrun"] is True
        assert captured["m6"]["skip_gate"] is True
        assert captured["m8"]["skip_tests"] is True
        assert captured["m8"]["skip_runtime_checks"] is True
        assert captured["m8"]["skip_gate"] is True
        assert captured["m9"]["skip_tests"] is True
        assert captured["m9"]["skip_runtime_checks"] is True
        assert captured["m9"]["skip_gate"] is True
        assert captured["m10"]["skip_tests"] is True
        assert captured["m10"]["skip_runtime_checks"] is True
        assert captured["m10"]["skip_gate"] is True
        assert captured["m11"]["skip_tests"] is True
        assert captured["m11"]["skip_runtime_checks"] is True
        assert captured["m11"]["skip_gate"] is True
    finally:
        _cleanup_case_root(case_root)
