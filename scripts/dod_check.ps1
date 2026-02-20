param(
  [string]$RepoRoot = "."
)

$ErrorActionPreference = "Stop"

function Assert-FileExists {
  param([string]$Path)
  if (-not (Test-Path $Path)) {
    throw "Missing required file: $Path"
  }
}

function Assert-FileContains {
  param([string]$Path, [string]$Pattern)
  $content = Get-Content -Path $Path -Raw -Encoding UTF8
  if ($content -notmatch $Pattern) {
    throw "File does not contain required pattern [$Pattern]: $Path"
  }
}

Set-Location $RepoRoot

$requiredFiles = @(
  "doc/07-autonomous-agent-sdlc-architecture.md",
  "autonomous/state_machine.md",
  "memory/schema.sql",
  "policy/gate_policy.yaml",
  "policy/slot_policy.yaml",
  "config/retrieval_budget.yaml",
  "runbooks/rollback.md",
  "runbooks/incident.md",
  "scripts/dod_check.ps1"
)

foreach ($f in $requiredFiles) {
  Assert-FileExists $f
}

Assert-FileContains "memory/schema.sql" "tenant_id"
Assert-FileContains "memory/schema.sql" "project_id"
Assert-FileContains "memory/schema.sql" "event_seq"
Assert-FileContains "autonomous/state_machine.md" "FailedExhausted"
Assert-FileContains "autonomous/state_machine.md" "FailedHard"
Assert-FileContains "autonomous/state_machine.md" "Killed"
Assert-FileContains "policy/gate_policy.yaml" "burn_rate_windows"
Assert-FileContains "policy/gate_policy.yaml" "min_sample_count"
Assert-FileContains "runbooks/rollback.md" "Trigger Conditions"
Assert-FileContains "runbooks/rollback.md" "Execution Steps"
Assert-FileContains "runbooks/rollback.md" "Verification Steps"
Assert-FileContains "runbooks/rollback.md" "Recovery Steps"

Write-Output "DoD check passed."
exit 0
