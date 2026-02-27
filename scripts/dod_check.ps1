param(
  [string]$RepoRoot = ".",
  [switch]$RunFullClosureChain,
  [switch]$ClosureQuickMode,
  [int]$ClosureTimeoutSeconds = 2400,
  [string]$ClosureOutput = "scratch/reports/release_closure_chain_full_m0_m7_ci.json"
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

function Get-PythonRuntime {
  $venvPython = ".\.venv\Scripts\python.exe"
  if (Test-Path $venvPython) {
    return @{
      Exe = $venvPython
      PrefixArgs = @()
    }
  }

  $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
  if ($pythonCmd) {
    return @{
      Exe = $pythonCmd.Source
      PrefixArgs = @()
    }
  }

  $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
  if ($pyLauncher) {
    return @{
      Exe = $pyLauncher.Source
      PrefixArgs = @("-3")
    }
  }

  throw "Python runtime not found (.venv/python, python, or py -3)."
}

function Invoke-FullClosureChain {
  param(
    [switch]$QuickMode,
    [int]$TimeoutSeconds,
    [string]$OutputPath
  )

  $runtime = Get-PythonRuntime
  $timeout = [Math]::Max(30, [int]$TimeoutSeconds)

  $args = @()
  $args += $runtime.PrefixArgs
  $args += @(
    "scripts/release_closure_chain_full_m0_m7.py",
    "--timeout-seconds", "$timeout",
    "--output", "$OutputPath"
  )
  if ($QuickMode) {
    $args += "--quick-mode"
  }

  Write-Output "[dod_check] Running closure chain: $($runtime.Exe) $($args -join ' ')"
  & $runtime.Exe @args
  if ($LASTEXITCODE -ne 0) {
    throw "release_closure_chain_full_m0_m7 failed with exit code: $LASTEXITCODE"
  }
}

Set-Location $RepoRoot

$requiredFiles = @(
  "doc/07-autonomous-agent-sdlc-architecture.md",
  "autonomous/state_machine.md",
  "memory/schema.sql",
  "storage_schema/brainstem_event_workflow.sql",
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

Assert-FileContains "storage_schema/brainstem_event_workflow.sql" "tenant_id"
Assert-FileContains "storage_schema/brainstem_event_workflow.sql" "project_id"
Assert-FileContains "storage_schema/brainstem_event_workflow.sql" "event_seq"
Assert-FileContains "memory/schema.sql" "storage_schema/brainstem_event_workflow.sql"
Assert-FileContains "autonomous/state_machine.md" "FailedExhausted"
Assert-FileContains "autonomous/state_machine.md" "FailedHard"
Assert-FileContains "autonomous/state_machine.md" "Killed"
Assert-FileContains "policy/gate_policy.yaml" "burn_rate_windows"
Assert-FileContains "policy/gate_policy.yaml" "min_sample_count"
Assert-FileContains "runbooks/rollback.md" "Trigger Conditions"
Assert-FileContains "runbooks/rollback.md" "Execution Steps"
Assert-FileContains "runbooks/rollback.md" "Verification Steps"
Assert-FileContains "runbooks/rollback.md" "Recovery Steps"

if ($RunFullClosureChain) {
  Invoke-FullClosureChain `
    -QuickMode:$ClosureQuickMode `
    -TimeoutSeconds $ClosureTimeoutSeconds `
    -OutputPath $ClosureOutput
}

Write-Output "DoD check passed."
exit 0
