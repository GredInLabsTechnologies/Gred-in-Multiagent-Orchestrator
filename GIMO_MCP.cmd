@echo off
:: =====================================================================
:: GIMO SECURE MCP SERVER LAUNCHER (Windows)
:: =====================================================================
:: This script starts the GIMO FastMCP Server for integration with 
:: external LLMs/Orchestrators (Claude Desktop, Cursor, etc).
:: =====================================================================
TITLE GIMO MCP Server

set "ROOT_DIR=%~dp0"
cd /d "%ROOT_DIR%"

:: 1. Detect Virtual Environment
set "PYTHON_EXE=python"
if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
) else if exist "venv\Scripts\python.exe" (
    set "PYTHON_EXE=venv\Scripts\python.exe"
) else if exist "env\Scripts\python.exe" (
    set "PYTHON_EXE=env\Scripts\python.exe"
)

:: Ensure required variables are set
set "PYTHONUNBUFFERED=1"

echo =======================================================
echo Iniciando GIMO Universal MCP Server (SSE) ...
echo =======================================================
echo.
echo NOTA: GIMO ahora expone su MCP Server en modo Stateful/Universal (SSE).
echo Para conectar a un Orquestador externo utilice la siguiente URL:
echo http://localhost:8000/mcp/sse
echo.

:: Start the MCP Server using Uvicorn (Universal SSE mode)
"%PYTHON_EXE%" -m uvicorn tools.gimo_server.main:create_app --factory --host 0.0.0.0 --port 8000
