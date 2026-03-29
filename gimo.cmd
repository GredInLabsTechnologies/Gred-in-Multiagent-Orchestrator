@echo off
setlocal EnableDelayedExpansion

:: =====================================================================
::  GIMO CLI — Unified Launcher
::  Usage:  gimo [up|down|restart|doctor|bootstrap|mcp|help]
:: =====================================================================

set "ROOT_DIR=%~dp0"
cd /d "%ROOT_DIR%" || (echo [ERROR] No se pudo entrar al repo root & exit /b 1)

set "PYTHON_EXE=.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"

set "CMD=%~1"
if "%CMD%"=="" set "CMD=up"

:: Collect extra args (e.g. --no-web)
set "EXTRA_ARGS="
shift
:parse_args
if "%~1"=="" goto :done_args
set "EXTRA_ARGS=!EXTRA_ARGS! %~1"
shift
goto :parse_args
:done_args

if /I "%CMD%"=="up"        goto :cmd_up
if /I "%CMD%"=="start"     goto :cmd_up
if /I "%CMD%"=="down"      goto :cmd_down
if /I "%CMD%"=="stop"      goto :cmd_down
if /I "%CMD%"=="doctor"    goto :cmd_doctor
if /I "%CMD%"=="bootstrap" goto :cmd_bootstrap
if /I "%CMD%"=="mcp"       goto :cmd_mcp
if /I "%CMD%"=="claude"    goto :cmd_claude
if /I "%CMD%"=="help"      goto :cmd_help
if /I "%CMD%"=="-h"        goto :cmd_help
if /I "%CMD%"=="--help"    goto :cmd_help

echo [ERROR] Comando desconocido: %CMD%
goto :cmd_help

:: =============================================================
::  UP — Interactive launcher with multiplexed logs
:: =============================================================
:cmd_up
TITLE GIMO

:: Auto-bootstrap if environment incomplete
set "NEED_BOOTSTRAP=0"
if not exist ".venv\Scripts\python.exe" set "NEED_BOOTSTRAP=1"
if not exist ".venv\pyvenv.cfg" set "NEED_BOOTSTRAP=1"
if not exist "tools\orchestrator_ui\node_modules" set "NEED_BOOTSTRAP=1"

if "!NEED_BOOTSTRAP!"=="1" (
    echo [INFO] Entorno incompleto. Ejecutando bootstrap...
    call :do_bootstrap || exit /b 1
    set "PYTHON_EXE=.venv\Scripts\python.exe"
)

:: Sync .env.local
call :sync_env_local

:: Launch interactive Python process manager
"%PYTHON_EXE%" scripts\dev\launcher.py !EXTRA_ARGS!
exit /b %ERRORLEVEL%

:: =============================================================
::  DOWN — Kill all GIMO processes and free ports
:: =============================================================
:cmd_down
TITLE GIMO Down
echo [1/2] Cerrando procesos GIMO...
taskkill /F /FI "WINDOWTITLE eq GIMO*" /T >nul 2>&1

echo [2/2] Liberando puertos 9325, 5173, 3000...
"%PYTHON_EXE%" scripts\ops\kill_port.py 9325 5173 3000 >nul 2>&1

echo [OK] GIMO detenido.
exit /b 0

:: =============================================================
::  DOCTOR — Check prerequisites and health
:: =============================================================
:cmd_doctor
TITLE GIMO Doctor
echo.
echo =======================================================
echo   GIMO Doctor
echo =======================================================

set "FAIL=0"
call :check_tool git "git --version"
call :check_tool node "node --version"
call :check_tool npm "npm --version"
call :check_tool python "python --version"

where codex >nul 2>&1 && (
    for /f "delims=" %%V in ('codex --version 2^>nul') do echo [OK] codex %%V
) || echo [INFO] codex CLI no instalado ^(opcional^)

where claude >nul 2>&1 && (
    for /f "delims=" %%V in ('claude --version 2^>nul') do echo [OK] claude %%V
) || echo [INFO] claude CLI no instalado ^(opcional^)

