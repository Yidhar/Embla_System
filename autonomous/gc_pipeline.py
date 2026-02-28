"""Compatibility exports for episodic-memory GC pipeline.

Canonical implementation now lives in `agents.memory.gc_pipeline`.
"""

from agents.memory.gc_pipeline import GCPipelineConfig, GCPipelineReport, run_gc_pipeline

__all__ = ["GCPipelineConfig", "GCPipelineReport", "run_gc_pipeline"]
