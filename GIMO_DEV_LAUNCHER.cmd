@echo off
:: =====================================================================
:: GIMO UNBREAKABLE DEV LAUNCHER
:: =====================================================================
:: Proposito: Lanzar Backend y Frontend simultaneamente con auto-recuperacion.
:: Resiliencia: Limpieza agresiva de zombis y loop de persistencia.
:: =====================================================================

TITLE GIMO UNBREAKABLE LAUNCHER
setlocal enabledelayedexpansion

:INIT
cls
echo.
echo  ###############################################################
echo  #                                                             #
echo  #     GIMO - UNBREAKABLE DEVELOPMENT LAUNCHER                 #
echo  #                                                             #
echo  ###############################################################
echo.

set "ROOT_DIR=%~dp0"
cd /d "%ROOT_DIR%"

:: 1. Detectar Entorno Python
set "PYTHON_EXE=python"
if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
) else if exist "venv\Scripts\python.exe" (
    set "PYTHON_EXE=venv\Scripts\python.exe"
)

:: 2. Limpieza de Zombis (Crucial para ser "Irrompible")
echo [INFO] Limpiando procesos huerfanos en puertos 9325 y 5173...
%PYTHON_EXE% scripts\ops\kill_port.py --all-gimo

:: 3. Lanzar Backend (Uvicorn con --reload)
echo [INFO] Iniciando GIMO Backend (Hot-Reload activo)...
start "GIMO_BACKEND_WATCHDOG" cmd /k "title GIMO Backend && %PYTHON_EXE% -m uvicorn tools.gimo_server.main:app --host 127.0.0.1 --port 9325 --reload --log-level info"

:: 4. Lanzar Frontend (Vite)
echo [INFO] Iniciando GIMO Frontend (Vite Hot-Reload)...
cd tools\orchestrator_ui
start "GIMO_FRONTEND_WATCHDOG" cmd /k "title GIMO Frontend && npm run dev -- --host 127.0.0.1"

:: 5. Loop de Control
cd /d "%ROOT_DIR%"
echo.
echo [SUCCESS] GIMO esta en el aire!
echo.
echo  - Backend:  http://127.0.0.1:9325
echo  - Frontend: http://127.0.0.1:5173
echo.
echo [INFO] Abriendo ventana dedicada de Chrome...
start chrome --new-window --app=http://127.0.0.1:5173

echo.
echo ###############################################################
echo # PRESIONA [R] PARA REINICIAR TODO (LIMPIEZA + RELANZAMIENTO) #
echo # PRESIONA [X] PARA SALIR Y CERRAR TODO                       #
echo ###############################################################
echo.

:CHOOSE
set /p user_choice="Seleccion: "
if /i "!user_choice!"=="R" goto RESTART
if /i "!user_choice!"=="X" goto EXIT_CLEAN
goto CHOOSE

:RESTART
echo [INFO] Reiniciando sistema...
goto INIT

:EXIT_CLEAN
echo [INFO] Cerrando todo y limpiando...
:: Matamos los procesos por titulo de ventana (mas fiable para CMDs lanzados con START)
taskkill /F /FI "WINDOWTITLE eq GIMO Backend*" /T >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq GIMO Frontend*" /T >nul 2>&1
:: Limpieza final de puertos por si acaso algo queda colgado
%PYTHON_EXE% scripts\ops\kill_port.py --all-gimo
echo.
echo [DONE] Entorno limpio y procesos cerrados.
timeout /t 2 >nul
exit
