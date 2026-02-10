param(
    [Parameter(Mandatory = $true)]
    [string]$RepoPath,
    [string]$OrchToken,
    [string]$RepoRoot,
    [string]$ApiBase = "http://127.0.0.1:9325"
)

$resolvedRepo = (Resolve-Path $RepoPath).Path
$resolvedRoot = (Resolve-Path $RepoRoot).Path

if (-not $resolvedRepo.StartsWith($resolvedRoot)) {
    Write-Host "Repo fuera del root permitido: $resolvedRoot" -ForegroundColor Red
    exit 1
}

if (-not $OrchToken) {
    Write-Host "ORCH_TOKEN requerido (usa -OrchToken)." -ForegroundColor Red
    exit 1
}

$headers = @{ Authorization = "Bearer $OrchToken" }
$encoded = [System.Web.HttpUtility]::UrlEncode($resolvedRepo)

Write-Host "Vitaminizando repo: $resolvedRepo" -ForegroundColor Cyan
Invoke-RestMethod -Method Post -Uri "$ApiBase/ui/repos/vitaminize?path=$encoded" -Headers $headers | Out-Null

Write-Host "Repo activado y listo. Abriendo Explorer..." -ForegroundColor Green
Invoke-RestMethod -Method Post -Uri "$ApiBase/ui/repos/open?path=$encoded" -Headers $headers | Out-Null
