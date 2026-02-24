"""WS18-007 DNA change audit and approval ledger."""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty_state(change_id: str) -> Dict[str, Any]:
    return {
        "change_id": change_id,
        "file_path": "",
        "requested_by": "",
        "request_ticket": "",
        "requested_at": "",
        "old_hash": "",
        "new_hash": "",
        "status": "unknown",
        "approved_by": "",
        "approval_ticket": "",
        "approved_at": "",
        "rejected_by": "",
        "rejection_ticket": "",
        "rejected_at": "",
        "applied_by": "",
        "applied_at": "",
        "notes": "",
    }


def _require_non_empty(value: str, *, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    return text


@dataclass(frozen=True)
class DNAChangeSummary:
    change_id: str
    file_path: str
    requested_by: str
    request_ticket: str
    requested_at: str
    old_hash: str
    new_hash: str
    status: str
    approved_by: str = ""
    approval_ticket: str = ""
    approved_at: str = ""
    rejected_by: str = ""
    rejection_ticket: str = ""
    rejected_at: str = ""
    applied_by: str = ""
    applied_at: str = ""
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class DNAChangeAuditLedger:
    """Append-only audit ledger for DNA approval workflow."""

    def __init__(self, *, ledger_file: Path) -> None:
        self.ledger_file = Path(ledger_file)
        self.ledger_file.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def request_change(
        self,
        *,
        file_path: str,
        old_hash: str,
        new_hash: str,
        requested_by: str,
        request_ticket: str,
        notes: str = "",
    ) -> str:
        requested_by_text = _require_non_empty(requested_by, field_name="requested_by")
        request_ticket_text = _require_non_empty(request_ticket, field_name="request_ticket")
        change_id = f"dna_change_{uuid.uuid4().hex[:12]}"
        event = {
            "ts": _utc_iso(),
            "event": "change_requested",
            "change_id": change_id,
            "file_path": str(file_path),
            "old_hash": str(old_hash),
            "new_hash": str(new_hash),
            "requested_by": requested_by_text,
            "request_ticket": request_ticket_text,
            "notes": str(notes),
        }
        self._append(event)
        return change_id

    def approve_change(self, *, change_id: str, approved_by: str, approval_ticket: str, notes: str = "") -> None:
        change_id_text = _require_non_empty(change_id, field_name="change_id")
        approved_by_text = _require_non_empty(approved_by, field_name="approved_by")
        approval_ticket_text = _require_non_empty(approval_ticket, field_name="approval_ticket")

        state = self._load_states().get(change_id_text)
        if state is None:
            raise ValueError(f"change_id not found: {change_id_text}")
        if state["status"] != "pending":
            raise ValueError(f"change_id {change_id_text} is not pending and cannot be approved")

        event = {
            "ts": _utc_iso(),
            "event": "change_approved",
            "change_id": change_id_text,
            "approved_by": approved_by_text,
            "approval_ticket": approval_ticket_text,
            "notes": str(notes),
        }
        self._append(event)

    def reject_change(self, *, change_id: str, rejected_by: str, rejection_ticket: str, notes: str = "") -> None:
        change_id_text = _require_non_empty(change_id, field_name="change_id")
        rejected_by_text = _require_non_empty(rejected_by, field_name="rejected_by")
        rejection_ticket_text = _require_non_empty(rejection_ticket, field_name="rejection_ticket")

        state = self._load_states().get(change_id_text)
        if state is None:
            raise ValueError(f"change_id not found: {change_id_text}")
        if state["status"] != "pending":
            raise ValueError(f"change_id {change_id_text} is not pending and cannot be rejected")

        event = {
            "ts": _utc_iso(),
            "event": "change_rejected",
            "change_id": change_id_text,
            "rejected_by": rejected_by_text,
            "rejection_ticket": rejection_ticket_text,
            "notes": str(notes),
        }
        self._append(event)

    def mark_applied(self, *, change_id: str, applied_by: str, notes: str = "") -> None:
        change_id_text = _require_non_empty(change_id, field_name="change_id")
        applied_by_text = _require_non_empty(applied_by, field_name="applied_by")

        state = self._load_states().get(change_id_text)
        if state is None:
            raise ValueError(f"change_id not found: {change_id_text}")
        if state["status"] != "approved":
            raise ValueError(f"change_id {change_id_text} is not approved and cannot be applied")

        event = {
            "ts": _utc_iso(),
            "event": "change_applied",
            "change_id": change_id_text,
            "applied_by": applied_by_text,
            "notes": str(notes),
        }
        self._append(event)

    def list_events(self) -> List[Dict[str, Any]]:
        if not self.ledger_file.exists():
            return []
        rows: List[Dict[str, Any]] = []
        for line in self.ledger_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                rows.append(payload)
        return rows

    def build_tracking_report(self) -> Dict[str, Any]:
        states = self._load_states()
        summaries = [DNAChangeSummary(**state).to_dict() for state in states.values()]
        summaries.sort(key=lambda item: item["requested_at"])
        by_status: Dict[str, int] = {}
        for item in summaries:
            by_status[item["status"]] = by_status.get(item["status"], 0) + 1

        return {
            "generated_at": _utc_iso(),
            "total_changes": len(summaries),
            "by_status": by_status,
            "changes": summaries,
        }

    def write_tracking_report(self, *, output_file: Path) -> Path:
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        report = self.build_tracking_report()
        output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return output_path

    def _load_states(self) -> Dict[str, Dict[str, Any]]:
        states: Dict[str, Dict[str, Any]] = {}
        events = self.list_events()
        for event in events:
            change_id = str(event.get("change_id") or "").strip()
            if not change_id:
                continue
            state = states.setdefault(change_id, _empty_state(change_id))
            event_name = str(event.get("event") or "")
            ts = str(event.get("ts") or "")
            if event_name == "change_requested":
                state["file_path"] = str(event.get("file_path") or "")
                state["requested_by"] = str(event.get("requested_by") or "")
                state["request_ticket"] = str(event.get("request_ticket") or "")
                state["requested_at"] = ts
                state["old_hash"] = str(event.get("old_hash") or "")
                state["new_hash"] = str(event.get("new_hash") or "")
                state["status"] = "pending"
                state["notes"] = str(event.get("notes") or "")
            elif event_name == "change_approved":
                state["approved_by"] = str(event.get("approved_by") or "")
                state["approval_ticket"] = str(event.get("approval_ticket") or "")
                state["approved_at"] = ts
                state["status"] = "approved"
                state["notes"] = str(event.get("notes") or state.get("notes") or "")
            elif event_name == "change_rejected":
                state["rejected_by"] = str(event.get("rejected_by") or "")
                state["rejection_ticket"] = str(event.get("rejection_ticket") or "")
                state["rejected_at"] = ts
                state["status"] = "rejected"
                state["notes"] = str(event.get("notes") or state.get("notes") or "")
            elif event_name == "change_applied":
                state["applied_by"] = str(event.get("applied_by") or "")
                state["applied_at"] = ts
                state["status"] = "applied"
                state["notes"] = str(event.get("notes") or state.get("notes") or "")
        return states

    def _append(self, payload: Dict[str, Any]) -> None:
        line = json.dumps(payload, ensure_ascii=False)
        with self._lock:
            with self.ledger_file.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
