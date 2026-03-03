"""Tests for Phase 3.5 — Memory Utility Agents."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from agents.memory.memory_agents import (
    CompressionReport,
    ConvertedExperience,
    DistillationResult,
    ExperienceDistiller,
    FormatConverter,
    LogScrubber,
    MemoryCompressor,
    ScrubResult,
    run_post_task_pipeline,
)


# ── LogScrubber ────────────────────────────────────────────────


RAW_LOG_WITH_NOISE = (
    "\x1b[32mStarting test...\x1b[0m\n"
    "Running check 1... OK\n"
    "Running check 2... OK\n"
    "Running check 2... OK\n"
    "Running check 2... OK\n"
    "Running check 2... OK\n"
    "Running check 2... OK\n"
    "\n\n\n\n\n"
    "Error: file not found: config.yaml\n"
    "Fixed: created default config.yaml\n"
    "Test passed: 42 assertions   \n"
)


class TestLogScrubber:

    def test_strips_ansi_codes(self) -> None:
        scrubber = LogScrubber()
        result = scrubber.scrub("\x1b[31mERROR\x1b[0m: something broke")
        assert "\x1b[" not in result.cleaned_text
        assert "ERROR" in result.cleaned_text

    def test_collapses_blank_lines(self) -> None:
        scrubber = LogScrubber()
        result = scrubber.scrub("line1\n\n\n\n\nline2")
        assert result.cleaned_text.count("\n") <= 3

    def test_deduplicates_lines(self) -> None:
        scrubber = LogScrubber(max_repeat_lines=2)
        result = scrubber.scrub("same\nsame\nsame\nsame\nsame")
        assert "×" in result.cleaned_text
        assert result.cleaned_text.count("same") <= 3

    def test_truncates_long_output(self) -> None:
        scrubber = LogScrubber(max_output_chars=100)
        long_text = "x" * 500
        result = scrubber.scrub(long_text)
        assert len(result.cleaned_text) < 200  # truncated + marker
        assert "截断" in result.cleaned_text

    def test_noise_ratio(self) -> None:
        scrubber = LogScrubber()
        result = scrubber.scrub(RAW_LOG_WITH_NOISE)
        assert 0.0 <= result.noise_ratio <= 1.0
        assert result.original_length > result.cleaned_length

    def test_heuristic_summary(self) -> None:
        scrubber = LogScrubber()
        result = scrubber.scrub(RAW_LOG_WITH_NOISE)
        assert len(result.summary) > 0
        # Should capture key events
        assert any(kw in result.summary.lower() for kw in ("error", "fixed", "passed"))

    def test_custom_summarizer(self) -> None:
        def mock_summarizer(text: str) -> str:
            return "MOCK SUMMARY"

        scrubber = LogScrubber(summarizer=mock_summarizer)
        result = scrubber.scrub("some log output")
        assert result.summary == "MOCK SUMMARY"

    def test_summarizer_failure_fallback(self) -> None:
        def broken_summarizer(text: str) -> str:
            raise RuntimeError("LLM down")

        scrubber = LogScrubber(summarizer=broken_summarizer)
        result = scrubber.scrub("Error: something")
        assert len(result.summary) > 0  # Fell back to heuristic

    def test_strips_trailing_whitespace(self) -> None:
        scrubber = LogScrubber()
        result = scrubber.scrub("line with spaces   \nclean line")
        assert "   " not in result.cleaned_text

    def test_empty_input(self) -> None:
        scrubber = LogScrubber()
        result = scrubber.scrub("")
        assert result.cleaned_text == ""
        assert result.original_length == 0


# ── FormatConverter ────────────────────────────────────────────


class TestFormatConverter:

    def test_from_scrub_result(self) -> None:
        scrub = ScrubResult(
            cleaned_text="Error: missing config\nFixed: added default",
            summary="Config fix",
            original_length=100,
            cleaned_length=50,
            noise_ratio=0.5,
        )
        converter = FormatConverter()
        exp = converter.from_scrub_result(
            scrub, name="config_fix", task_id="t-001", outcome="success"
        )
        assert exp.name == "config_fix"
        assert exp.task_id == "t-001"
        assert exp.outcome == "success"
        assert "Config Fix" in exp.title

    def test_from_jsonl_record(self) -> None:
        record = {
            "record_id": "r-001",
            "session_id": "s-001",
            "source_tool": "file_write",
            "narrative_summary": "Refactored pipeline module",
            "fetch_hints": ["agents/pipeline.py", "refactor"],
        }
        converter = FormatConverter()
        exp = converter.from_jsonl_record(record)
        assert "pipeline" in exp.name.lower()
        assert exp.task_id == "r-001"
        assert "agents/pipeline.py" in exp.files

    def test_from_raw_text(self) -> None:
        converter = FormatConverter()
        exp = converter.from_raw_text(
            "Fixed bug in `agents/shell_agent.py` config handling",
            name="shell_config_fix",
            task_id="t-002",
            tags=["fix", "shell"],
        )
        assert exp.name == "shell_config_fix"
        assert "agents/shell_agent.py" in exp.files
        assert "fix" in exp.tags

    def test_extracts_files_from_backticks(self) -> None:
        converter = FormatConverter()
        exp = converter.from_raw_text(
            "Modified `core/engine.py` and `tests/test_engine.py`",
            name="engine_update", task_id="t-003",
        )
        assert "core/engine.py" in exp.files
        assert "tests/test_engine.py" in exp.files

    def test_derive_name_english(self) -> None:
        converter = FormatConverter()
        name = converter._derive_name("Refactored pipeline module handlers")
        assert "refactored" in name

    def test_derive_name_cjk(self) -> None:
        converter = FormatConverter()
        name = converter._derive_name("修复了管线处理逻辑")
        assert len(name) > 0


# ── MemoryCompressor ───────────────────────────────────────────


def _create_experience(episodic_dir: Path, name: str, tag: str, date: str) -> Path:
    filepath = episodic_dir / f"exp_{date}_{name}.md"
    filepath.write_text(
        f"# 经验：{name}\n\ntags: #{tag}\ntask: t-{name}\noutcome: success\n\n"
        f"## 问题\nSome problem with {name}.\n\n"
        f"## 解决方案\nFixed {name} issue.\n",
        encoding="utf-8",
    )
    return filepath


class TestMemoryCompressor:

    def test_should_compress_below_threshold(self, tmp_path: Path) -> None:
        episodic = tmp_path / "episodic"
        episodic.mkdir()
        for i in range(3):
            _create_experience(episodic, f"test_{i}", "test", "20260101")

        compressor = MemoryCompressor(episodic, file_count_threshold=50)
        assert not compressor.should_compress()

    def test_should_compress_above_threshold(self, tmp_path: Path) -> None:
        episodic = tmp_path / "episodic"
        episodic.mkdir()
        for i in range(55):
            _create_experience(episodic, f"test_{i}", "test", "20260101")

        compressor = MemoryCompressor(episodic, file_count_threshold=50)
        assert compressor.should_compress()

    def test_compress_old_files(self, tmp_path: Path) -> None:
        episodic = tmp_path / "episodic"
        episodic.mkdir()
        # Create old files (date in the past)
        for i in range(5):
            _create_experience(episodic, f"old_{i}", "api", "20250101")
        # Create fresh files
        _create_experience(episodic, "fresh_0", "api", "20261231")

        compressor = MemoryCompressor(episodic, max_age_days=7)
        report = compressor.compress()

        assert report.files_compressed >= 1
        assert report.files_archived >= 2  # At least 2 old files archived
        assert (episodic / "_archive").exists()

    def test_compress_empty_dir(self, tmp_path: Path) -> None:
        compressor = MemoryCompressor(tmp_path / "nonexistent")
        report = compressor.compress()
        assert report.files_scanned == 0

    def test_compression_ratio(self, tmp_path: Path) -> None:
        episodic = tmp_path / "episodic"
        episodic.mkdir()
        for i in range(10):
            _create_experience(episodic, f"ratio_{i}", "deploy", "20250101")

        compressor = MemoryCompressor(episodic, max_age_days=1)
        report = compressor.compress()
        assert 0.0 <= report.compression_ratio <= 1.0


# ── ExperienceDistiller ───────────────────────────────────────


class TestExperienceDistiller:

    def test_should_distill_below_threshold(self, tmp_path: Path) -> None:
        episodic = tmp_path / "episodic"
        episodic.mkdir()
        for i in range(2):
            _create_experience(episodic, f"few_{i}", "pipeline", "20260303")

        distiller = ExperienceDistiller(episodic, tmp_path / "domain", min_experiences=5)
        assert not distiller.should_distill("pipeline")

    def test_should_distill_above_threshold(self, tmp_path: Path) -> None:
        episodic = tmp_path / "episodic"
        episodic.mkdir()
        for i in range(6):
            _create_experience(episodic, f"many_{i}", "refactor", "20260303")

        distiller = ExperienceDistiller(episodic, tmp_path / "domain", min_experiences=5)
        assert distiller.should_distill("refactor")

    def test_distill_creates_domain_file(self, tmp_path: Path) -> None:
        episodic = tmp_path / "episodic"
        domain = tmp_path / "domain"
        episodic.mkdir()
        for i in range(6):
            _create_experience(episodic, f"dist_{i}", "api", "20260303")

        distiller = ExperienceDistiller(episodic, domain, min_experiences=5)
        result = distiller.distill("api")

        assert result.tag == "api"
        assert result.source_count == 6
        assert result.domain_file is not None
        assert result.domain_file.exists()
        content = result.domain_file.read_text(encoding="utf-8")
        assert "api" in content

    def test_distill_insufficient_experiences(self, tmp_path: Path) -> None:
        episodic = tmp_path / "episodic"
        episodic.mkdir()
        _create_experience(episodic, "lonely", "rare", "20260303")

        distiller = ExperienceDistiller(episodic, tmp_path / "domain", min_experiences=5)
        result = distiller.distill("rare")
        assert result.domain_file is None

    def test_scan_all_tags(self, tmp_path: Path) -> None:
        episodic = tmp_path / "episodic"
        episodic.mkdir()
        for i in range(6):
            _create_experience(episodic, f"scan_a_{i}", "backend", "20260303")
        for i in range(3):
            _create_experience(episodic, f"scan_b_{i}", "frontend", "20260303")

        distiller = ExperienceDistiller(episodic, tmp_path / "domain", min_experiences=5)
        tags = distiller.scan_all_tags()
        assert "backend" in tags
        assert "frontend" not in tags  # Only 3, below threshold

    def test_custom_distill_fn(self, tmp_path: Path) -> None:
        episodic = tmp_path / "episodic"
        domain = tmp_path / "domain"
        episodic.mkdir()
        for i in range(5):
            _create_experience(episodic, f"llm_{i}", "ops", "20260303")

        def mock_distill(text: str) -> str:
            return "Patterns:\n- Pattern from LLM\nRules:\n- Rule from LLM\n"

        distiller = ExperienceDistiller(
            episodic, domain, min_experiences=5, distill_fn=mock_distill
        )
        result = distiller.distill("ops")
        assert "Pattern from LLM" in result.patterns
        assert "Rule from LLM" in result.rules


# ── Pipeline Integration ───────────────────────────────────────


class TestPostTaskPipeline:

    def test_full_pipeline(self) -> None:
        exp = run_post_task_pipeline(
            RAW_LOG_WITH_NOISE,
            name="pipeline_test",
            task_id="t-pipe-001",
            outcome="success",
            tags=["test", "pipeline"],
        )
        assert exp.name == "pipeline_test"
        assert exp.task_id == "t-pipe-001"
        assert exp.outcome == "success"
        assert exp.title == "Pipeline Test"
        assert "test" in exp.tags
        assert "pipeline" in exp.tags

    def test_pipeline_with_custom_scrubber(self) -> None:
        scrubber = LogScrubber(max_output_chars=50)
        exp = run_post_task_pipeline(
            "x" * 200,
            name="truncated_test",
            task_id="t-trunc",
            scrubber=scrubber,
        )
        assert exp.name == "truncated_test"

    def test_pipeline_extracts_files(self) -> None:
        log = "Modified `agents/pipeline.py` and `tests/test_pipe.py`\nAll tests passed."
        exp = run_post_task_pipeline(
            log,
            name="file_extraction_test",
            task_id="t-files",
            files=["agents/pipeline.py"],
        )
        assert "agents/pipeline.py" in exp.files
