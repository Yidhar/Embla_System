"""WS16-006 documentation consistency validator."""

from __future__ import annotations

import csv
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Sequence


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


_LINE_REF_RE = re.compile(r":\d+(?::\d+)?$")


@dataclass(frozen=True)
class ConsistencyIssue:
    task_id: str
    level: str  # error/warn
    field: str
    message: str
    evidence_item: str = ""
    normalized_path: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ConsistencyReport:
    generated_at: str
    board_file: str
    checked_rows: int
    issue_count: int
    error_count: int
    warn_count: int
    issues: List[Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _normalize_evidence_path(item: str) -> str:
    token = str(item or "").strip()
    if not token:
        return ""
    token = token.split("::", 1)[0].strip()
    token = token.split("#L", 1)[0].strip()
    if _LINE_REF_RE.search(token):
        token = _LINE_REF_RE.sub("", token).strip()
    return token


def validate_execution_board_consistency(
    *,
    board_file: Path,
    repo_root: Path,
    enforce_statuses: Sequence[str] = ("review", "done"),
) -> ConsistencyReport:
    board_path = Path(board_file)
    root = Path(repo_root)
    rows: List[Dict[str, Any]] = []
    with board_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if isinstance(row, dict):
                rows.append({str(k): str(v) for k, v in row.items()})

    statuses = {str(s).strip().lower() for s in enforce_statuses}
    issues: List[ConsistencyIssue] = []
    checked_rows = 0

    for row in rows:
        status = str(row.get("status") or "").strip().lower()
        if status not in statuses:
            continue
        checked_rows += 1
        task_id = str(row.get("task_id") or "").strip()
        evidence_link = str(row.get("evidence_link") or "").strip()
        if not evidence_link:
            issues.append(
                ConsistencyIssue(
                    task_id=task_id,
                    level="error",
                    field="evidence_link",
                    message="review/done task requires evidence_link",
                )
            )
            continue

        raw_items = [item.strip() for item in evidence_link.split(";") if item.strip()]
        if not raw_items:
            issues.append(
                ConsistencyIssue(
                    task_id=task_id,
                    level="error",
                    field="evidence_link",
                    message="evidence_link has no usable item",
                )
            )
            continue

        for item in raw_items:
            normalized = _normalize_evidence_path(item)
            if not normalized:
                issues.append(
                    ConsistencyIssue(
                        task_id=task_id,
                        level="warn",
                        field="evidence_link",
                        message="unable to parse evidence item path",
                        evidence_item=item,
                        normalized_path="",
                    )
                )
                continue
            if not (root / normalized).exists():
                issues.append(
                    ConsistencyIssue(
                        task_id=task_id,
                        level="error",
                        field="evidence_link",
                        message="evidence path does not exist",
                        evidence_item=item,
                        normalized_path=normalized,
                    )
                )

    error_count = sum(1 for issue in issues if issue.level == "error")
    warn_count = sum(1 for issue in issues if issue.level == "warn")
    return ConsistencyReport(
        generated_at=_utc_iso(),
        board_file=str(board_path),
        checked_rows=checked_rows,
        issue_count=len(issues),
        error_count=error_count,
        warn_count=warn_count,
        issues=[issue.to_dict() for issue in issues],
    )


__all__ = [
    "ConsistencyIssue",
    "ConsistencyReport",
    "validate_execution_board_consistency",
]
