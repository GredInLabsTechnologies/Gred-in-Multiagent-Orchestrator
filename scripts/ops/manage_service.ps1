$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BaseDir = Resolve-Path (Join-Path $ScriptDir "..")

# Ajusta a TU ruta real del exe instalado (o del script si usas python)
# Por defecto apuntamos al .exe que genera PyInstaller en scripts/
$ServiceExe = Join-Path $ScriptDir "Gred_Orchestrator.exe"

if (-not (Test-Path $ServiceExe)) {
    # Fallback para desarrollo
    $ServiceExe = "uvicorn.exe" # O ruta completa si se conoce
    Write-Warning "Ejecutable Gred_Orchestrator.exe no encontrado. Usando fallback."
}

$ServiceName = "GILOrchestrator"

function Service-Exists([string]$name) {
    $null -ne (Get-Service -Name $name -ErrorAction SilentlyContinue)
}

if ($args.Count -eq 0) {
    Write-Host "Usage: .\manage_service.ps1 [install | uninstall | start | stop | status | restart]" -ForegroundColor Yellow
    exit
}

$action = $args[0].ToLower()

switch ($action) {
    "install" {
        if (-not (Service-Exists $ServiceName)) {
            # LocalSystem (lo más simple y portable)
            sc.exe create $ServiceName binPath= "`"$ServiceExe`"" start= auto obj= "LocalSystem"
            Write-Host "Servicio $ServiceName creado."
        }
        else {
            Write-Host "El servicio $ServiceName ya existe."
        }
    }
    "uninstall" {
        if (Service-Exists $ServiceName) {
            sc.exe stop $ServiceName
            sc.exe delete $ServiceName
            Write-Host "Servicio $ServiceName eliminado."
        }
    }
    "start" {
        sc.exe start $ServiceName
    }
    "stop" {
        sc.exe stop $ServiceName
    }
    "status" {
        sc.exe query $ServiceName
    }
    "restart" {
        sc.exe stop $ServiceName
        Start-Sleep -Seconds 2
        sc.exe start $ServiceName
    }
    default {
        Write-Host "Accion desconocida: $action"
    }
}
