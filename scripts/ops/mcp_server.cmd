@echo off
:: =====================================================================
:: GIMO SECURE MCP SERVER LAUNCHER (Windows)
:: =====================================================================
TITLE GIMO MCP Server

set "ROOT_DIR=%~dp0..\.."
cd /d "%ROOT_DIR%"

:: 1. Detect Virtual Environment
set "PYTHON_EXE=python"
if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
) else if exist "venv\Scripts\python.exe" (
    set "PYTHON_EXE=venv\Scripts\python.exe"
)

set "PYTHONUNBUFFERED=1"

echo =======================================================
echo Iniciando GIMO Universal MCP Server (SSE) ...
echo =======================================================
echo.
echo URL: http://localhost:8000/mcp/sse
echo.

"%PYTHON_EXE%" -m uvicorn tools.gimo_server.main:create_app --factory --host 0.0.0.0 --port 8000
