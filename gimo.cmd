@echo off
cd /d "%~dp0" || exit /b 1
if exist ".venv\Scripts\python.exe" (".venv\Scripts\python.exe" -m gimo_cli %*) else (python -m gimo_cli %*)
