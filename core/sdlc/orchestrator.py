"""SDLC orchestrator — coordinates lease, gate evaluation, stage transitions, and controlled execution."""
import asyncio
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Default stage sequence
_DEFAULT_STAGES = ("plan", "build", "test", "deploy")


@dataclass
class StageTransition:
    """Record of a stage transition."""
    from_stage: Optional[str]
    to_stage: str
    timestamp: str
    trigger: str  # "auto" | "manual" | "gate_pass"
    metadata: Dict[str, Any] = field(default_factory=dict)


class SDLCOrchestrator:
    def __init__(
        self,
        *,
        project_root: Path = Path("."),
        event_emitter=None,
        enabled: bool = False,
        stages: Optional[List[str]] = None,
        auto_advance: bool = False,
    ):
        self._project_root = project_root
        self._event_emitter = event_emitter
        self._enabled = enabled
        self._stages = tuple(stages) if stages else _DEFAULT_STAGES
        self._auto_advance = auto_advance
        self._lease_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        # Stage tracking
        self._current_stage: Optional[str] = None
        self._stage_history: List[StageTransition] = []
        self._stage_lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def is_running(self) -> bool:
        return self._lease_thread is not None and self._lease_thread.is_alive()

    @property
    def current_stage(self) -> Optional[str]:
        return self._current_stage

    @property
    def stages(self) -> tuple:
        return self._stages

    def get_status(self) -> Dict[str, Any]:
        """Return comprehensive orchestrator status for dashboard/API."""
        with self._stage_lock:
            history = list(self._stage_history[-20:])
        return {
            "enabled": self._enabled,
            "running": self.is_running,
            "stages": list(self._stages),
            "current_stage": self._current_stage,
            "auto_advance": self._auto_advance,
            "stage_history": [
                {
                    "from": t.from_stage,
                    "to": t.to_stage,
                    "timestamp": t.timestamp,
                    "trigger": t.trigger,
                }
                for t in history
            ],
        }

    def advance_stage(self, *, trigger: str = "manual", metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Advance to the next SDLC stage.

        Returns a dict with the transition result.
        """
        with self._stage_lock:
            if self._current_stage is None:
                next_stage = self._stages[0] if self._stages else None
            else:
                try:
                    idx = self._stages.index(self._current_stage)
                    next_stage = self._stages[idx + 1] if idx + 1 < len(self._stages) else None
                except ValueError:
                    next_stage = None

            if next_stage is None:
                return {"status": "completed", "message": "All SDLC stages completed or no stages configured."}

            transition = StageTransition(
                from_stage=self._current_stage,
                to_stage=next_stage,
                timestamp=datetime.now(timezone.utc).isoformat(),
                trigger=trigger,
                metadata=metadata or {},
            )
            prev = self._current_stage
            self._current_stage = next_stage
            self._stage_history.append(transition)

        logger.info("SDLC stage: %s → %s (trigger=%s)", prev or "(none)", next_stage, trigger)
        self._emit("SDLCStageAdvanced", {
            "from_stage": prev,
            "to_stage": next_stage,
            "trigger": trigger,
        })
        return {"status": "advanced", "from_stage": prev, "to_stage": next_stage, "trigger": trigger}

    def reset_stages(self) -> None:
        """Reset stage tracking to initial state."""
        with self._stage_lock:
            self._current_stage = None
            self._stage_history.clear()
        self._emit("SDLCStagesReset", {})

    def start(self) -> None:
        """Start the SDLC orchestrator if enabled."""
        if not self._enabled:
            logger.info("SDLC 编排器未启用 (autonomous_runtime.yaml: enabled=false)")
            return
        self._stop_event.clear()
        self._lease_thread = threading.Thread(target=self._lease_heartbeat_loop, daemon=True, name="sdlc-lease")
        self._lease_thread.start()
        logger.info("SDLC 编排器已启动 (stages=%s, auto_advance=%s)", list(self._stages), self._auto_advance)

    def shutdown(self) -> None:
        self._stop_event.set()
        if self._lease_thread and self._lease_thread.is_alive():
            self._lease_thread.join(timeout=3.0)
        self._lease_thread = None

    def _lease_heartbeat_loop(self) -> None:
        """Periodic lease renewal loop."""
        from core.security.lease_fencing import LeaseFencingController

        controller = LeaseFencingController()
        controller.ensure_initialized(ttl_seconds=10.0)
        ttl = 10.0  # from autonomous_runtime.yaml default
        loop = asyncio.new_event_loop()
        try:
            while not self._stop_event.is_set():
                try:
                    loop.run_until_complete(
                        controller.acquire(owner_id="sdlc_orchestrator", job_id="sdlc_heartbeat", ttl=ttl)
                    )
                    self._emit("LeaseAcquired", {"owner": "sdlc_orchestrator"})
                except Exception as exc:
                    logger.warning(f"Lease 心跳失败: {exc}")
                    self._emit("LeaseHeartbeatFailed", {"error": str(exc)})
                self._stop_event.wait(timeout=max(1.0, ttl / 2))
        finally:
            loop.close()

    def evaluate_gate(self, gate_name: str) -> Dict[str, Any]:
        """Delegate gate evaluation to GateRunner."""
        from core.release.gate_runner import GateRunner

        policy_path = self._project_root / "policy" / "gate_policy.yaml"
        runner = GateRunner(policy_path=policy_path, event_emitter=self._event_emitter)
        evaluation = runner.evaluate_gate(gate_name)
        return evaluation.to_dict()

    def _emit(self, event_type: str, payload: Dict[str, Any]) -> None:
        if self._event_emitter is None:
            return
        try:
            self._event_emitter.emit(event_type, payload)
        except Exception:
            pass


_DEFAULT_ORCHESTRATOR: Optional[SDLCOrchestrator] = None


def get_default_orchestrator() -> SDLCOrchestrator:
    global _DEFAULT_ORCHESTRATOR
    if _DEFAULT_ORCHESTRATOR is None:
        _DEFAULT_ORCHESTRATOR = SDLCOrchestrator()
    return _DEFAULT_ORCHESTRATOR
