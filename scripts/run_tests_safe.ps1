param(
  [Parameter(Position = 0, ValueFromRemainingArguments = $true)]
  [string[]]$Targets
)

$ErrorActionPreference = "Stop"

$baseTemp = "scratch/pytest_tmp_runtime"
$pytestArgs = @(
  "-q",
  "-p", "no:cacheprovider",
  "--basetemp=$baseTemp"
)

if ($Targets -and $Targets.Count -gt 0) {
  $pytestArgs += $Targets
}

$venvPython = ".\.venv\Scripts\python.exe"
if (Test-Path $venvPython) {
  Write-Host "[run_tests_safe] $venvPython -m pytest $($pytestArgs -join ' ')"
  & $venvPython -m pytest @pytestArgs
  exit $LASTEXITCODE
}

$uvArgs = @("--cache-dir", ".uv_cache", "run", "python", "-m", "pytest") + $pytestArgs
Write-Host "[run_tests_safe] uv $($uvArgs -join ' ')"
& uv @uvArgs
exit $LASTEXITCODE
