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


def _split_tokens(raw: str) -> List[str]:
    value = str(raw or "").strip()
    if not value:
        return []
    tokens = re.split(r"[|,;]", value)
    return [token.strip() for token in tokens if token.strip()]


def load_risk_verification_map(*, risk_ledger_file: Path) -> Dict[str, List[str]]:
    ledger_path = Path(risk_ledger_file)
    mapping: Dict[str, List[str]] = {}
    if not ledger_path.exists():
        return mapping

    content = ledger_path.read_text(encoding="utf-8")
    for line in content.splitlines():
        row = line.strip()
        if not row.startswith("| R"):
            continue
        columns = [part.strip() for part in row.strip("|").split("|")]
        if len(columns) < 5:
            continue
        risk_id = columns[0]
        verification_tasks = _split_tokens(columns[4])
        if risk_id and verification_tasks:
            mapping[risk_id] = verification_tasks
    return mapping


def validate_execution_board_consistency(
    *,
    board_file: Path,
    repo_root: Path,
    enforce_statuses: Sequence[str] = ("review", "done"),
    risk_ledger_file: Path | None = None,
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
    risk_map = (
        load_risk_verification_map(risk_ledger_file=risk_ledger_file)
        if risk_ledger_file is not None
        else {}
    )
    board_task_ids = {str(row.get("task_id") or "").strip() for row in rows if str(row.get("task_id") or "").strip()}
    issues: List[ConsistencyIssue] = []
    checked_rows = 0

    for row in rows:
        status = str(row.get("status") or "").strip().lower()
        if status not in statuses:
            continue
        checked_rows += 1
        task_id = str(row.get("task_id") or "").strip()
        risk_ids = _split_tokens(str(row.get("risk_ids") or ""))
        verify_for_risks = _split_tokens(str(row.get("verify_for_risks") or ""))
        if risk_ids and not verify_for_risks:
            issues.append(
                ConsistencyIssue(
                    task_id=task_id,
                    level="error",
                    field="verify_for_risks",
                    message="review/done task with risk_ids requires verify_for_risks",
                )
            )
        for verify_task in verify_for_risks:
            if verify_task not in board_task_ids:
                issues.append(
                    ConsistencyIssue(
                        task_id=task_id,
                        level="error",
                        field="verify_for_risks",
                        message="verify_for_risks task_id not found in execution board",
                        evidence_item=verify_task,
                    )
                )
        if risk_ids and risk_map:
            expected_verify_tasks: List[str] = []
            for risk_id in risk_ids:
                if risk_id in risk_map:
                    expected_verify_tasks.extend(risk_map[risk_id])
                else:
                    issues.append(
                        ConsistencyIssue(
                            task_id=task_id,
                            level="warn",
                            field="risk_ids",
                            message="risk_id not found in risk closure ledger",
                            evidence_item=risk_id,
                        )
                    )
            expected_set = set(expected_verify_tasks)
            missing_mapped_verify = sorted(expected_set.difference(verify_for_risks))
            if missing_mapped_verify:
                issues.append(
                    ConsistencyIssue(
                        task_id=task_id,
                        level="error",
                        field="verify_for_risks",
                        message=f"missing mapped verification task(s): {','.join(missing_mapped_verify)}",
                    )
                )

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
    "load_risk_verification_map",
    "validate_execution_board_consistency",
]
