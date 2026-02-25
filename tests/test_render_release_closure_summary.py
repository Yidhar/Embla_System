from __future__ import annotations

import shutil
import sys
import uuid
from pathlib import Path

import scripts.render_release_closure_summary as render_summary
from scripts.render_release_closure_summary import build_release_summary_markdown


def _make_case_root(prefix: str) -> Path:
    root = Path("scratch") / prefix / uuid.uuid4().hex[:12]
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_case_root(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


def test_build_release_summary_markdown_all_pass() -> None:
    case_root = _make_case_root("test_render_release_summary")
    try:
        full_report = {"passed": True, "failed_groups": []}
        m0_report = {"passed": True, "failed_steps": [], "step_results": []}
        m6_report = {"passed": True, "failed_steps": [], "step_results": []}
        m8_report = {"passed": True, "failed_steps": [], "step_results": []}
        m9_report = {"passed": True, "failed_steps": [], "step_results": []}

        markdown = build_release_summary_markdown(
            full_report=full_report,
            m0_m5_report=m0_report,
            m6_m7_report=m6_report,
            m8_report=m8_report,
            m9_report=m9_report,
            full_report_path=case_root / "full.json",
            m0_m5_report_path=case_root / "m0.json",
            m6_m7_report_path=case_root / "m6.json",
            m8_report_path=case_root / "m8.json",
            m9_report_path=case_root / "m9.json",
            load_errors={},
        )
        assert "Overall: **PASS**" in markdown
        assert "| `full_m0_m7` | `PASS` |" in markdown
        assert "| `m8` | `PASS` |" in markdown
        assert "| `m9` | `PASS` |" in markdown
        assert "Load issues:" not in markdown
    finally:
        _cleanup_case_root(case_root)


def test_build_release_summary_markdown_failed_steps_and_load_errors() -> None:
    case_root = _make_case_root("test_render_release_summary")
    try:
        full_report = {"passed": False, "failed_groups": ["m0_m5"]}
        m0_report = {
            "passed": False,
            "failed_steps": ["T2"],
            "step_results": [
                {
                    "step_id": "T2",
                    "description": "contract suite",
                    "return_code": 2,
                    "passed": False,
                    "stderr_tail": "assertion failed in contract validation",
                }
            ],
        }
        m6_report = {"passed": True, "failed_steps": [], "step_results": []}
        m8_report = {"passed": True, "failed_steps": [], "step_results": []}
        m9_report = {"passed": True, "failed_steps": [], "step_results": []}

        markdown = build_release_summary_markdown(
            full_report=full_report,
            m0_m5_report=m0_report,
            m6_m7_report=m6_report,
            m8_report=m8_report,
            m9_report=m9_report,
            full_report_path=case_root / "full.json",
            m0_m5_report_path=case_root / "m0.json",
            m6_m7_report_path=case_root / "m6.json",
            m8_report_path=case_root / "m8.json",
            m9_report_path=case_root / "m9.json",
            load_errors={"m6_m7": "report file not found", "m8": "report file not found", "m9": "report file not found"},
        )
        assert "Overall: **FAIL**" in markdown
        assert "Load issues:" in markdown
        assert "`m6_m7`: report file not found" in markdown
        assert "`m8`: report file not found" in markdown
        assert "`m9`: report file not found" in markdown
        assert "Failed steps:" in markdown
        assert "`m0_m5` `T2` rc=2 contract suite" in markdown
        assert "assertion failed in contract validation" in markdown
    finally:
        _cleanup_case_root(case_root)


def test_main_allows_missing_full_report(monkeypatch) -> None:
    case_root = _make_case_root("test_render_release_summary")
    try:
        output = case_root / "summary.md"
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "render_release_closure_summary.py",
                "--full-report",
                str(case_root / "missing_full.json"),
                "--m0-m5-report",
                str(case_root / "missing_m0.json"),
                "--m6-m7-report",
                str(case_root / "missing_m6.json"),
                "--m8-report",
                str(case_root / "missing_m8.json"),
                "--m9-report",
                str(case_root / "missing_m9.json"),
                "--output",
                str(output),
                "--allow-missing-full-report",
            ],
        )
        rc = render_summary.main()
        assert rc == 0
        assert output.exists()
        text = output.read_text(encoding="utf-8")
        assert "Overall: **UNKNOWN**" in text
    finally:
        _cleanup_case_root(case_root)
