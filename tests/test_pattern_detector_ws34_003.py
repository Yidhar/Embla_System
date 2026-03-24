"""WS34-003: Tests for pattern_detector + evolution_trigger."""
from pathlib import Path
from unittest.mock import MagicMock

from agents.evolution.pattern_detector import PatternDetector
from agents.evolution.evolution_trigger import EvolutionTrigger


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_exp(directory: Path, name: str, outcome: str, tags: list[str] | None = None, task_type: str = "") -> Path:
    """Write a minimal experience markdown file with frontmatter."""
    tag_str = "[" + ", ".join(tags) + "]" if tags else "[]"
    task_line = f"task_type: {task_type}\n" if task_type else ""
    content = (
        "---\n"
        f"outcome: {outcome}\n"
        f"tags: {tag_str}\n"
        f"{task_line}"
        "---\n"
        "# Experience\n"
        "body text\n"
    )
    filepath = directory / name
    filepath.write_text(content, encoding="utf-8")
    return filepath


# ---------------------------------------------------------------------------
# PatternDetector tests
# ---------------------------------------------------------------------------

def test_empty_episodic_dir_returns_no_signals(tmp_path: Path) -> None:
    ep_dir = tmp_path / "episodic"
    ep_dir.mkdir()
    detector = PatternDetector(episodic_dir=ep_dir, trigger_threshold=3)
    assert detector.check_recent() == []


def test_nonexistent_dir_returns_no_signals(tmp_path: Path) -> None:
    detector = PatternDetector(episodic_dir=tmp_path / "does_not_exist", trigger_threshold=3)
    assert detector.check_recent() == []


def test_single_failure_below_threshold_no_signal(tmp_path: Path) -> None:
    ep_dir = tmp_path / "episodic"
    ep_dir.mkdir()
    _write_exp(ep_dir, "exp_001.md", outcome="failure", tags=["backend"])
    detector = PatternDetector(episodic_dir=ep_dir, trigger_threshold=3)
    signals = detector.check_recent()
    assert signals == []


def test_three_failures_same_tag_triggers_signal(tmp_path: Path) -> None:
    ep_dir = tmp_path / "episodic"
    ep_dir.mkdir()
    _write_exp(ep_dir, "exp_001.md", outcome="failure", tags=["backend"])
    _write_exp(ep_dir, "exp_002.md", outcome="failure", tags=["backend"])
    _write_exp(ep_dir, "exp_003.md", outcome="failure", tags=["backend"])

    detector = PatternDetector(episodic_dir=ep_dir, trigger_threshold=3)
    signals = detector.check_recent()

    assert len(signals) == 1
    sig = signals[0]
    assert sig.trigger_type == "failure_pattern"
    assert sig.task_type == "backend"
    assert sig.failure_count == 3
    assert len(sig.sample_files) == 3
    assert sig.confidence > 0


def test_mixed_outcomes_only_failures_counted(tmp_path: Path) -> None:
    ep_dir = tmp_path / "episodic"
    ep_dir.mkdir()
    _write_exp(ep_dir, "exp_001.md", outcome="failure", tags=["ops"])
    _write_exp(ep_dir, "exp_002.md", outcome="success", tags=["ops"])
    _write_exp(ep_dir, "exp_003.md", outcome="failure", tags=["ops"])
    _write_exp(ep_dir, "exp_004.md", outcome="success", tags=["ops"])

    detector = PatternDetector(episodic_dir=ep_dir, trigger_threshold=3)
    signals = detector.check_recent()
    # Only 2 failures for "ops" — below threshold of 3
    assert signals == []


def test_frontmatter_parsing_with_tags(tmp_path: Path) -> None:
    ep_dir = tmp_path / "episodic"
    ep_dir.mkdir()
    content = (
        "---\n"
        "outcome: failure\n"
        "tags: [backend, testing]\n"
        "task_type: integration\n"
        "---\n"
        "# Title\n"
    )
    (ep_dir / "exp_010.md").write_text(content, encoding="utf-8")
    detector = PatternDetector(episodic_dir=ep_dir, trigger_threshold=1)
    signals = detector.check_recent()

    assert len(signals) == 1
    # cluster key should be sorted: "backend|testing"
    assert signals[0].task_type == "backend|testing"
    assert "roles/backend_expert.md" in signals[0].suggested_targets
    assert "roles/testing_expert.md" in signals[0].suggested_targets


def test_task_type_fallback_when_no_tags(tmp_path: Path) -> None:
    ep_dir = tmp_path / "episodic"
    ep_dir.mkdir()
    _write_exp(ep_dir, "exp_001.md", outcome="failure", tags=[], task_type="deployment")

    detector = PatternDetector(episodic_dir=ep_dir, trigger_threshold=1)
    signals = detector.check_recent()

    assert len(signals) == 1
    assert signals[0].task_type == "deployment"


def test_no_frontmatter_file_ignored(tmp_path: Path) -> None:
    ep_dir = tmp_path / "episodic"
    ep_dir.mkdir()
    # File without frontmatter
    (ep_dir / "exp_001.md").write_text("# Just a title\nSome content\n", encoding="utf-8")
    detector = PatternDetector(episodic_dir=ep_dir, trigger_threshold=1)
    assert detector.check_recent() == []


