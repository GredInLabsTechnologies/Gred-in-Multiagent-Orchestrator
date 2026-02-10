param(
    [switch]$IncludeOrchData = $false
)

$ErrorActionPreference = "Stop"

function Remove-IfExists([string]$Path) {
    if (Test-Path $Path) {
        Write-Host "Removing $Path"
        Remove-Item -Recurse -Force $Path
    }
}

# Python / runtime artifacts
Remove-IfExists ".pytest_cache"
Remove-IfExists "htmlcov"
Remove-IfExists ".coverage"
Get-ChildItem -Recurse -Force -ErrorAction SilentlyContinue -Filter "__pycache__" |
    ForEach-Object { Remove-Item -Recurse -Force $_.FullName }

Remove-IfExists ".orch_snapshots"
if ($IncludeOrchData) {
    Remove-IfExists ".orch_data"
}

# UI artifacts
Remove-IfExists "tools/orchestrator_ui/coverage"
Remove-IfExists "tools/orchestrator_ui/dist"
Remove-IfExists "tools/orchestrator_ui/.turbo"
Remove-IfExists "tools/orchestrator_ui/.vite"

# Generated metrics (generated output should live under out/metrics or artifacts/metrics)
Remove-IfExists "out/metrics"
Remove-IfExists "artifacts/metrics"

Write-Host "Clean completed."