if exist ".venv\Scripts\python.exe" (echo [OK] .venv) else (echo [WARN] .venv no existe. Ejecuta: gimo bootstrap)
if exist ".env" (echo [OK] .env) else (echo [WARN] .env ausente. Ejecuta: gimo bootstrap)
if exist "tools\orchestrator_ui\.env.local" (echo [OK] UI .env.local) else (echo [WARN] UI .env.local ausente)

powershell -NoProfile -Command "try { $r=Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:9325/auth/check' -TimeoutSec 2; Write-Output ('[OK] Backend responde (HTTP ' + $r.StatusCode + ')') } catch { Write-Output '[INFO] Backend no responde en 9325' }"

echo.
if "!FAIL!"=="1" (
    echo [ACTION] Faltan herramientas. Instala prerequisitos.
    exit /b 1
)
echo [OK] Doctor OK.
exit /b 0

:: =============================================================
::  BOOTSTRAP
:: =============================================================
:cmd_bootstrap
call :do_bootstrap
exit /b %ERRORLEVEL%

:do_bootstrap
TITLE GIMO Bootstrap
set "VIRTUAL_ENV="
set "PYTHONHOME="
set "PYTHONPATH="

echo.
echo =======================================================
echo   GIMO Bootstrap
echo =======================================================

where git >nul 2>&1 || (echo [ERROR] git no esta en PATH & exit /b 1)
where npm >nul 2>&1 || (echo [ERROR] npm no esta en PATH & exit /b 1)

set "PY_BOOTSTRAP="
where py >nul 2>&1
if not errorlevel 1 (
    py -3.11 -c "import sys; print(sys.version_info.major)" >nul 2>&1
    if not errorlevel 1 set "PY_BOOTSTRAP=py -3.11"
    if not defined PY_BOOTSTRAP (
        py -3 -c "import sys; print(sys.version_info.major)" >nul 2>&1
        if not errorlevel 1 set "PY_BOOTSTRAP=py -3"
    )
)
if not defined PY_BOOTSTRAP (
    where python >nul 2>&1 || (echo [ERROR] Python 3.x no encontrado & exit /b 1)
    for /f %%V in ('python -c "import sys; print(sys.version_info.major)"') do (
        if "%%V"=="3" set "PY_BOOTSTRAP=python"
    )
)
if not defined PY_BOOTSTRAP (echo [ERROR] Python 3.x no disponible & exit /b 1)

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "import sys" >nul 2>&1
    if errorlevel 1 (
        echo [WARN] .venv corrupto. Recreando...
        rmdir /s /q ".venv" >nul 2>&1
    )
)
if not exist ".venv\Scripts\python.exe" (
    echo [1/6] Creando .venv ...
    %PY_BOOTSTRAP% -m venv .venv || (echo [ERROR] Fallo crear .venv & exit /b 1)
)
set "PYTHON_EXE=.venv\Scripts\python.exe"

echo [2/6] Instalando deps Python ...
"%PYTHON_EXE%" -m pip install --upgrade pip setuptools wheel >nul 2>&1
"%PYTHON_EXE%" -m pip install -r requirements.txt || (echo [ERROR] pip install fallo & exit /b 1)

echo [3/6] Instalando deps UI ...
pushd tools\orchestrator_ui >nul
npm ci || (popd >nul & echo [ERROR] npm ci fallo en UI & exit /b 1)
popd >nul

echo [4/6] Instalando deps Web ...
pushd apps\web >nul
npm ci || (popd >nul & echo [ERROR] npm ci fallo en web & exit /b 1)
popd >nul

echo [5/6] Preparando .env ...
if not exist ".env" copy /Y ".env.example" ".env" >nul
set "ORCH_TOKEN="
if exist ".env" (
    for /f "usebackq eol=# tokens=1,* delims==" %%A in (".env") do (
        if /I "%%A"=="ORCH_TOKEN" set "ORCH_TOKEN=%%B"
    )
)
if "!ORCH_TOKEN!"=="" (
    for /f %%T in ('powershell -NoProfile -Command "$b=New-Object byte[] 32; [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); [Convert]::ToBase64String($b)"') do set "ORCH_TOKEN=%%T"
    >> ".env" echo ORCH_TOKEN=!ORCH_TOKEN!
)
call :sync_env_local

