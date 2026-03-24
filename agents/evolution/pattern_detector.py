"""Pattern detector — analyzes L1 episodic memory for failure patterns."""
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


@dataclass
class EvolutionTriggerSignal:
    trigger_type: str  # "failure_pattern" | "performance_degradation"
    task_type: str
    failure_count: int
    sample_files: List[str] = field(default_factory=list)
    suggested_targets: List[str] = field(default_factory=list)
    confidence: float = 0.0


class PatternDetector:
    def __init__(self, *, episodic_dir: Path, trigger_threshold: int = 3):
        self._episodic_dir = Path(episodic_dir)
        self._trigger_threshold = max(1, trigger_threshold)

    def check_recent(self, *, limit: int = 50) -> List[EvolutionTriggerSignal]:
        """Scan recent episodic memory files for failure patterns."""
        if not self._episodic_dir.exists():
            return []

        # Read recent experience files
        exp_files = sorted(
            self._episodic_dir.glob("exp_*.md"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )[:limit]

        if not exp_files:
            return []

        # Parse and cluster by tags/task_type
        failure_clusters: Dict[str, List[str]] = defaultdict(list)

        for exp_file in exp_files:
            try:
                content = exp_file.read_text(encoding="utf-8")
                metadata = self._parse_frontmatter(content)
                outcome = str(metadata.get("outcome", "")).strip().lower()
                if outcome not in ("failure", "failed", "error"):
                    continue

                # Cluster key: tags or task_type
                tags = metadata.get("tags", [])
                if isinstance(tags, list) and tags:
                    cluster_key = "|".join(sorted(str(t).strip() for t in tags if str(t).strip()))
                else:
                    cluster_key = str(metadata.get("task_type", "unknown")).strip()

                if cluster_key:
                    failure_clusters[cluster_key].append(str(exp_file.name))
            except Exception:
                continue

        # Check each cluster against threshold
        signals = []
        for cluster_key, files in failure_clusters.items():
            if len(files) >= self._trigger_threshold:
                # Map cluster key to suggested prompt targets
                suggested = self._suggest_targets(cluster_key)
                signals.append(
                    EvolutionTriggerSignal(
                        trigger_type="failure_pattern",
                        task_type=cluster_key,
                        failure_count=len(files),
                        sample_files=files[:5],
                        suggested_targets=suggested,
                        confidence=min(1.0, len(files) / (self._trigger_threshold * 2)),
                    )
                )

        return signals

    def _parse_frontmatter(self, content: str) -> Dict[str, Any]:
        """Parse YAML-like frontmatter from markdown."""
        lines = content.split("\n")
        if not lines or lines[0].strip() != "---":
            return {}
        metadata: Dict[str, Any] = {}
        for line in lines[1:]:
            if line.strip() == "---":
                break
            if ":" in line:
                key, _, value = line.partition(":")
                key = key.strip()
                value = value.strip()
                if value.startswith("[") and value.endswith("]"):
                    # Simple list parsing
                    items = [item.strip().strip("'\"") for item in value[1:-1].split(",") if item.strip()]
                    metadata[key] = items
                else:
                    metadata[key] = value
        return metadata

    def _suggest_targets(self, cluster_key: str) -> List[str]:
        """Map failure cluster key to suggested prompt targets."""
        tag_to_prompt = {
            "backend": "roles/backend_expert.md",
            "frontend": "roles/frontend_expert.md",
            "ops": "roles/ops_expert.md",
            "testing": "roles/testing_expert.md",
            "docs": "roles/docs_expert.md",
            "code_quality": "skills/code_review.md",
            "architecture": "skills/architecture.md",
        }
        tags = cluster_key.split("|")
        targets = []
        for tag in tags:
            tag_lower = tag.strip().lower()
            if tag_lower in tag_to_prompt:
                targets.append(tag_to_prompt[tag_lower])
        return targets if targets else ["roles/backend_expert.md"]  # default
