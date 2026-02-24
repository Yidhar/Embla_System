"""Workspace large-file concurrency baseline for NGA-WS12-006."""

from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import json
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from apiserver.native_tools import NativeToolExecutor

TOTAL_LINES = 30_000
TARGET_LINE_INDEX = 14_999
WORKER_COUNT = 12
MAX_RETRIES = 2
TARGET_FILE = Path("scratch/tmp_workspace_concurrency_baseline_30k.txt")
REPORT_FILE = Path("scratch/reports/workspace_concurrency_baseline.json")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _replace_line(content: str, line_index: int, new_line: str) -> str:
    lines = content.splitlines(keepends=True)
    lines[line_index] = f"{new_line}\n"
    return "".join(lines)


def _extract_error_int(text: str, key: str) -> int:
    m = re.search(rf"{re.escape(key)}=(\d+)", text)
    return int(m.group(1)) if m is not None else 0


def _is_conflict_error(text: str) -> bool:
    lowered = text.lower()
    return "workspace transaction failed" in lowered and "conflict_ticket=" in lowered


def _run_workspace_apply(
    *,
    path: Path,
    content: str,
    base_content: str,
    base_hash: str,
    attempt: int,
    session_id: str,
) -> dict[str, Any]:
    executor = NativeToolExecutor()
    return asyncio.run(
        executor.execute(
            {
                "tool_name": "workspace_txn_apply",
                "changes": [
                    {
                        "path": str(path).replace("\\", "/"),
                        "content": content,
                        "mode": "overwrite",
                        "original_file_hash": base_hash,
                        "original_content": base_content,
                        "conflict_backoff": {
                            "base_ms": 20,
                            "max_ms": 120,
                            "attempt": attempt,
                            "jitter_ratio": 0.0,
                        },
                    }
                ],
            },
            session_id=session_id,
        )
    )


@dataclass
class WorkerResult:
    worker_id: int
    success: bool
    attempts: int
    retries: int
    conflicts: int
    backoff_ms: list[int] = field(default_factory=list)
    last_error: str = ""


def _run_worker(
    *,
    worker_id: int,
    target: Path,
    stale_base_content: str,
    stale_base_hash: str,
    start_barrier: threading.Barrier,
    retry_lock: threading.Lock,
) -> WorkerResult:
    attempts = 0
    retries = 0
    conflicts = 0
    backoffs: list[int] = []
    last_error = ""
    worker_marker = f"worker-{worker_id:02d}-line"

    start_barrier.wait(timeout=20)

    while attempts < (MAX_RETRIES + 1):
        attempts += 1

        if attempts == 1:
            base_content = stale_base_content
            base_hash = stale_base_hash
            desired_content = _replace_line(base_content, TARGET_LINE_INDEX, worker_marker)
            result = _run_workspace_apply(
                path=target,
                content=desired_content,
                base_content=base_content,
                base_hash=base_hash,
                attempt=attempts,
                session_id=f"sess-ws12-006-w{worker_id}-a{attempts}",
            )
        else:
            with retry_lock:
                base_content = target.read_text(encoding="utf-8")
                base_hash = _sha256(base_content)
                desired_content = _replace_line(base_content, TARGET_LINE_INDEX, worker_marker)
                result = _run_workspace_apply(
                    path=target,
                    content=desired_content,
                    base_content=base_content,
                    base_hash=base_hash,
                    attempt=attempts,
                    session_id=f"sess-ws12-006-w{worker_id}-a{attempts}",
                )

        if result.get("status") == "success":
            return WorkerResult(
                worker_id=worker_id,
                success=True,
                attempts=attempts,
                retries=retries,
                conflicts=conflicts,
                backoff_ms=backoffs,
            )

        last_error = str(result.get("result") or "")
        if _is_conflict_error(last_error):
            conflicts += 1
            backoff_value = _extract_error_int(last_error, "backoff_ms")
            if backoff_value > 0:
                backoffs.append(backoff_value)
            if attempts <= MAX_RETRIES:
                retries += 1
                continue
        break

    return WorkerResult(
        worker_id=worker_id,
        success=False,
        attempts=attempts,
        retries=retries,
        conflicts=conflicts,
        backoff_ms=backoffs,
        last_error=last_error,
    )


def test_workspace_concurrency_large_file_baseline_metrics():
    target = TARGET_FILE
    report = REPORT_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    report.parent.mkdir(parents=True, exist_ok=True)

    base_content = "".join(f"row-{i:05d}\n" for i in range(TOTAL_LINES))
    target.write_text(base_content, encoding="utf-8")
    stale_hash = _sha256(base_content)

    # Prime one commit so all worker first-attempt baselines are stale and conflict deterministically.
    primed_content = _replace_line(base_content, TARGET_LINE_INDEX, "primed-line")
    primed = _run_workspace_apply(
        path=target,
        content=primed_content,
        base_content=base_content,
        base_hash=stale_hash,
        attempt=1,
        session_id="sess-ws12-006-prime",
    )
    assert primed["status"] == "success"

    start_barrier = threading.Barrier(WORKER_COUNT)
    retry_lock = threading.Lock()

    started_at = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKER_COUNT) as pool:
        futures = [
            pool.submit(
                _run_worker,
                worker_id=worker_id,
                target=target,
                stale_base_content=base_content,
                stale_base_hash=stale_hash,
                start_barrier=start_barrier,
                retry_lock=retry_lock,
            )
            for worker_id in range(1, WORKER_COUNT + 1)
        ]
        results = [f.result(timeout=90) for f in futures]
    elapsed_ms = int((time.time() - started_at) * 1000)

    total_attempts = sum(item.attempts for item in results)
    total_retries = sum(item.retries for item in results)
    total_conflicts = sum(item.conflicts for item in results)
    successful_workers = sum(1 for item in results if item.success)
    all_backoffs = [ms for item in results for ms in item.backoff_ms]

    metrics = {
        "workers": WORKER_COUNT,
        "large_file_lines": TOTAL_LINES,
        "total_attempts": total_attempts,
        "retry_count": total_retries,
        "conflict_count": total_conflicts,
        "successful_workers": successful_workers,
        "success_rate": round(successful_workers / WORKER_COUNT, 4),
        "conflict_rate": round(total_conflicts / max(1, total_attempts), 4),
        "avg_backoff_ms": round(sum(all_backoffs) / max(1, len(all_backoffs)), 2),
        "max_backoff_ms": max(all_backoffs) if all_backoffs else 0,
        "elapsed_ms": elapsed_ms,
    }

    report_payload = {
        "task_id": "NGA-WS12-006",
        "scenario": "30k-lines-stale-baseline-concurrency",
        "metrics": metrics,
        "worker_results": [asdict(item) for item in results],
    }
    report.write_text(json.dumps(report_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    final_lines = target.read_text(encoding="utf-8").splitlines()
    assert len(final_lines) == TOTAL_LINES
    assert metrics["conflict_count"] >= WORKER_COUNT
    assert metrics["retry_count"] >= WORKER_COUNT
    assert metrics["successful_workers"] == WORKER_COUNT
    assert metrics["success_rate"] == 1.0
    assert metrics["avg_backoff_ms"] > 0
    assert report.exists()
