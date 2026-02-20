# Rollback Runbook

## Trigger Conditions

1. Canary burn-rate violates configured threshold for 2 consecutive windows.
2. Critical KPI regression exceeds release guardrail.
3. Production deploy task enters `FailedHard` or manual kill switch is triggered.

## Execution Steps

1. Freeze further promotions.
2. Identify target release revision and rollback point.
3. Execute rollback command through release controller.
4. Mark current release as `rolled_back`.
5. Open incident record with root-cause placeholder.

## Verification Steps

1. Validate service health checks return to baseline.
2. Compare error rate and latency against pre-release baseline.
3. Confirm no new critical alerts remain firing for two windows.

## Recovery Steps

1. Capture root cause and impacted scope.
2. Prepare fix branch and rerun mandatory checks.
3. Re-enter canary flow with fresh sample window.
