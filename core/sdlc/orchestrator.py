"""SDLC orchestrator — coordinates lease, gate evaluation, and controlled execution."""
import asyncio
import logging
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class SDLCOrchestrator:
    def __init__(self, *, project_root: Path = Path("."), event_emitter=None, enabled: bool = False):
        self._project_root = project_root
        self._event_emitter = event_emitter
        self._enabled = enabled
        self._lease_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    @property
    def enabled(self) -> bool:
        return self._enabled

    def start(self) -> None:
        """Start the SDLC orchestrator if enabled."""
        if not self._enabled:
            logger.info("SDLC 编排器未启用 (autonomous_runtime.yaml: enabled=false)")
            return
        self._stop_event.clear()
        self._lease_thread = threading.Thread(target=self._lease_heartbeat_loop, daemon=True, name="sdlc-lease")
        self._lease_thread.start()
        logger.info("SDLC 编排器已启动")

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
                    snapshot = loop.run_until_complete(
                        controller.acquire(owner_id="sdlc_orchestrator", job_id="sdlc_heartbeat", ttl=ttl)
                    )
                    if self._event_emitter:
                        self._event_emitter.emit("LeaseAcquired", {"owner": "sdlc_orchestrator"})
                except Exception as exc:
                    logger.warning(f"Lease 心跳失败: {exc}")
                    if self._event_emitter:
                        self._event_emitter.emit("LeaseHeartbeatFailed", {"error": str(exc)})
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


_DEFAULT_ORCHESTRATOR: Optional[SDLCOrchestrator] = None


def get_default_orchestrator() -> SDLCOrchestrator:
    global _DEFAULT_ORCHESTRATOR
    if _DEFAULT_ORCHESTRATOR is None:
        _DEFAULT_ORCHESTRATOR = SDLCOrchestrator()
    return _DEFAULT_ORCHESTRATOR
