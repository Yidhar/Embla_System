#!/usr/bin/env python3
"""Bulk garbage-collect stale/orphaned agent worktrees.

Usage:
    # Dry-run (default) — list what would be cleaned
    python scripts/gc_stale_worktrees_ws35_001.py

    # Actually delete stale worktrees
    python scripts/gc_stale_worktrees_ws35_001.py --execute

    # Custom age threshold (hours)
    python scripts/gc_stale_worktrees_ws35_001.py --execute --max-age 1.0
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Ensure project root on sys.path
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger("gc_stale_worktrees")


def main() -> None:
    parser = argparse.ArgumentParser(description="Garbage-collect stale agent worktrees")
    parser.add_argument("--execute", action="store_true", help="Actually delete (default is dry-run)")
    parser.add_argument("--max-age", type=float, default=2.0, help="Max age in hours before a worktree is considered stale (default: 2.0)")
    args = parser.parse_args()

    dry_run = not args.execute

    # Collect active session IDs from the on-disk DB
    active_ids: set = set()
    db_path = _PROJECT_ROOT / "scratch" / "runtime" / "agent_sessions.db"
    if db_path.exists():
        try:
            from agents.runtime.agent_session import AgentSessionStore
            store = AgentSessionStore(db_path=str(db_path))
            active_ids = {s.session_id for s in store.list_sessions()}
            store.close()
            logger.info("Loaded %d active session IDs from %s", len(active_ids), db_path)
        except Exception as exc:
            logger.warning("Could not read session DB: %s — treating all worktrees as orphaned", exc)
    else:
        logger.warning("Session DB not found at %s — treating all worktrees as orphaned", db_path)

    # List current worktrees
    from system.git_worktree_sandbox import list_worktree_dirs, gc_sweep_stale_worktrees

    worktrees = list_worktree_dirs(repo_root=_PROJECT_ROOT)
    logger.info("Found %d worktree(s) on disk", len(worktrees))
    if not worktrees:
        logger.info("Nothing to do.")
        return

    # Run GC sweep
    result = gc_sweep_stale_worktrees(
        repo_root=_PROJECT_ROOT,
        active_session_ids=active_ids,
        max_age_hours=args.max_age,
        dry_run=dry_run,
    )

    cleaned = result.get("cleaned", [])
    skipped = result.get("skipped", [])
    errors = result.get("errors", [])

    mode_label = "DRY-RUN" if dry_run else "EXECUTED"
    logger.info("--- GC Summary (%s) ---", mode_label)
    logger.info("  Cleaned : %d", len(cleaned))
    logger.info("  Skipped : %d (active or too recent)", len(skipped))
    logger.info("  Errors  : %d", len(errors))

    if cleaned and dry_run:
        logger.info("Would clean:")
        for owner in cleaned:
            logger.info("  - %s", owner)
        logger.info("Re-run with --execute to actually delete.")

    if errors:
        logger.warning("Errors:")
        for err in errors:
            logger.warning("  - %s: %s", err.get("owner"), err.get("error"))

    # Also run git worktree prune for any broken refs
    import subprocess
    try:
        subprocess.run(
            ["git", "worktree", "prune"],
            cwd=str(_PROJECT_ROOT),
            capture_output=True,
            timeout=30,
        )
        logger.info("git worktree prune completed.")
    except Exception as exc:
        logger.warning("git worktree prune failed: %s", exc)


if __name__ == "__main__":
    main()
