# Scripts Index And Lifecycle

This directory contains release gates, runbook utilities, and one-off task scripts.

## Lifecycle Labels

- `active`: currently used in release chains or standard runbooks.
- `legacy`: kept for backward compatibility, default non-blocking in main release chain.
- `experimental`: task-specific or migration-stage tooling; not a default release blocker.

## Primary Entrypoints (`active`)

- `scripts/release_closure_chain_m0_m5.py`
  - M0-M5 release closure chain.
  - Frontend gate strategy:
    - `T5B`: `scripts/embla_core_release_compat_gate.py` (blocking).
    - `T5C`: `scripts/desktop_release_compat_ws20_006.py` (legacy, non-blocking by default).
- `scripts/release_closure_chain_full_m0_m7.py`
  - M0-M11 unified closure chain.
- `scripts/release_closure_chain_full_m0_m12.py`
  - M0-M12 full closure chain.
- `scripts/manage_brainstem_control_plane_ws28_017.py`
  - Brainstem + watchdog managed lifecycle.
- `scripts/run_watchdog_daemon_ws28_025.py`
  - Watchdog daemon run/status entrypoint.

## Frontend Compatibility Gates

- `scripts/embla_core_release_compat_gate.py` (`active`)
  - Wrapper entrypoint.
  - Canonical implementation:
    - `scripts/gates/embla_core/embla_core_release_compat_gate.py`
- `scripts/desktop_release_compat_ws20_006.py` (`legacy`)
  - Wrapper entrypoint kept for old commands and runbooks.
  - Canonical implementation:
    - `scripts/gates/legacy/desktop_release_compat_ws20_006.py`

## Devtools Helpers (`experimental`)

- `scripts/devtools/dev_grep.py`
  - Tiny grep helper for line-level pattern scan in a single file.
- `scripts/devtools/dev_search_repo.py`
  - Plain substring search across the repo.
- `scripts/devtools/dev_slice.py`
  - Print file line ranges for quick inspection.

## Compatibility Policy

- Root-level script names are treated as stable command contracts.
- When internals are reorganized, root wrappers should remain available.
- Legacy gates can be forced to blocking mode when needed:
  - `python scripts/release_closure_chain_m0_m5.py --strict-legacy-desktop-gate`
