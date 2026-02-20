"""Planner that converts findings into executable tasks."""

from __future__ import annotations

import uuid
from typing import Dict, List

from autonomous.types import OptimizationTask


class Planner:
    """Simple deterministic planner for skeleton implementation."""

    def generate_tasks(self, findings: List[Dict[str, str]]) -> List[OptimizationTask]:
        tasks: List[OptimizationTask] = []
        for finding in findings:
            kind = finding.get("kind", "generic")
            severity = finding.get("severity", "medium")
            summary = finding.get("summary", "Address detected issue")
            task = OptimizationTask(
                task_id=f"auto-{uuid.uuid4().hex[:10]}",
                instruction=f"[{kind}/{severity}] {summary}",
                complexity="high" if severity == "high" else "medium",
                target_files=["autonomous/"],
                context_files=["doc/07-autonomous-agent-sdlc-architecture.md", "doc/架构与时序设计.md"],
                metadata={"finding": finding},
            )
            tasks.append(task)

        return tasks
