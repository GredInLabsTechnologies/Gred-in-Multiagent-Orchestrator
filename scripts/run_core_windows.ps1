#Requires -Version 5.0
<#
.SYNOPSIS
    Arranca GIMO Core en Windows usando un Python standalone no-sandboxed.

.DESCRIPTION
    El Python de Microsoft Store corre en AppContainer y reescribe
    silenciosamente bind(0.0.0.0) a 127.0.0.1 - incapaz de servir LAN.
    Este launcher:
      1. Descarga un python-build-standalone MSVC (~30 MiB) la primera vez
         y lo cachea en %LOCALAPPDATA%\gimo\core-python\
      2. Instala las deps minimas del Core en un site-packages local la
         primera vez
      3. Lanza `python -m tools.gimo_server.main` con ese Python, NO
         sandboxed, bind LAN real

.PARAMETER Role
    "server" (bind 0.0.0.0 + mDNS) o "client" (loopback).

.PARAMETER Port
    Puerto TCP del Core. Default 9325.

.PARAMETER DeviceId
    ID del device para el bootstrap host. Default hostname.

.PARAMETER Force
    Fuerza redescarga y reinstalacion aunque ya haya cache.

.EXAMPLE
    .\scripts\run_core_windows.ps1 -Role server

.EXAMPLE
    .\scripts\run_core_windows.ps1 -Role server -Force

.NOTES
    - Sin permisos admin - todo en %LOCALAPPDATA%
    - El token ORCH_TOKEN se lee de .orch_token del repo o env var
    - Reusable: siguientes arranques son instantaneos (cache hit)
