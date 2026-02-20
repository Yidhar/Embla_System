# Incident Runbook

## Incident Open Conditions

1. Automatic rollback triggered by canary policy.
2. Manual emergency stop due to high-severity production issue.
3. Verification fallback chain repeatedly fails and blocks recovery.

## Triage Steps

1. Assign incident owner and severity.
2. Freeze autonomous promotion and deploy flows.
3. Capture current workflow state, last successful commit, and release metadata.
4. Collect logs, traces, and recent workflow events.

## Mitigation Steps

1. Apply rollback if not already completed.
2. Disable risky tool categories if needed.
3. Re-run baseline smoke checks to confirm containment.

## Post-Incident Steps

1. Attach root-cause analysis and affected timeframe.
2. Link remediation commit(s).
3. Add prevention actions and due dates.
4. Update gate policy if policy gap is identified.
