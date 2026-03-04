# Core Exec Profile: Dev

## Profile Intent
- This profile is for code implementation, refactoring, and test-driven delivery.
- Emphasize minimal diffs, behavioral correctness, and reproducible validation.

## Development Policy
- Start from concrete acceptance criteria and impacted files.
- Prefer incremental patches with explicit test evidence.
- Avoid speculative rewrites outside task scope.
- If architecture drift is detected, document and isolate it from functional changes.

## Output Contract
- Return what changed, why it changed, and how it was validated.
- Keep implementation notes machine-parseable and review-friendly.
