"""Signal collection for autonomous planning."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List


class Sensor:
    """Collect lightweight repository signals for planner input."""

    def __init__(self, repo_dir: str) -> None:
        self.repo_dir = Path(repo_dir)

    def scan_codebase(self) -> List[Dict[str, str]]:
        findings: List[Dict[str, str]] = []

        autonomous_dir = self.repo_dir / "autonomous"
        if not autonomous_dir.exists():
            findings.append(
                {
                    "kind": "bootstrap",
                    "severity": "high",
                    "summary": "autonomous package does not exist",
                }
            )

        tests_dir = self.repo_dir / "autonomous" / "tests"
        if not tests_dir.exists():
            findings.append(
                {
                    "kind": "test_gap",
                    "severity": "medium",
                    "summary": "autonomous/tests is missing",
                }
            )

        return findings

    def scan_logs(self) -> List[Dict[str, str]]:
        return []
