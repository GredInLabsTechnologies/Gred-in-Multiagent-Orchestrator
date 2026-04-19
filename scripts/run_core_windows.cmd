@echo off
REM Wrapper .cmd para invocar run_core_windows.ps1 con ExecutionPolicy Bypass.
REM Usage (desde repo root):
REM   scripts\run_core_windows.cmd [server|client] [port]
REM Ejemplos:
REM   scripts\run_core_windows.cmd server
REM   scripts\run_core_windows.cmd server 9325
REM   scripts\run_core_windows.cmd client

setlocal
set ROLE=%1
set PORT=%2
if "%ROLE%"=="" set ROLE=server
if "%PORT%"=="" set PORT=9325

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_core_windows.ps1" -Role %ROLE% -Port %PORT%
exit /b %ERRORLEVEL%
