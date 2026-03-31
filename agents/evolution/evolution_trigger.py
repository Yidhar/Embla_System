"""Evolution trigger — evaluates signals and emits evolution events."""
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List

from agents.evolution.pattern_detector import EvolutionTriggerSignal, PatternDetector

logger = logging.getLogger(__name__)


@dataclass
class EvolutionDecision:
    should_evolve: bool
    signals: List[EvolutionTriggerSignal]
    reason: str = ""


class EvolutionTrigger:
    def __init__(
        self,
        *,
        episodic_dir: Path = Path("memory/episodic"),
        trigger_threshold: int = 3,
        max_per_day: int = 5,
        event_emitter: Any = None,
    ):
        self._detector = PatternDetector(
            episodic_dir=episodic_dir,
            trigger_threshold=trigger_threshold,
        )
        self._max_per_day = max_per_day
        self._event_emitter = event_emitter
        self._daily_count = 0

    def evaluate(self) -> EvolutionDecision:
        """Check for evolution-worthy patterns and decide whether to trigger."""
        if self._daily_count >= self._max_per_day:
            return EvolutionDecision(
                should_evolve=False,
                signals=[],
                reason=f"daily evolution limit reached ({self._max_per_day})",
            )

        signals = self._detector.check_recent(limit=50)
        if not signals:
            return EvolutionDecision(
                should_evolve=False,
                signals=[],
                reason="no failure patterns detected",
            )

        # Pick the highest confidence signal
        signals.sort(key=lambda s: s.confidence, reverse=True)

        self._daily_count += 1

        # Emit event
        if self._event_emitter:
            try:
                self._event_emitter.emit(
                    "EvolutionTriggered",
                    {
                        "trigger_type": signals[0].trigger_type,
                        "task_type": signals[0].task_type,
                        "failure_count": signals[0].failure_count,
                        "suggested_targets": signals[0].suggested_targets,
                    },
                    source="evolution_trigger",
                    severity="info",
                )
            except Exception:
                pass

        return EvolutionDecision(
            should_evolve=True,
            signals=signals,
            reason=(
                f"detected {len(signals)} failure pattern(s), "
                f"top: {signals[0].task_type} ({signals[0].failure_count} failures)"
            ),
        )

    def reset_daily_count(self) -> None:
        self._daily_count = 0
