"""WS24 plugin worker proxy (isolation + runtime hardening + lifecycle tracking)."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from system.process_lineage import get_process_lineage_registry


def _json_error(message: str, **kwargs: Any) -> str:
    payload: Dict[str, Any] = {"status": "error", "message": str(message)}
    payload.update(kwargs)
    return json.dumps(payload, ensure_ascii=False)


@dataclass(frozen=True)
class PluginWorkerSpec:
    service_name: str
    module_name: str
    class_name: str
    timeout_seconds: float = 30.0
    max_payload_bytes: int = 131_072
    max_output_bytes: int = 262_144
    max_memory_mb: int = 256
    cpu_time_seconds: int = 20
    max_failure_streak: int = 3
    cooldown_seconds: float = 30.0
    stale_reap_grace_seconds: float = 90.0
    python_executable: str = sys.executable
    pythonpath_entries: List[str] = field(default_factory=list)


_RUNTIME_METRICS_LOCK = threading.RLock()
_RUNTIME_METRICS: Dict[str, Dict[str, Any]] = {}


def _get_or_init_service_metric(service_name: str) -> Dict[str, Any]:
    key = str(service_name or "unknown").strip() or "unknown"
    with _RUNTIME_METRICS_LOCK:
        metric = _RUNTIME_METRICS.get(key)
        if metric is None:
            metric = {
                "service_name": key,
                "calls_total": 0,
                "success_total": 0,
                "error_total": 0,
                "timeout_total": 0,
                "circuit_open_total": 0,
                "payload_reject_total": 0,
                "output_budget_reject_total": 0,
                "stale_reaped_total": 0,
                "last_call_ts": 0.0,
                "last_status": "",
                "last_error": "",
                "last_elapsed_ms": 0,
            }
            _RUNTIME_METRICS[key] = metric
        return metric


def _record_metric(
    service_name: str,
    *,
    status: str,
    elapsed_ms: int,
    error: str = "",
    stale_reaped: int = 0,
) -> None:
    metric = _get_or_init_service_metric(service_name)
    with _RUNTIME_METRICS_LOCK:
        metric["calls_total"] = int(metric.get("calls_total") or 0) + 1
        metric["last_call_ts"] = time.time()
        metric["last_status"] = status
        metric["last_error"] = str(error or "")
        metric["last_elapsed_ms"] = int(max(0, elapsed_ms))
        metric["stale_reaped_total"] = int(metric.get("stale_reaped_total") or 0) + int(max(0, stale_reaped))
        if status == "ok":
            metric["success_total"] = int(metric.get("success_total") or 0) + 1
        else:
            metric["error_total"] = int(metric.get("error_total") or 0) + 1
            if status == "timeout":
                metric["timeout_total"] = int(metric.get("timeout_total") or 0) + 1
            if status == "circuit_open":
                metric["circuit_open_total"] = int(metric.get("circuit_open_total") or 0) + 1
            if status == "payload_rejected":
                metric["payload_reject_total"] = int(metric.get("payload_reject_total") or 0) + 1
            if status == "output_budget_rejected":
                metric["output_budget_reject_total"] = int(metric.get("output_budget_reject_total") or 0) + 1


def get_plugin_worker_runtime_metrics() -> Dict[str, Any]:
    with _RUNTIME_METRICS_LOCK:
        services = {k: dict(v) for k, v in _RUNTIME_METRICS.items()}
    return {
        "services": services,
        "service_count": len(services),
    }


def reset_plugin_worker_runtime_metrics() -> None:
    with _RUNTIME_METRICS_LOCK:
        _RUNTIME_METRICS.clear()


def _to_preview(data: bytes | str, *, limit: int = 1200) -> str:
    if isinstance(data, bytes):
        text = data.decode("utf-8", errors="replace")
    else:
        text = str(data or "")
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def _extract_fencing_epoch(payload: Dict[str, Any]) -> Optional[int]:
    value = payload.get("_fencing_epoch")
    if value is None:
        value = payload.get("fencing_epoch")
    if value is None:
        return None
    try:
        parsed = int(value)
    except Exception:
        return None
    return parsed if parsed > 0 else None


class PluginWorkerProxy:
    """Execute plugin calls in an isolated child process."""

    def __init__(self, spec: PluginWorkerSpec) -> None:
        self.spec = spec
        self._state_lock = threading.RLock()
        self._failure_streak = 0
        self._circuit_open_until = 0.0

    async def handle_handoff(self, tool_call: Dict[str, Any]) -> str:
        payload = dict(tool_call or {})
        return await asyncio.to_thread(self._invoke_worker_subprocess, payload)

    def _invoke_worker_subprocess(self, payload: Dict[str, Any]) -> str:
        started_at = time.monotonic()
        is_open, retry_after = self._circuit_open_state()
        if is_open:
            elapsed_ms = int((time.monotonic() - started_at) * 1000)
            _record_metric(
                self.spec.service_name,
                status="circuit_open",
                elapsed_ms=elapsed_ms,
                error="circuit_open",
            )
            return _json_error(
                "plugin worker circuit open",
                service_name=self.spec.service_name,
                module_name=self.spec.module_name,
                class_name=self.spec.class_name,
                route="plugin_worker",
                retry_after_seconds=round(max(0.0, retry_after), 3),
            )

        stale_reaped = self._reap_stale_plugin_workers()
        cmd = [
            str(self.spec.python_executable or sys.executable),
            "-m",
            "mcpserver.plugin_worker_runtime",
            "--module",
            str(self.spec.module_name),
            "--class",
            str(self.spec.class_name),
            "--max-memory-mb",
            str(max(0, int(self.spec.max_memory_mb))),
            "--cpu-time-seconds",
            str(max(0, int(self.spec.cpu_time_seconds))),
        ]
        env = self._build_env()
        stdin_text = json.dumps(payload, ensure_ascii=False)
        stdin_bytes = stdin_text.encode("utf-8")
        if len(stdin_bytes) > int(self.spec.max_payload_bytes):
            self._mark_failure()
            elapsed_ms = int((time.monotonic() - started_at) * 1000)
            _record_metric(
                self.spec.service_name,
                status="payload_rejected",
                elapsed_ms=elapsed_ms,
                error="payload_budget_exceeded",
                stale_reaped=stale_reaped,
            )
            return _json_error(
                "plugin payload budget exceeded",
                service_name=self.spec.service_name,
                module_name=self.spec.module_name,
                class_name=self.spec.class_name,
                route="plugin_worker",
                payload_bytes=len(stdin_bytes),
                max_payload_bytes=int(self.spec.max_payload_bytes),
            )

        command_text = subprocess.list2cmdline(cmd)
        timeout_seconds = max(1.0, float(self.spec.timeout_seconds))
        lineage = get_process_lineage_registry()
        call_id = f"plugin_{uuid.uuid4().hex[:12]}"
        job_root_id = ""
        process: subprocess.Popen[bytes] | None = None
        try:
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )
            job_root_id = lineage.register_start(
                call_id=call_id,
                command=command_text,
                root_pid=int(process.pid or 0),
                fencing_epoch=_extract_fencing_epoch(payload),
            )
            stdout_bytes, stderr_bytes = process.communicate(input=stdin_bytes, timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            if process is not None:
                try:
                    process.kill()
                except Exception:
                    pass
                try:
                    process.communicate(timeout=1.0)
                except Exception:
                    pass

            timeout_cleanup: Dict[str, Any] = {}
            try:
                if job_root_id:
                    kill_ok = bool(lineage.kill_job(job_root_id, reason="plugin_worker_timeout"))
                    timeout_cleanup["lineage_kill_ok"] = kill_ok
                    orphan_reaped = int(
                        lineage.reap_orphaned_running_jobs(
                            reason="plugin_worker_timeout_orphan_scan",
                            max_epoch=_extract_fencing_epoch(payload),
                        )
                    )
                    timeout_cleanup["orphan_reaped_count"] = orphan_reaped
                    stale_reaped += orphan_reaped
            except Exception:
                pass

            self._mark_failure()
            elapsed_ms = int((time.monotonic() - started_at) * 1000)
            _record_metric(
                self.spec.service_name,
                status="timeout",
                elapsed_ms=elapsed_ms,
                error="timeout",
                stale_reaped=stale_reaped,
            )
            return _json_error(
                "plugin worker timeout",
                service_name=self.spec.service_name,
                module_name=self.spec.module_name,
                class_name=self.spec.class_name,
                route="plugin_worker",
                timeout_seconds=timeout_seconds,
                stale_reaped=int(stale_reaped),
                timeout_cleanup=timeout_cleanup,
            )
        except Exception as exc:
            self._mark_failure()
            elapsed_ms = int((time.monotonic() - started_at) * 1000)
            _record_metric(
                self.spec.service_name,
                status="spawn_failed",
                elapsed_ms=elapsed_ms,
                error=str(exc),
                stale_reaped=stale_reaped,
            )
            return _json_error(
                f"plugin worker spawn failed: {exc}",
                service_name=self.spec.service_name,
                module_name=self.spec.module_name,
                class_name=self.spec.class_name,
                route="plugin_worker",
            )

        stdout_size = len(stdout_bytes or b"")
        stderr_size = len(stderr_bytes or b"")
        total_output_size = stdout_size + stderr_size
        return_code = int(process.returncode or 0) if process is not None else 1
        stdout_text = _to_preview(stdout_bytes, limit=2_000_000)
        stderr_text = _to_preview(stderr_bytes, limit=2_000_000)

        if total_output_size > int(self.spec.max_output_bytes):
            if job_root_id:
                try:
                    lineage.register_end(
                        job_root_id,
                        return_code=return_code,
                        status="output_budget_rejected",
                        reason=f"output_budget_exceeded:{total_output_size}>{int(self.spec.max_output_bytes)}",
                    )
                except Exception:
                    pass
            self._mark_failure()
            elapsed_ms = int((time.monotonic() - started_at) * 1000)
            _record_metric(
                self.spec.service_name,
                status="output_budget_rejected",
                elapsed_ms=elapsed_ms,
                error="output_budget_exceeded",
                stale_reaped=stale_reaped,
            )
            return _json_error(
                "plugin worker output budget exceeded",
                service_name=self.spec.service_name,
                module_name=self.spec.module_name,
                class_name=self.spec.class_name,
                route="plugin_worker",
                max_output_bytes=int(self.spec.max_output_bytes),
                output_bytes=int(total_output_size),
                stderr=_to_preview(stderr_text),
                stdout=_to_preview(stdout_text),
            )

        if return_code != 0:
            if job_root_id:
                try:
                    lineage.register_end(
                        job_root_id,
                        return_code=return_code,
                        status="failed",
                        reason="plugin_worker_execution_failed",
                    )
                except Exception:
                    pass
            self._mark_failure()
            elapsed_ms = int((time.monotonic() - started_at) * 1000)
            _record_metric(
                self.spec.service_name,
                status="execution_failed",
                elapsed_ms=elapsed_ms,
                error=stderr_text[:300],
                stale_reaped=stale_reaped,
            )
            return _json_error(
                "plugin worker execution failed",
                service_name=self.spec.service_name,
                module_name=self.spec.module_name,
                class_name=self.spec.class_name,
                route="plugin_worker",
                exit_code=return_code,
                stderr=stderr_text[:1200],
                stdout=stdout_text[:1200],
            )

        if job_root_id:
            try:
                lineage.register_end(job_root_id, return_code=return_code, status="completed", reason="ok")
            except Exception:
                pass
        self._mark_success()
        elapsed_ms = int((time.monotonic() - started_at) * 1000)
        _record_metric(
            self.spec.service_name,
            status="ok",
            elapsed_ms=elapsed_ms,
            stale_reaped=stale_reaped,
        )

        if stdout_text:
            return stdout_text
        return json.dumps(
            {
                "status": "ok",
                "service_name": self.spec.service_name,
                "route": "plugin_worker",
                "result": "",
                "stale_reaped": int(stale_reaped),
            },
            ensure_ascii=False,
        )

    def _build_env(self) -> Dict[str, str]:
        env = dict(os.environ)
        env["NAGA_PLUGIN_WORKER_ISOLATED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        existing = str(env.get("PYTHONPATH", "")).strip()
        entries = [str(Path(item)).replace("\\", "/") for item in self.spec.pythonpath_entries if str(item).strip()]
        if existing:
            entries.append(existing)
        if entries:
            env["PYTHONPATH"] = os.pathsep.join(entries)
        return env

    def _circuit_open_state(self) -> tuple[bool, float]:
        now = time.time()
        with self._state_lock:
            if now < float(self._circuit_open_until):
                return True, float(self._circuit_open_until) - now
            return False, 0.0

    def _mark_failure(self) -> None:
        with self._state_lock:
            self._failure_streak = int(self._failure_streak) + 1
            if self._failure_streak >= int(max(1, self.spec.max_failure_streak)):
                self._circuit_open_until = max(float(self._circuit_open_until), time.time() + float(self.spec.cooldown_seconds))

    def _mark_success(self) -> None:
        with self._state_lock:
            self._failure_streak = 0
            self._circuit_open_until = 0.0

    def _reap_stale_plugin_workers(self) -> int:
        threshold = max(float(self.spec.stale_reap_grace_seconds), float(self.spec.timeout_seconds) * 2.0)
        now = time.time()
        try:
            registry = get_process_lineage_registry()
            candidates = [
                item
                for item in registry.list_running()
                if "mcpserver.plugin_worker_runtime" in str(item.command or "")
                and (now - float(item.started_at or 0.0)) >= threshold
            ]
            cleaned = 0
            for item in candidates:
                if registry.kill_job(item.job_root_id, reason=f"plugin_worker_stale_reap>{int(threshold)}s"):
                    cleaned += 1
            return cleaned
        except Exception:
            return 0


__all__ = [
    "PluginWorkerSpec",
    "PluginWorkerProxy",
    "get_plugin_worker_runtime_metrics",
    "reset_plugin_worker_runtime_metrics",
]
