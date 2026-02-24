"""WS18-008 brainstem supervisor (service supervision + self-recovery templates)."""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


Launcher = Callable[["BrainstemServiceSpec"], int]


@dataclass(frozen=True)
class BrainstemServiceSpec:
    service_name: str
    command: List[str]
    working_dir: str = ""
    env: Dict[str, str] | None = None
    restart_policy: str = "on-failure"  # always/on-failure/never
    max_restarts: int = 5
    restart_backoff_seconds: float = 2.0
    lightweight_fallback_command: List[str] | None = None

    def normalized(self) -> "BrainstemServiceSpec":
        policy = str(self.restart_policy or "on-failure").strip().lower()
        if policy not in {"always", "on-failure", "never"}:
            policy = "on-failure"
        cmd = [str(item) for item in (self.command or []) if str(item).strip()]
        fallback_cmd = [str(item) for item in (self.lightweight_fallback_command or []) if str(item).strip()]
        if not cmd:
            raise ValueError("command is required")
        return BrainstemServiceSpec(
            service_name=str(self.service_name or "").strip(),
            command=cmd,
            working_dir=str(self.working_dir or "").strip(),
            env={str(k): str(v) for k, v in (self.env or {}).items()},
            restart_policy=policy,
            max_restarts=max(0, int(self.max_restarts)),
            restart_backoff_seconds=max(0.0, float(self.restart_backoff_seconds)),
            lightweight_fallback_command=fallback_cmd or None,
        )


@dataclass
class BrainstemServiceState:
    service_name: str
    running: bool = False
    pid: int = 0
    restart_count: int = 0
    mode: str = "managed"  # managed/lightweight
    last_started_at: str = ""
    last_exit_code: Optional[int] = None
    updated_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "BrainstemServiceState":
        return cls(
            service_name=str(payload.get("service_name") or ""),
            running=bool(payload.get("running", False)),
            pid=int(payload.get("pid") or 0),
            restart_count=int(payload.get("restart_count") or 0),
            mode=str(payload.get("mode") or "managed"),
            last_started_at=str(payload.get("last_started_at") or ""),
            last_exit_code=payload.get("last_exit_code"),
            updated_at=str(payload.get("updated_at") or ""),
        )