echo [6/6] Registrando MCP server ...
"%PYTHON_EXE%" scripts\setup_mcp.py >nul 2>&1

echo.
echo [OK] Bootstrap completado. Ejecuta: gimo
exit /b 0

:: =============================================================
::  MCP — Standalone MCP server
:: =============================================================
:cmd_mcp
TITLE GIMO MCP Server
set "PYTHONUNBUFFERED=1"
echo =======================================================
echo   GIMO MCP Server ^(SSE^) — http://localhost:8000/mcp/sse
echo =======================================================
"%PYTHON_EXE%" -m uvicorn tools.gimo_server.main:create_app --factory --host 0.0.0.0 --port 8000
exit /b %ERRORLEVEL%

:: =============================================================
::  CLAUDE — Launch Claude Code CLI
:: =============================================================
:cmd_claude
TITLE GIMO Claude
powershell -ExecutionPolicy Bypass -Command "claude !EXTRA_ARGS!"
exit /b %ERRORLEVEL%

:: =============================================================
::  HELP
:: =============================================================
:cmd_help
echo.
echo   GIMO CLI
echo.
echo   Usage:  gimo [command] [options]
echo.
echo   Commands:
echo     up, start      Lanza todo ^(interactive, logs unificados^)
echo     down, stop     Para todos los servicios
echo     doctor         Verifica prerequisitos
echo     bootstrap      Setup completo del entorno
echo     mcp            MCP server standalone ^(puerto 8000^)
echo     help           Muestra esta ayuda
echo.
echo   Options for 'up':
echo     --no-web       No lanzar apps/web
echo     --no-frontend  No lanzar la UI
echo     --backend-only Solo backend
echo.
exit /b 0

:: =============================================================
::  Helpers
:: =============================================================
:sync_env_local
set "ORCH_TOKEN="
if exist ".env" (
    for /f "usebackq eol=# tokens=1,* delims==" %%A in (".env") do (
        if /I "%%A"=="ORCH_TOKEN" set "ORCH_TOKEN=%%B"
    )
)
(
    echo VITE_API_URL=http://127.0.0.1:9325
    if defined ORCH_TOKEN echo VITE_ORCH_TOKEN=!ORCH_TOKEN!
) > "tools\orchestrator_ui\.env.local"

set "FB_VARS=API_KEY AUTH_DOMAIN PROJECT_ID STORAGE_BUCKET MESSAGING_SENDER_ID APP_ID"
for %%V in (%FB_VARS%) do (
    set "FB_%%V="
    if exist ".env" (
        for /f "usebackq eol=# tokens=1,* delims==" %%A in (".env") do (
            if /I "%%A"=="VITE_FIREBASE_%%V" set "FB_%%V=%%B"
            if /I "%%A"=="FIREBASE_%%V" if not defined FB_%%V set "FB_%%V=%%B"
            if /I "%%A"=="NEXT_PUBLIC_FIREBASE_%%V" if not defined FB_%%V set "FB_%%V=%%B"
        )
    )
    if defined FB_%%V >> "tools\orchestrator_ui\.env.local" echo VITE_FIREBASE_%%V=!FB_%%V!
)
goto :eof

:check_tool
set "TOOL_NAME=%~1"
set "TOOL_CMD=%~2"
where %TOOL_NAME% >nul 2>&1
if errorlevel 1 (
    echo [ERROR] %TOOL_NAME% no esta en PATH
    set "FAIL=1"
    goto :eof
)
for /f "delims=" %%V in ('%TOOL_CMD% 2^>nul') do (
    echo [OK] %%V
    goto :eof
)
echo [OK] %TOOL_NAME% detectado
goto :eof
