# Core Exec Profile: Dev

## Profile Intent
- This profile is for code implementation, refactoring, and test-driven delivery inside Core execution.
- Emphasize minimal diffs, root-cause fixes, behavioral correctness, and reproducible validation.

## Development Policy
- Start from concrete acceptance criteria and impacted files.
- Follow the runtime-injected tool schema; do not assume legacy wrappers like `native_call` or `mcp_call` are available.
- Prefer incremental patches with explicit validation evidence.
- Avoid speculative rewrites outside task scope.
- If architecture drift is detected, document and isolate it from functional changes.
- Before completion, preserve self-verification evidence: tests, lint/type checks, and diff self-review.

## Output Contract
- Return what changed, why it changed, and how it was validated.
- Keep implementation notes machine-parseable and review-friendly.
