@echo off
setlocal enabledelayedexpansion

REM Directorio donde está este .bat
set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

REM scripts\ops\run_as_service.bat -> subir dos para llegar a REPO_ROOT
set "REPO_ROOT=%SCRIPT_DIR%\..\.."
set "VENV_BIN=%REPO_ROOT%\.venv\Scripts"
set "PYTHON_EXE=%VENV_BIN%\python.exe"

if not exist "%PYTHON_EXE%" (
    set "PYTHON_EXE=python.exe"
)

set "PYTHONPATH=%REPO_ROOT%"
set "ENV_FILE=%REPO_ROOT%\.env"

if exist "%ENV_FILE%" (
    for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%ENV_FILE%") do (
        if /I "%%A"=="ORCH_TOKEN" set "ORCH_TOKEN=%%B"
    )
)

set "LOG_FILE=%REPO_ROOT%\logs\service_log.txt"
if not exist "%REPO_ROOT%\logs" mkdir "%REPO_ROOT%\logs"

if "%ORCH_TOKEN%"=="" (
    echo [%DATE% %TIME%] ORCH_TOKEN no encontrado. >> "%LOG_FILE%"
    for /f %%T in ('powershell -NoProfile -Command "$bytes = New-Object byte[] 32; [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes); [Convert]::ToBase64String($bytes)"') do set "ORCH_TOKEN=%%T"
    echo ORCH_TOKEN=%ORCH_TOKEN%>> "%ENV_FILE%"
    echo [%DATE% %TIME%] Token guardado en %ENV_FILE% >> "%LOG_FILE%"
)

cd /d "%REPO_ROOT%"

echo [%DATE% %TIME%] ISOLATED START >> "%LOG_FILE%"
"%PYTHON_EXE%" -m uvicorn tools.gimo_server.main:app --host 127.0.0.1 --port 9325 >> "%LOG_FILE%" 2>&1
if %ERRORLEVEL% neq 0 (
    echo [%DATE% %TIME%] Exit Code: %ERRORLEVEL% >> "%LOG_FILE%"
)
endlocal
