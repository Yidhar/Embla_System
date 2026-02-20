# Autonomous Workflow State Machine

## States

1. `GoalAccepted`
2. `PlanDrafted`
3. `Implementing`
4. `Verifying`
5. `Reworking`
6. `ReleaseCandidate`
7. `CanaryRunning`
8. `Promoted`
9. `RolledBack`
10. `FailedExhausted`
11. `FailedHard`
12. `Killed`

## Transition Rules (Implemented Skeleton)

1. `GoalAccepted -> PlanDrafted` when planner produced task.
2. `PlanDrafted -> Implementing` before first CLI dispatch.
3. `Implementing -> Verifying` after each CLI execution.
4. `Verifying -> ReleaseCandidate` when evaluator approves.
5. `ReleaseCandidate -> CanaryRunning` when outbox consumer starts canary evaluation.
6. `CanaryRunning -> Promoted` when canary decision is promote.
7. `CanaryRunning -> RolledBack` when canary decision is rollback.
8. `Verifying -> Reworking` when evaluator rejects and retry remains.
9. `Reworking -> Implementing` on retry dispatch.
10. `Verifying -> FailedExhausted` when retries are exhausted.
11. `FailedExhausted -> Reworking` when Codex MCP fallback provides usable suggestion.
12. `FailedExhausted -> FailedHard` when Codex MCP fallback fails.

## Durable Persistence

1. `workflow_state` tracks current state and retry counters.
2. `workflow_event` stores immutable transitions with unique `transition_id`.
3. `workflow_command` stores side-effect command lifecycle and idempotency key.
4. `outbox_event` stores events ready for async dispatch.
5. `inbox_dedup` is used by the release outbox consumer for idempotent dispatch.
6. `orchestrator_lease` stores `owner_id + fencing_epoch + lease_expire_at` for single-active arbitration.