#>
param(
    [string]$Role = "server",
    [int]$Port = 9325,
    [string]$DeviceId = "",
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$CacheRoot = Join-Path $env:LOCALAPPDATA "gimo\core-python"
$PythonRelease = "20260414"
$PythonVersion = "3.13.13"
$Asset = "cpython-$PythonVersion+$PythonRelease-x86_64-pc-windows-msvc-install_only.tar.gz"
$AssetUrl = "https://github.com/astral-sh/python-build-standalone/releases/download/$PythonRelease/$Asset"
$PythonDir = Join-Path $CacheRoot "python-$PythonRelease"
$PythonExe = Join-Path $PythonDir "python.exe"
$SitePkg = Join-Path $CacheRoot "site-packages"
$MarkerFile = Join-Path $CacheRoot ".setup-complete-$PythonRelease"

if ($DeviceId -eq "") {
    $DeviceId = $env:COMPUTERNAME.ToLower()
}

function Write-Step($msg) {
    Write-Host "[gimo-core] " -NoNewline -ForegroundColor Cyan
    Write-Host $msg
}

function Write-Warn($msg) {
    Write-Host "[gimo-core] " -NoNewline -ForegroundColor Yellow
    Write-Host $msg -ForegroundColor Yellow
}

# Step 1: Fetch + extract Python standalone
if ($Force -or -not (Test-Path $PythonExe)) {
    Write-Step "Python standalone $PythonVersion not cached, fetching..."
    New-Item -ItemType Directory -Force -Path $CacheRoot | Out-Null
    $TarballPath = Join-Path $CacheRoot $Asset
    if ($Force -or -not (Test-Path $TarballPath)) {
        Invoke-WebRequest -Uri $AssetUrl -OutFile $TarballPath
    }

    Write-Step "Extracting $Asset..."
    if (Test-Path $PythonDir) {
        Remove-Item -Recurse -Force $PythonDir
    }
    $ExtractTmp = Join-Path $CacheRoot "extract-tmp"
    if (Test-Path $ExtractTmp) { Remove-Item -Recurse -Force $ExtractTmp }
    New-Item -ItemType Directory -Force -Path $ExtractTmp | Out-Null

    # Windows 10+ ships bsdtar at System32\tar.exe. NO usar `tar` generic del
    # PATH porque git-bash expone el MSYS2 tar que NO acepta paths Windows.
    $WinTar = Join-Path $env:SystemRoot "System32\tar.exe"
    if (Test-Path $WinTar) {
        & $WinTar -xzf $TarballPath -C $ExtractTmp
        if ($LASTEXITCODE -ne 0) {
            throw "tar extraction failed with exit $LASTEXITCODE"
        }
    } else {
        # Fallback Python stdlib — funciona en cualquier Python que haga falta.
        # Usamos el propio Python standalone tras un bootstrap minimal, o el
        # Store Python si existe.
        $BootstrapPy = (Get-Command python -ErrorAction SilentlyContinue).Source
        if (-not $BootstrapPy) {
            throw "No tar.exe in Windows\System32 and no python in PATH to extract $Asset"
        }
        & $BootstrapPy -c "import tarfile, sys; tarfile.open(sys.argv[1]).extractall(sys.argv[2])" $TarballPath $ExtractTmp
        if ($LASTEXITCODE -ne 0) {
            throw "Python tarfile extraction failed with exit $LASTEXITCODE"
        }
    }

    Move-Item -Path (Join-Path $ExtractTmp "python") -Destination $PythonDir
    Remove-Item -Recurse -Force $ExtractTmp

    if (-not (Test-Path $PythonExe)) {
        throw "Python extraction failed - $PythonExe not present"
    }
    Write-Step "Python standalone ready at $PythonExe"
} else {
    Write-Step "Python cache hit: $PythonExe"
}

# Step 2: Install minimum deps (once)
$RequirementsPath = Join-Path $RepoRoot "requirements.txt"
if ($Force -or -not (Test-Path $MarkerFile)) {
    Write-Step "Installing Core deps into $SitePkg (first run, ~1-2 min)..."
    if (Test-Path $SitePkg) { Remove-Item -Recurse -Force $SitePkg }
    New-Item -ItemType Directory -Force -Path $SitePkg | Out-Null

    & $PythonExe -m pip install --upgrade pip --quiet --target $SitePkg --no-warn-script-location
    & $PythonExe -m pip install --quiet --target $SitePkg --no-warn-script-location -r $RequirementsPath
    if ($LASTEXITCODE -ne 0) {
        throw "pip install failed with exit $LASTEXITCODE"
    }

    Set-Content -Path $MarkerFile -Value "complete $PythonVersion $(Get-Date -Format o)"
    Write-Step "Deps installed."
} else {
    Write-Step "Deps cache hit (markerfile present)."
}

# Step 3: Resolve ORCH_TOKEN
$Token = $env:ORCH_TOKEN
if ([string]::IsNullOrEmpty($Token)) {
    $TokenFile = Join-Path $RepoRoot ".orch_token"
    if (Test-Path $TokenFile) {
        $Token = (Get-Content $TokenFile -Raw).Trim()
        Write-Step "ORCH_TOKEN loaded from .orch_token"
    } else {
        Write-Warn "ORCH_TOKEN not set and no .orch_token file; the server will refuse most routes."
    }
}

# Step 4: Launch Core
# pywin32 ships its critical DLLs (pywintypes313.dll, pythoncom313.dll) in
# site-packages/pywin32_system32/. They are loaded via Windows DLL search
# path, not Python import path - so PATH must include that dir or the first
# `import pywintypes` raises ModuleNotFoundError.
$Pywin32DllDir = Join-Path $SitePkg "pywin32_system32"
if (Test-Path $Pywin32DllDir) {
    $env:PATH = "$Pywin32DllDir;$env:PATH"
}
# win32/ and Pythonwin/ subdirs also need to be on PYTHONPATH because
# pywin32 uses non-standard layouts.
$Pywin32Lib = Join-Path $SitePkg "win32"
$Pywin32Lib2 = Join-Path $SitePkg "win32\lib"
$PythonwinDir = Join-Path $SitePkg "Pythonwin"
$env:PYTHONPATH = "$SitePkg;$Pywin32Lib;$Pywin32Lib2;$PythonwinDir;$RepoRoot"
$env:ORCH_TOKEN = $Token
# DEBUG=true habilita bypass del integrity manifest para runs sin firma
# productiva (setup de dev). El reload auto de watchfiles se deshabilita
# explicitamente en main.py cuando role=server para evitar que los writes
# en .orch_data/ causen restart loops.
$env:DEBUG = "true"
$env:ORCH_LICENSE_ALLOW_DEBUG_BYPASS = "true"
$env:GIMO_MESH_HOST_ENABLED = "true"
$env:GIMO_MESH_HOST_DEVICE_ID = $DeviceId
$env:GIMO_MESH_HOST_DEVICE_MODE = $Role
$env:GIMO_MESH_HOST_DEVICE_CLASS = "desktop"
if ($Role -eq "server") {
    $env:ORCH_MDNS_ENABLED = "true"
} else {
    $env:ORCH_MDNS_ENABLED = "false"
}

Write-Step "Launching GIMO Core:"
Write-Host "    python  = $PythonExe"
Write-Host "    role    = $Role"
Write-Host "    port    = $Port"
Write-Host "    device  = $DeviceId"
Write-Host "    repo    = $RepoRoot"
Write-Host ""

Set-Location $RepoRoot
& $PythonExe -m tools.gimo_server.main --role $Role --mesh-host-id $DeviceId --mesh-host-class desktop --port $Port
exit $LASTEXITCODE