# ---------------------------------------------------------------------------
# EvolutionTrigger tests
# ---------------------------------------------------------------------------

def test_evolution_trigger_evaluate_with_signals(tmp_path: Path) -> None:
    ep_dir = tmp_path / "episodic"
    ep_dir.mkdir()
    _write_exp(ep_dir, "exp_001.md", outcome="failure", tags=["backend"])
    _write_exp(ep_dir, "exp_002.md", outcome="failure", tags=["backend"])
    _write_exp(ep_dir, "exp_003.md", outcome="failure", tags=["backend"])

    trigger = EvolutionTrigger(episodic_dir=ep_dir, trigger_threshold=3, max_per_day=5)
    decision = trigger.evaluate()

    assert decision.should_evolve is True
    assert len(decision.signals) >= 1
    assert "failure pattern" in decision.reason


def test_evolution_trigger_no_signals(tmp_path: Path) -> None:
    ep_dir = tmp_path / "episodic"
    ep_dir.mkdir()
    trigger = EvolutionTrigger(episodic_dir=ep_dir, trigger_threshold=3, max_per_day=5)
    decision = trigger.evaluate()

    assert decision.should_evolve is False
    assert "no failure patterns" in decision.reason


def test_evolution_trigger_daily_limit(tmp_path: Path) -> None:
    ep_dir = tmp_path / "episodic"
    ep_dir.mkdir()
    _write_exp(ep_dir, "exp_001.md", outcome="failure", tags=["backend"])
    _write_exp(ep_dir, "exp_002.md", outcome="failure", tags=["backend"])
    _write_exp(ep_dir, "exp_003.md", outcome="failure", tags=["backend"])

    trigger = EvolutionTrigger(episodic_dir=ep_dir, trigger_threshold=3, max_per_day=2)

    # First two evaluations should succeed
    d1 = trigger.evaluate()
    assert d1.should_evolve is True
    d2 = trigger.evaluate()
    assert d2.should_evolve is True

    # Third should hit the daily limit
    d3 = trigger.evaluate()
    assert d3.should_evolve is False
    assert "daily evolution limit" in d3.reason


def test_evolution_trigger_reset_daily_count(tmp_path: Path) -> None:
    ep_dir = tmp_path / "episodic"
    ep_dir.mkdir()
    _write_exp(ep_dir, "exp_001.md", outcome="failure", tags=["backend"])
    _write_exp(ep_dir, "exp_002.md", outcome="failure", tags=["backend"])
    _write_exp(ep_dir, "exp_003.md", outcome="failure", tags=["backend"])

    trigger = EvolutionTrigger(episodic_dir=ep_dir, trigger_threshold=3, max_per_day=1)
    d1 = trigger.evaluate()
    assert d1.should_evolve is True

    d2 = trigger.evaluate()
    assert d2.should_evolve is False

    trigger.reset_daily_count()
    d3 = trigger.evaluate()
    assert d3.should_evolve is True


def test_evolution_trigger_emits_event(tmp_path: Path) -> None:
    ep_dir = tmp_path / "episodic"
    ep_dir.mkdir()
    _write_exp(ep_dir, "exp_001.md", outcome="failure", tags=["backend"])
    _write_exp(ep_dir, "exp_002.md", outcome="failure", tags=["backend"])
    _write_exp(ep_dir, "exp_003.md", outcome="failure", tags=["backend"])

    mock_emitter = MagicMock()
    trigger = EvolutionTrigger(
        episodic_dir=ep_dir, trigger_threshold=3, max_per_day=5, event_emitter=mock_emitter
    )
    decision = trigger.evaluate()

    assert decision.should_evolve is True
    mock_emitter.emit.assert_called_once()
    call_args = mock_emitter.emit.call_args
    assert call_args[0][0] == "EvolutionTriggered"
    payload = call_args[0][1]
    assert payload["trigger_type"] == "failure_pattern"
    assert payload["task_type"] == "backend"
    assert payload["failure_count"] == 3


def test_evolution_trigger_event_emitter_exception_suppressed(tmp_path: Path) -> None:
    """Event emitter failure should not break evaluate()."""
    ep_dir = tmp_path / "episodic"
    ep_dir.mkdir()
    _write_exp(ep_dir, "exp_001.md", outcome="failure", tags=["backend"])
    _write_exp(ep_dir, "exp_002.md", outcome="failure", tags=["backend"])
    _write_exp(ep_dir, "exp_003.md", outcome="failure", tags=["backend"])

    mock_emitter = MagicMock()
    mock_emitter.emit.side_effect = RuntimeError("emit failed")
    trigger = EvolutionTrigger(
        episodic_dir=ep_dir, trigger_threshold=3, max_per_day=5, event_emitter=mock_emitter
    )
    decision = trigger.evaluate()
    # Should still return a valid decision despite emitter failure
    assert decision.should_evolve is True