@dataclass(frozen=True)
class SupervisorAction:
    action: str  # started/restarted/stopped/fallback/noop
    service_name: str
    pid: int = 0
    restart_count: int = 0
    reason: str = ""
    mode: str = "managed"
    backoff_seconds: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class BrainstemSupervisor:
    """Process supervision with restart policy and state persistence."""

    def __init__(
        self,
        *,
        state_file: Path,
        launcher: Optional[Launcher] = None,
        now_fn: Optional[Callable[[], float]] = None,
    ) -> None:
        self.state_file = Path(state_file)
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.launcher = launcher or self._default_launcher
        self._now_fn = now_fn or time.time
        self._lock = threading.Lock()
        self._specs: Dict[str, BrainstemServiceSpec] = {}
        self._states: Dict[str, BrainstemServiceState] = {}
        self._load_state()

    def register_service(self, spec: BrainstemServiceSpec) -> None:
        normalized = spec.normalized()
        if not normalized.service_name:
            raise ValueError("service_name is required")
        with self._lock:
            self._specs[normalized.service_name] = normalized
            self._states.setdefault(normalized.service_name, BrainstemServiceState(service_name=normalized.service_name))
            self._persist_state()

    def ensure_running(self, service_name: str) -> SupervisorAction:
        name = str(service_name or "").strip()
        with self._lock:
            spec = self._require_spec(name)
            state = self._states.setdefault(name, BrainstemServiceState(service_name=name))
            if state.running and state.pid > 0:
                return SupervisorAction(
                    action="noop",
                    service_name=name,
                    pid=state.pid,
                    restart_count=state.restart_count,
                    reason="already_running",
                    mode=state.mode,
                )
            pid = int(self.launcher(spec))
            state.running = True
            state.pid = pid
            state.mode = "managed"
            state.last_started_at = _utc_iso()
            state.updated_at = _utc_iso()
            self._persist_state()
            return SupervisorAction(
                action="started",
                service_name=name,
                pid=pid,
                restart_count=state.restart_count,
                reason="initial_start",
                mode=state.mode,
            )

    def mark_exit(self, service_name: str, *, exit_code: int) -> SupervisorAction:
        name = str(service_name or "").strip()
        with self._lock:
            spec = self._require_spec(name)
            state = self._states.setdefault(name, BrainstemServiceState(service_name=name))
            state.running = False
            state.pid = 0
            state.last_exit_code = int(exit_code)
            state.updated_at = _utc_iso()

            abnormal_exit = int(exit_code) != 0
            should_restart = False
            if spec.restart_policy == "always":
                should_restart = True
            elif spec.restart_policy == "on-failure" and abnormal_exit:
                should_restart = True

            if should_restart and state.restart_count < spec.max_restarts:
                state.restart_count += 1
                pid = int(self.launcher(spec))
                state.running = True
                state.pid = pid
                state.mode = "managed"
                state.last_started_at = _utc_iso()
                state.updated_at = _utc_iso()
                self._persist_state()
                return SupervisorAction(
                    action="restarted",
                    service_name=name,
                    pid=pid,
                    restart_count=state.restart_count,
                    reason="abnormal_exit_auto_restart",
                    mode=state.mode,
                    backoff_seconds=spec.restart_backoff_seconds,
                )

            if should_restart and state.restart_count >= spec.max_restarts and spec.lightweight_fallback_command:
                state.mode = "lightweight"
                state.updated_at = _utc_iso()
                self._persist_state()
                return SupervisorAction(
                    action="fallback",
                    service_name=name,
                    pid=0,
                    restart_count=state.restart_count,
                    reason="restart_budget_exhausted",
                    mode=state.mode,
                    backoff_seconds=0.0,
                )

            self._persist_state()
            reason = "clean_exit" if not abnormal_exit else "restart_disabled_or_budget_exhausted"
            return SupervisorAction(
                action="stopped",
                service_name=name,
                pid=0,
                restart_count=state.restart_count,
                reason=reason,
                mode=state.mode,
            )

    def get_state(self, service_name: str) -> BrainstemServiceState:
        name = str(service_name or "").strip()
        state = self._states.get(name)
        if state is None:
            return BrainstemServiceState(service_name=name)
        return BrainstemServiceState.from_dict(state.to_dict())

    def build_supervisor_manifest(self) -> Dict[str, Any]:
        services: List[Dict[str, Any]] = []
        for name, spec in self._specs.items():
            state = self._states.get(name, BrainstemServiceState(service_name=name))
            services.append(
                {
                    "service_name": name,
                    "command": list(spec.command),
                    "working_dir": spec.working_dir,
                    "restart_policy": spec.restart_policy,
                    "max_restarts": spec.max_restarts,
                    "restart_backoff_seconds": spec.restart_backoff_seconds,
                    "lightweight_fallback_command": list(spec.lightweight_fallback_command or []),
                    "state": state.to_dict(),
                }
            )
        services.sort(key=lambda row: row["service_name"])
        return {
            "generated_at": _utc_iso(),
            "state_file": str(self.state_file),
            "service_count": len(services),
            "services": services,
        }

    def render_systemd_unit(self, service_name: str) -> str:
        spec = self._require_spec(str(service_name or "").strip())
        restart_policy = {
            "always": "always",
            "on-failure": "on-failure",
            "never": "no",
        }.get(spec.restart_policy, "on-failure")
        command_text = " ".join(spec.command)
        working_dir = spec.working_dir or os.getcwd()
        return "\n".join(
            [
                "[Unit]",
                f"Description=Naga Brainstem Service ({spec.service_name})",
                "After=network.target",
                "",
                "[Service]",
                "Type=simple",
                f"WorkingDirectory={working_dir}",
                f"ExecStart={command_text}",
                f"Restart={restart_policy}",
                f"RestartSec={int(spec.restart_backoff_seconds)}",
                f"Environment=NAGA_BRAINSTEM_STATE_FILE={self.state_file}",
                "",
                "[Install]",
                "WantedBy=multi-user.target",
            ]
        )

    def render_windows_recovery_template(self, service_name: str) -> Dict[str, Any]:
        spec = self._require_spec(str(service_name or "").strip())
        return {
            "service_name": spec.service_name,
            "command": list(spec.command),
            "working_dir": spec.working_dir,
            "restart_policy": spec.restart_policy,
            "max_restarts": spec.max_restarts,
            "restart_backoff_seconds": spec.restart_backoff_seconds,
            "state_file": str(self.state_file),
            "recover_actions": [
                {"when": "failure", "action": "restart", "delay_seconds": int(spec.restart_backoff_seconds)},
                {"when": "second_failure", "action": "restart", "delay_seconds": int(spec.restart_backoff_seconds)},
                {"when": "third_failure", "action": "run_lightweight_mode" if spec.lightweight_fallback_command else "none"},
            ],
        }

    def _load_state(self) -> None:
        if not self.state_file.exists():
            return
        try:
            payload = json.loads(self.state_file.read_text(encoding="utf-8"))
        except Exception:
            return
        rows = payload.get("services")
        if not isinstance(rows, list):
            return
        for row in rows:
            if not isinstance(row, dict):
                continue
            state_payload = row.get("state")
            if not isinstance(state_payload, dict):
                continue
            state = BrainstemServiceState.from_dict(state_payload)
            if state.service_name:
                self._states[state.service_name] = state

    def _persist_state(self) -> None:
        payload = {
            "updated_at": _utc_iso(),
            "services": [{"service_name": name, "state": state.to_dict()} for name, state in sorted(self._states.items())],
        }
        self.state_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _require_spec(self, service_name: str) -> BrainstemServiceSpec:
        spec = self._specs.get(service_name)
        if spec is None:
            raise KeyError(f"service not registered: {service_name}")
        return spec

    @staticmethod
    def _default_launcher(spec: BrainstemServiceSpec) -> int:
        env = os.environ.copy()
        env.update(spec.env or {})
        proc = subprocess.Popen(  # noqa: S603
            spec.command,
            cwd=spec.working_dir or None,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return int(proc.pid)


__all__ = [
    "BrainstemServiceSpec",
    "BrainstemServiceState",
    "SupervisorAction",
    "BrainstemSupervisor",
]
