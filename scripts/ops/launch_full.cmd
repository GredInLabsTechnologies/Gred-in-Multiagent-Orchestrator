@echo off
:: =====================================================================
:: GIMO SECURE UNIFIED LAUNCHER (Windows)
:: =====================================================================
TITLE GIMO Secure Launcher
setlocal enabledelayedexpansion

echo [1/5] Preparando entorno...
set "ROOT_DIR=%~dp0..\.."
cd /d "%ROOT_DIR%"

:: 1. Detect Virtual Environment
set "PYTHON_EXE=python"
if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
) else if exist "venv\Scripts\python.exe" (
    set "PYTHON_EXE=venv\Scripts\python.exe"
)

:: 2. Verificar/Generar ORCH_TOKEN
set ENV_FILE=.env
if not exist "%ENV_FILE%" (
    echo [INFO] .env no encontrado. Inicializando...
    echo ORCH_PORT=9325 > "%ENV_FILE%"
)

findstr "ORCH_TOKEN" "%ENV_FILE%" >nul
if errorlevel 1 (
    echo [INFO] Generando ORCH_TOKEN de alta entropía...
    for /f %%T in ('powershell -NoProfile -Command "$bytes = New-Object byte[] 32; [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes); [Convert]::ToBase64String($bytes)"') do set "GENERATED_TOKEN=%%T"
    echo ORCH_TOKEN=!GENERATED_TOKEN!>> "%ENV_FILE%"
    
    :: Sync token with Frontend (Vite)
    echo VITE_ORCH_TOKEN=!GENERATED_TOKEN!> "tools\orchestrator_ui\.env.local"
)

:: 3. Limpiar procesos previos
echo [2/5] Limpiando puertos 9325 (Backend) y 5173 (Frontend)...
for %%p in (9325 5173) do (
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr :%%p ^| findstr LISTENING') do (
        taskkill /F /PID %%a >nul 2>&1
    )
)

:: 4. Lanzar Backend
echo [3/5] Lanzando GIMO Backend (127.0.0.1:9325)...
start "GIMO Backend" cmd /c "title GIMO Backend && %PYTHON_EXE% -m uvicorn tools.gimo_server.main:app --host 127.0.0.1 --port 9325 --log-level info"

:: 5. Esperar Backend Health Check (Optional, scripts/dev/health_check.py might be missing if cleaned up)
:: echo [4/5] Esperando a que el Backend esté listo...
:: %PYTHON_EXE% scripts\dev\health_check.py --port 9325 --timeout 30

:: 6. Lanzar Frontend
echo [5/5] Iniciando GIMO Frontend (Vite)...
cd tools\orchestrator_ui
start "GIMO Frontend" cmd /c "title GIMO Frontend && npm run dev -- --host 127.0.0.1"

echo.
echo [SUCCESS] GIMO está operativo! 🚀
echo.
echo  - Backend: http://127.0.0.1:9325
echo  - Frontend: http://127.0.0.1:5173
echo.
timeout /t 3 /nobreak >nul
start http://127.0.0.1:5173

exit
