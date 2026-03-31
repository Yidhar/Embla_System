from __future__ import annotations

from system.gc_eval_suite import (
    DEFAULT_GC_QUALITY_THRESHOLDS,
    evaluate_gc_quality,
    validate_gc_quality_report,
)


def test_gc_quality_eval_meets_regression_thresholds() -> None:
    report = evaluate_gc_quality(iterations=3)
    violations = validate_gc_quality_report(report, DEFAULT_GC_QUALITY_THRESHOLDS)
    assert violations == [], f"GC quality regression threshold violated: {violations}"


def test_gc_quality_eval_accuracy_metrics_are_reproducible() -> None:
    first = evaluate_gc_quality(iterations=2)
    second = evaluate_gc_quality(iterations=2)

    assert first.sample_count == second.sample_count
    assert first.expected_total == second.expected_total
    assert first.matched_total == second.matched_total
    assert first.recall_overall == second.recall_overall
    assert first.recall_by_field == second.recall_by_field
    assert first.false_delete_rate == second.false_delete_rate


def test_gc_quality_eval_covers_gc_reader_bridge_and_memory_card_chain() -> None:
    report = evaluate_gc_quality(iterations=1)

    assert report.bridge_followup_rate == 1.0
    assert report.memory_card_rate == 1.0
    assert all(summary.get("bridge_call_mode") for summary in report.case_summaries)
    assert all(summary.get("memory_card_built") for summary in report.case_summaries)

