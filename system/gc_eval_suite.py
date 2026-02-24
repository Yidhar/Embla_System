"""
GC quality evaluation suite and regression baseline.

NGA-WS15-006:
- Evaluate extraction quality on a deterministic synthetic dataset.
- Provide recall / false-delete / latency metrics for CI regression gates.
- Cover the reader-bridge and memory-card injection chain in the same pass.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path
from typing import Any, Mapping, Sequence

from system.gc_evidence_extractor import build_gc_fetch_hints, extract_gc_evidence
from system.gc_memory_card import build_gc_memory_index_card
from system.gc_reader_bridge import build_gc_reader_followup_plan

RECALL_FIELDS: tuple[str, ...] = ("trace_ids", "error_codes", "paths", "hex_addresses")
OPTIONAL_FIELDS: tuple[str, ...] = ("stack_tokens",)
ALL_FIELDS: tuple[str, ...] = RECALL_FIELDS + OPTIONAL_FIELDS
DEFAULT_ITERATIONS = 5


@dataclass(frozen=True)
class GCEvalCase:
    """One deterministic synthetic sample used for GC quality evaluation."""

    case_id: str
    content_type: str
    payload: str
    expected: Mapping[str, Sequence[str]]
    critical_expected: Mapping[str, Sequence[str]] = dataclass_field(default_factory=dict)


@dataclass(frozen=True)
class GCQualityThresholds:
    """Regression thresholds used by tests/CI."""

    min_recall: float = 0.85
    max_false_delete_rate: float = 0.15
    max_p95_latency_ms: float = 50.0

    def to_dict(self) -> dict[str, float]:
        return {
            "min_recall": self.min_recall,
            "max_false_delete_rate": self.max_false_delete_rate,
            "max_p95_latency_ms": self.max_p95_latency_ms,
        }


@dataclass(frozen=True)
class GCQualityReport:
    """Aggregated evaluation report."""

    sample_count: int
    iteration_count: int
    expected_total: int
    matched_total: int
    recall_overall: float
    recall_by_field: dict[str, float]
    false_delete_rate: float
    latency_avg_ms: float
    latency_p95_ms: float
    bridge_followup_rate: float
    memory_card_rate: float
    case_summaries: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_count": self.sample_count,
            "iteration_count": self.iteration_count,
            "expected_total": self.expected_total,
            "matched_total": self.matched_total,
            "recall_overall": self.recall_overall,
            "recall_by_field": dict(self.recall_by_field),
            "false_delete_rate": self.false_delete_rate,
            "latency_avg_ms": self.latency_avg_ms,
            "latency_p95_ms": self.latency_p95_ms,
            "bridge_followup_rate": self.bridge_followup_rate,
            "memory_card_rate": self.memory_card_rate,
            "case_summaries": list(self.case_summaries),
        }


DEFAULT_GC_QUALITY_THRESHOLDS = GCQualityThresholds()


def default_gc_eval_cases() -> list[GCEvalCase]:
    """Return deterministic text+JSON synthetic cases for quality evaluation."""
    json_case_3 = json.dumps(
        {
            "trace_id": "trace-json-003",
            "error_code": "ERR_CACHE_MISS",
            "file_path": "/opt/app/cache.py",
            "memory_address": "0xDEADBEEF",
            "stack": "at CacheService.reload (/opt/app/cache.py:77:9)",
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    json_case_4 = json.dumps(
        {
            "meta": {"traceId": "trace-nested-004"},
            "status_code": 504,
            "event": {"path": "/srv/mod/main.go", "address": "FEEDBEEF"},
            "stack": 'File "/srv/mod/main.go", line 21, in run_loop',
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    json_case_6 = json.dumps(
        [
            {
                "trace": "trace-array-006",
                "errorCode": "ERR_NET_RESET",
                "source_path": "/var/log/naga/net.log",
                "ptr": "0xFFEEAA11",
            }
        ],
        ensure_ascii=False,
        sort_keys=True,
    )

    return [
        GCEvalCase(
            case_id="text_basic_001",
            content_type="text/plain",
            payload="\n".join(
                [
                    "2026-02-24 ERROR trace_id=trace_case_001 error_code=ERR_DB_TIMEOUT",
                    "at app.worker.handle",
                    "/srv/app/worker.py",
                    "addr=7FFDF0A12010",
                ]
            ),
            expected={
                "trace_ids": ["trace_case_001"],
                "error_codes": ["ERR_DB_TIMEOUT"],
                "stack_tokens": ["app.worker.handle"],
                "paths": ["/srv/app/worker.py"],
                "hex_addresses": ["0x7ffdf0a12010"],
            },
        ),
        GCEvalCase(
            case_id="text_windows_002",
            content_type="text/plain",
            payload=r"panic trace-triage-002 HTTP 503 C:\ProgramData\Naga\logs\agent.log ptr=0xABCDEF12",
            expected={
                "trace_ids": ["trace-triage-002"],
                "error_codes": ["503"],
                "paths": [r"C:\ProgramData\Naga\logs\agent.log"],
                "hex_addresses": ["0xabcdef12"],
            },
        ),
        GCEvalCase(
            case_id="json_flat_003",
            content_type="application/json",
            payload=json_case_3,
            expected={
                "trace_ids": ["trace-json-003"],
                "error_codes": ["ERR_CACHE_MISS"],
                "stack_tokens": ["CacheService.reload"],
                "paths": ["/opt/app/cache.py"],
                "hex_addresses": ["0xdeadbeef"],
            },
        ),
        GCEvalCase(
            case_id="json_nested_004",
            content_type="application/json",
            payload=json_case_4,
            expected={
                "trace_ids": ["trace-nested-004"],
                "error_codes": ["504"],
                "stack_tokens": ["run_loop"],
                "paths": ["/srv/mod/main.go"],
                "hex_addresses": ["0xfeedbeef"],
            },
        ),
        GCEvalCase(
            case_id="text_linux_005",
            content_type="text/plain",
            payload="\n".join(
                [
                    "ERR_IO_FAIL trace_id=trace_case_005",
                    "at pkg.module.func",
                    "/tmp/run/job.log",
                    "RIP=7fffff11aa22",
                ]
            ),
            expected={
                "trace_ids": ["trace_case_005"],
                "error_codes": ["ERR_IO_FAIL"],
                "stack_tokens": ["pkg.module.func"],
                "paths": ["/tmp/run/job.log"],
                "hex_addresses": ["0x7fffff11aa22"],
            },
        ),
        GCEvalCase(
            case_id="json_array_006",
            content_type="application/json",
            payload=json_case_6,
            expected={
                "trace_ids": ["trace-array-006"],
                "error_codes": ["ERR_NET_RESET"],
                "paths": ["/var/log/naga/net.log"],
                "hex_addresses": ["0xffeeaa11"],
            },
        ),
    ]


def _normalize_values(values: Sequence[str]) -> set[str]:
    normalized: set[str] = set()
    for value in values:
        text = str(value).strip().lower()
        if text:
            normalized.add(text)
    return normalized


def _normalize_field_map(source: Mapping[str, Sequence[str]]) -> dict[str, set[str]]:
    return {field: _normalize_values(source.get(field, ())) for field in ALL_FIELDS}


def _resolve_critical_map(case: GCEvalCase) -> dict[str, set[str]]:
    if case.critical_expected:
        source = case.critical_expected
    else:
        source = {field: case.expected.get(field, ()) for field in RECALL_FIELDS}
    return {field: _normalize_values(source.get(field, ())) for field in RECALL_FIELDS}


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = int(math.ceil((percentile / 100.0) * len(ordered)) - 1)
    index = min(max(rank, 0), len(ordered) - 1)
    return ordered[index]


def _round(value: float) -> float:
    return round(float(value), 6)


def _build_synthetic_result(case_id: str, hints: Sequence[str]) -> dict[str, Any]:
    artifact_ref = f"artifact_eval_{case_id}"
    hint_text = ", ".join(hints) if hints else "(none)"
    tagged_result = "\n".join(
        [
            "[truncated] true",
            f"[forensic_artifact_ref] {artifact_ref}",
            f"[raw_result_ref] {artifact_ref}",
            f"[fetch_hints] {hint_text}",
            "[display_preview]",
            "Synthetic preview for GC evaluation.",
        ]
    )
    return {
        "service_name": "native",
        "tool_name": "run_cmd",
        "status": "success",
        "forensic_artifact_ref": artifact_ref,
        "raw_result_ref": artifact_ref,
        "fetch_hints": list(hints),
        "result": tagged_result,
    }


def evaluate_gc_quality(
    *,
    cases: Sequence[GCEvalCase] | None = None,
    iterations: int = DEFAULT_ITERATIONS,
) -> GCQualityReport:
    """
    Run deterministic GC quality evaluation and return aggregated report.

    The recall/false-delete metrics are computed on one deterministic pass.
    Latency metrics are sampled across `iterations` runs for stability.
    """
    if iterations <= 0:
        raise ValueError("iterations must be >= 1")

    selected_cases = list(cases) if cases is not None else default_gc_eval_cases()
    if not selected_cases:
        raise ValueError("at least one evaluation case is required")

    field_expected = {field: 0 for field in RECALL_FIELDS}
    field_hits = {field: 0 for field in RECALL_FIELDS}
    critical_expected_total = 0
    critical_missing_total = 0
    latency_samples: list[float] = []
    bridge_followups = 0
    bridge_attempts = 0
    memory_cards = 0
    memory_card_attempts = 0
    case_summaries: list[dict[str, Any]] = []

    for pass_idx in range(iterations):
        for case in selected_cases:
            started = time.perf_counter_ns()
            evidence = extract_gc_evidence(case.payload, content_type=case.content_type)
            hints = build_gc_fetch_hints(evidence, content_type=case.content_type)
            synthetic_result = _build_synthetic_result(case.case_id, hints)
            plan = build_gc_reader_followup_plan([synthetic_result], round_num=1, max_calls_per_round=1)
            memory_card = build_gc_memory_index_card(synthetic_result, index=1, total=1)
            elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000.0
            latency_samples.append(elapsed_ms)

            bridge_attempts += 1
            memory_card_attempts += 1
            if plan.call is not None:
                bridge_followups += 1
            if memory_card:
                memory_cards += 1

            if pass_idx != 0:
                continue

            expected_map = _normalize_field_map(case.expected)
            actual_map = _normalize_field_map(evidence.to_dict())
            critical_map = _resolve_critical_map(case)

            missing_expected: dict[str, list[str]] = {}
            matched_count = 0
            expected_count = 0
            for field in ALL_FIELDS:
                expected_tokens = expected_map[field]
                actual_tokens = actual_map[field]
                if not expected_tokens:
                    continue
                matched = expected_tokens & actual_tokens
                missing = sorted(expected_tokens - actual_tokens)
                matched_count += len(matched)
                expected_count += len(expected_tokens)
                if missing:
                    missing_expected[field] = missing

                if field in RECALL_FIELDS:
                    field_expected[field] += len(expected_tokens)
                    field_hits[field] += len(matched)

            for field in RECALL_FIELDS:
                expected_tokens = critical_map[field]
                if not expected_tokens:
                    continue
                actual_tokens = actual_map[field]
                critical_expected_total += len(expected_tokens)
                critical_missing_total += len(expected_tokens - actual_tokens)

            case_summaries.append(
                {
                    "case_id": case.case_id,
                    "content_type": case.content_type,
                    "expected_count": expected_count,
                    "matched_count": matched_count,
                    "missing_expected": missing_expected,
                    "hint_count": len(hints),
                    "bridge_call_mode": (plan.call or {}).get("mode"),
                    "memory_card_built": bool(memory_card),
                }
            )

    expected_total = sum(field_expected.values())
    matched_total = sum(field_hits.values())
    recall_by_field = {
        field: _round((field_hits[field] / field_expected[field]) if field_expected[field] else 1.0)
        for field in RECALL_FIELDS
    }
    recall_overall = _round((matched_total / expected_total) if expected_total else 1.0)
    false_delete_rate = _round((critical_missing_total / critical_expected_total) if critical_expected_total else 0.0)
    latency_avg_ms = _round(sum(latency_samples) / len(latency_samples)) if latency_samples else 0.0
    latency_p95_ms = _round(_percentile(latency_samples, 95.0))
    bridge_followup_rate = _round((bridge_followups / bridge_attempts) if bridge_attempts else 0.0)
    memory_card_rate = _round((memory_cards / memory_card_attempts) if memory_card_attempts else 0.0)

    return GCQualityReport(
        sample_count=len(selected_cases),
        iteration_count=iterations,
        expected_total=expected_total,
        matched_total=matched_total,
        recall_overall=recall_overall,
        recall_by_field=recall_by_field,
        false_delete_rate=false_delete_rate,
        latency_avg_ms=latency_avg_ms,
        latency_p95_ms=latency_p95_ms,
        bridge_followup_rate=bridge_followup_rate,
        memory_card_rate=memory_card_rate,
        case_summaries=case_summaries,
    )


def validate_gc_quality_report(
    report: GCQualityReport,
    thresholds: GCQualityThresholds = DEFAULT_GC_QUALITY_THRESHOLDS,
) -> list[str]:
    """Return threshold violations; empty list means pass."""
    violations: list[str] = []
    if report.recall_overall < thresholds.min_recall:
        violations.append(
            f"recall_overall={report.recall_overall:.6f} < min_recall={thresholds.min_recall:.6f}"
        )
    if report.false_delete_rate > thresholds.max_false_delete_rate:
        violations.append(
            "false_delete_rate="
            f"{report.false_delete_rate:.6f} > max_false_delete_rate={thresholds.max_false_delete_rate:.6f}"
        )
    if report.latency_p95_ms > thresholds.max_p95_latency_ms:
        violations.append(
            f"latency_p95_ms={report.latency_p95_ms:.6f} > max_p95_latency_ms={thresholds.max_p95_latency_ms:.6f}"
        )
    return violations


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run GC quality evaluation suite.")
    parser.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS, help="Latency sampling passes.")
    parser.add_argument("--output", type=str, default="", help="Optional JSON output path.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with code 1 if threshold checks fail.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    report = evaluate_gc_quality(iterations=args.iterations)
    violations = validate_gc_quality_report(report, DEFAULT_GC_QUALITY_THRESHOLDS)

    payload = report.to_dict()
    payload["thresholds"] = DEFAULT_GC_QUALITY_THRESHOLDS.to_dict()
    payload["threshold_violations"] = violations

    json_text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json_text, encoding="utf-8")
    print(json_text)
    return 1 if args.strict and violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
