"""
Process lineage registry and reap helpers.

WS14-005/006:
- bind command execution to job_root_id + fencing_epoch
- provide best-effort process tree cleanup hooks
"""

from __future__ import annotations

import json
import os
import platform
import re
import signal
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence


@dataclass
class JobLineageRecord:
    job_root_id: str
    call_id: str
    command: str
    root_pid: int
    fencing_epoch: Optional[int]
    started_at: float
    ended_at: Optional[float] = None
    status: str = "running"
    return_code: Optional[int] = None
    reason: str = ""

    def to_dict(self) -> Dict[str, object]:
        return {
            "job_root_id": self.job_root_id,
            "call_id": self.call_id,
            "command": self.command,
            "root_pid": self.root_pid,
            "fencing_epoch": self.fencing_epoch,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "status": self.status,
            "return_code": self.return_code,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "JobLineageRecord":
        return cls(
            job_root_id=str(data.get("job_root_id") or ""),
            call_id=str(data.get("call_id") or ""),
            command=str(data.get("command") or ""),
            root_pid=int(data.get("root_pid") or 0),
            fencing_epoch=(int(data["fencing_epoch"]) if data.get("fencing_epoch") is not None else None),
            started_at=float(data.get("started_at") or 0.0),
            ended_at=(float(data["ended_at"]) if data.get("ended_at") is not None else None),
            status=str(data.get("status") or "running"),
            return_code=(int(data["return_code"]) if data.get("return_code") is not None else None),
            reason=str(data.get("reason") or ""),
        )


class ProcessLineageRegistry:
    PROJECT_ROOT = Path(__file__).resolve().parents[1]

    def __init__(self, state_file: Optional[Path] = None, audit_file: Optional[Path] = None) -> None:
        runtime_dir = self.PROJECT_ROOT / "logs" / "runtime"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = state_file or (runtime_dir / "process_lineage_state.json")
        self.audit_file = audit_file or (runtime_dir / "process_lineage_events.jsonl")
        self._lock = threading.RLock()
        self._records: Dict[str, JobLineageRecord] = {}
        self._load()

    def _load(self) -> None:
        with self._lock:
            if not self.state_file.exists():
                return
            try:
                payload = json.loads(self.state_file.read_text(encoding="utf-8"))
            except Exception:
                return
            if not isinstance(payload, dict):
                return
            for key, value in payload.items():
                if not isinstance(value, dict):
                    continue
                try:
                    self._records[str(key)] = JobLineageRecord.from_dict(value)
                except Exception:
                    continue

    def _save(self) -> None:
        with self._lock:
            payload = {k: v.to_dict() for k, v in self._records.items()}
            try:
                self.state_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass

    def _append_event(self, event: Dict[str, object]) -> None:
        record = {"ts": time.time(), **event}
        try:
            with self.audit_file.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            pass

    @staticmethod
    def _is_pid_alive(pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            if platform.system().lower().startswith("win"):
                result = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    encoding="utf-8",
                    errors="ignore",
                    check=False,
                )
                out = result.stdout or ""
                return str(pid) in out and "No tasks are running" not in out

            os.kill(pid, 0)
            return True
        except Exception:
            return False

    @staticmethod
    def _extract_signature_tokens(command: str) -> List[str]:
        """
        Build conservative signature tokens for detached-process cleanup.
        Only returns tokens for detached-launch style commands to reduce false positives.
        """
        text = (command or "").strip()
        if not text:
            return []
        lowered = text.lower()
        detached_markers = ("nohup", "setsid", "docker run -d", "docker run --detach", "start /b", "disown", "daemonize")
        if not any(m in lowered for m in detached_markers):
            return []

        # Keep meaningful executable-ish tokens and script paths.
        candidates = re.findall(r"[A-Za-z0-9_.:/\\-]+", text)
        stopwords = {
            "nohup",
            "setsid",
            "docker",
            "run",
            "-d",
            "start",
            "/b",
            "cmd",
            "/c",
            "bash",
            "sh",
            "powershell",
            "pwsh",
            "&",
            "&&",
            "|",
        }
        tokens: List[str] = []
        for item in candidates:
            token = item.strip().strip("'\"")
            if not token:
                continue
            if token.lower() in stopwords:
                continue
            if token.startswith("-"):
                continue
            if len(token) < 3:
                continue
            tokens.append(token)
            if len(tokens) >= 4:
                break
        return tokens

    def _list_process_rows(self) -> List[Dict[str, object]]:
        rows: List[Dict[str, object]] = []
        try:
            if platform.system().lower().startswith("win"):
                cmd = [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    (
                        "Get-CimInstance Win32_Process | "
                        "Select-Object ProcessId,ParentProcessId,CommandLine | "
                        "ConvertTo-Json -Depth 2 -Compress"
                    ),
                ]
                result = subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    encoding="utf-8",
                    errors="ignore",
                    check=False,
                )
                payload = (result.stdout or "").strip()
                if not payload:
                    return rows
                parsed = json.loads(payload)
                items = parsed if isinstance(parsed, list) else [parsed]
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    pid = int(item.get("ProcessId") or 0)
                    ppid = int(item.get("ParentProcessId") or 0)
                    cmdline = str(item.get("CommandLine") or "")
                    rows.append({"pid": pid, "ppid": ppid, "cmdline": cmdline})
                return rows

            result = subprocess.run(
                ["ps", "-eo", "pid=,ppid=,args="],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="ignore",
                check=False,
            )
            for line in (result.stdout or "").splitlines():
                parts = line.strip().split(None, 2)
                if len(parts) < 3:
                    continue
                pid = int(parts[0]) if parts[0].isdigit() else 0
                ppid = int(parts[1]) if parts[1].isdigit() else 0
                cmdline = parts[2]
                rows.append({"pid": pid, "ppid": ppid, "cmdline": cmdline})
        except Exception:
            return []
        return rows

    def _kill_by_signature(self, tokens: Sequence[str], *, exclude_pids: Optional[Sequence[int]] = None) -> int:
        """
        Best-effort fallback for detached/double-fork ghosts.
        Match all signature tokens in commandline, then force kill the pid tree.
        """
        normalized_tokens = [str(t).strip().lower() for t in tokens if str(t).strip()]
        if not normalized_tokens:
            return 0

        exclude = {int(x) for x in (exclude_pids or [])}
        killed = 0
        for row in self._list_process_rows():
            pid = int(row.get("pid") or 0)
            if pid <= 0 or pid in exclude:
                continue
            cmdline = str(row.get("cmdline") or "").lower()
            if not cmdline:
                continue
            if all(tok in cmdline for tok in normalized_tokens):
                if self._kill_pid_tree(pid):
                    killed += 1
        return killed

    def register_start(
        self,
        *,
        call_id: str,
        command: str,
        root_pid: int,
        fencing_epoch: Optional[int],
    ) -> str:
        with self._lock:
            job_root_id = f"job_{uuid.uuid4().hex[:16]}"
            record = JobLineageRecord(
                job_root_id=job_root_id,
                call_id=call_id or "",
                command=command or "",
                root_pid=int(root_pid),
                fencing_epoch=fencing_epoch,
                started_at=time.time(),
            )
            self._records[job_root_id] = record
            self._save()
            self._append_event(
                {
                    "event": "register_start",
                    "job_root_id": job_root_id,
                    "call_id": call_id,
                    "root_pid": int(root_pid),
                    "fencing_epoch": fencing_epoch,
                }
            )
            return job_root_id

    def register_end(
        self,
        job_root_id: str,
        *,
        return_code: Optional[int],
        status: str,
        reason: str = "",
    ) -> None:
        with self._lock:
            record = self._records.get(job_root_id)
            if record is None:
                return
            record.ended_at = time.time()
            record.return_code = return_code
            record.status = status
            record.reason = reason
            self._save()
            self._append_event(
                {
                    "event": "register_end",
                    "job_root_id": job_root_id,
                    "status": status,
                    "return_code": return_code,
                    "reason": reason,
                }
            )

    def list_running(self) -> List[JobLineageRecord]:
        with self._lock:
            return [v for v in self._records.values() if v.status == "running"]

    @staticmethod
    def _kill_pid_tree(pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            if platform.system().lower().startswith("win"):
                result = subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
                return result.returncode in (0, 128, 255)

            # POSIX fallback.
            try:
                os.killpg(pid, signal.SIGKILL)
                return True
            except Exception:
                os.kill(pid, signal.SIGKILL)
                return True
        except Exception:
            return False

    def kill_job(self, job_root_id: str, *, reason: str = "manual_reap") -> bool:
        with self._lock:
            record = self._records.get(job_root_id)
            if record is None:
                return False
            if record.status != "running":
                return False
            pid = int(record.root_pid)
            cmd = str(record.command or "")

        ok = self._kill_pid_tree(pid)
        signature_killed = 0
        tokens = self._extract_signature_tokens(cmd)
        # WS26-005: detached/double-fork ghosts may survive even when root pid was killed.
        # Always attempt conservative signature sweep for detached-launch commands.
        if tokens:
            signature_killed = self._kill_by_signature(tokens, exclude_pids=[pid])
            if not ok and signature_killed > 0:
                ok = True

        self.register_end(
            job_root_id,
            return_code=None,
            status="killed" if ok else "reap_failed",
            reason=f"{reason};signature_killed={signature_killed}" if signature_killed else reason,
        )
        return ok

    def reap_by_fencing_epoch(self, max_epoch: int) -> int:
        with self._lock:
            candidates = [
                r.job_root_id
                for r in self._records.values()
                if r.status == "running" and r.fencing_epoch is not None and int(r.fencing_epoch) <= int(max_epoch)
            ]
        killed = 0
        for job_root_id in candidates:
            if self.kill_job(job_root_id, reason=f"fencing_takeover<=epoch_{max_epoch}"):
                killed += 1
        killed += self.reap_orphaned_running_jobs(reason=f"fencing_orphan_scan<=epoch_{max_epoch}", max_epoch=max_epoch)
        return killed

    def reap_for_lock_scavenge(self, *, fencing_epoch: Optional[int], reason: str = "lock_scavenge") -> Dict[str, object]:
        """
        Unified entry used by lock scavenger:
        - if fencing epoch is available, reap by epoch (includes orphan scan <= epoch)
        - otherwise, only run orphan running-job scan.
        """
        epoch_value: Optional[int]
        try:
            epoch_value = int(fencing_epoch) if fencing_epoch is not None else None
        except Exception:
            epoch_value = None

        if epoch_value is not None and epoch_value > 0:
            reaped = int(self.reap_by_fencing_epoch(epoch_value))
            mode = "fencing_epoch"
        else:
            reaped = int(self.reap_orphaned_running_jobs(reason=f"{reason};orphan_only", max_epoch=None))
            mode = "orphan_running_jobs"

        self._append_event(
            {
                "event": "lock_scavenge_cleanup",
                "cleanup_mode": mode,
                "fencing_epoch": epoch_value,
                "reaped_count": reaped,
                "reason": reason,
            }
        )
        return {
            "cleanup_mode": mode,
            "fencing_epoch": epoch_value,
            "reaped_count": reaped,
            "reason": reason,
        }

    def reap_orphaned_running_jobs(self, *, reason: str = "orphan_scan", max_epoch: Optional[int] = None) -> int:
        """
        WS14-006: cleanup running records whose root pid disappeared, then perform
        conservative signature-based cleanup for detached children.
        """
        with self._lock:
            targets = [
                r
                for r in self._records.values()
                if r.status == "running"
                and not self._is_pid_alive(int(r.root_pid))
                and (max_epoch is None or (r.fencing_epoch is not None and int(r.fencing_epoch) <= int(max_epoch)))
            ]

        cleaned = 0
        for record in targets:
            tokens = self._extract_signature_tokens(record.command)
            signature_killed = self._kill_by_signature(tokens, exclude_pids=[int(record.root_pid)]) if tokens else 0
            self.register_end(
                record.job_root_id,
                return_code=None,
                status="killed" if signature_killed > 0 else "orphan_reaped",
                reason=f"{reason};signature_killed={signature_killed}",
            )
            cleaned += 1
            self._append_event(
                {
                    "event": "orphan_cleanup",
                    "job_root_id": record.job_root_id,
                    "root_pid": int(record.root_pid),
                    "signature_tokens": tokens,
                    "signature_killed": signature_killed,
                    "reason": reason,
                }
            )
        return cleaned


_process_lineage_registry: Optional[ProcessLineageRegistry] = None


def get_process_lineage_registry() -> ProcessLineageRegistry:
    global _process_lineage_registry
    if _process_lineage_registry is None:
        _process_lineage_registry = ProcessLineageRegistry()
    return _process_lineage_registry


__all__ = ["JobLineageRecord", "ProcessLineageRegistry", "get_process_lineage_registry"]
