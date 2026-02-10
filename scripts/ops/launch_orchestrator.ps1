$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $root

$env:PYTHONPATH = $root

$envFile = Join-Path $root ".env"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        if ($_ -match "^\s*#") { return }
        if ($_ -match "^\s*$") { return }
        $parts = $_ -split "=", 2
        if ($parts.Length -eq 2) {
            $name = $parts[0].Trim()
            $value = $parts[1].Trim()
            if ($name -eq "ORCH_TOKEN" -and -not [string]::IsNullOrWhiteSpace($value)) {
                $env:ORCH_TOKEN = $value
            }
        }
    }
}

if ([string]::IsNullOrWhiteSpace($env:ORCH_TOKEN)) {
    Write-Host "[INFO] ORCH_TOKEN no encontrado. Generando uno nuevo..."
    $bytes = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $env:ORCH_TOKEN = [Convert]::ToBase64String($bytes)
    "ORCH_TOKEN=$($env:ORCH_TOKEN)" | Out-File -FilePath $envFile -Append -Encoding UTF8
    Write-Host "[OK] Token guardado en $envFile"
}

# Host local-only (seguridad por defecto)
uvicorn tools.gimo_server.main:app --host 127.0.0.1 --port 9325 --reload
