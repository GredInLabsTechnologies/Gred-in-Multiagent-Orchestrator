@echo off
TITLE GIL Orchestrator - Managed Service
setlocal enabledelayedexpansion

REM Directorio donde está este .cmd
set "SCRIPT_DIR=%~dp0"
REM Normaliza: quita \ final
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

REM scripts\ops\start_orch.cmd -> subir dos para llegar a repo root
set "BASE_DIR=%SCRIPT_DIR%\..\.."
pushd "%BASE_DIR%" || (echo ERROR: no puedo entrar en "%BASE_DIR%" & exit /b 1)

set ENV_FILE=.env
set FOUND_TOKEN=0

if exist "%ENV_FILE%" (
    for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%ENV_FILE%") do (
        if /I "%%A"=="ORCH_TOKEN" (
            set ORCH_TOKEN=%%B
            set FOUND_TOKEN=1
        )
    )
)

if "%ORCH_TOKEN%"=="" (
    echo [INFO] ORCH_TOKEN no encontrado. Generando uno nuevo...
    for /f %%T in ('powershell -NoProfile -Command "$bytes = New-Object byte[] 32; [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes); [Convert]::ToBase64String($bytes)"') do set ORCH_TOKEN=%%T
    if "%FOUND_TOKEN%"=="0" (
        echo ORCH_TOKEN=%ORCH_TOKEN%>> "%ENV_FILE%"
    ) else (
        echo ORCH_TOKEN=%ORCH_TOKEN%> "%ENV_FILE%"
    )
    echo [OK] Token guardado en %ENV_FILE%
)

echo [HARDENING] Checking for existing instances on port 9325...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :9325 ^| findstr LISTENING') do (
    echo [CLEANUP] Found zombie/previous process (PID %%a). Terminating...
    taskkill /F /PID %%a >nul 2>&1
)

echo [START] Launching GIL Orchestrator...
REM Asumiendo que estamos en modo dev con python instalado.
REM Si es producción, el instalador debería apuntar al .exe
uvicorn tools.gimo_server.main:app --host 127.0.0.1 --port 9325

popd
endlocal
