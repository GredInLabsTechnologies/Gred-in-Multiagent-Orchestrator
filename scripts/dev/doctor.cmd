@echo off
setlocal EnableDelayedExpansion

TITLE GIMO Dev Doctor

set "ROOT_DIR=%~dp0..\.."
cd /d "%ROOT_DIR%" || (echo [ERROR] No se pudo entrar al repo root & exit /b 1)

echo.
echo =======================================================
echo   GIMO Dev Doctor
echo =======================================================

set "FAIL=0"

call :check_tool git "git --version"
call :check_tool node "node --version"
call :check_tool npm "npm --version"
call :check_tool python "python --version"

if exist ".venv\Scripts\python.exe" (
  echo [OK] .venv detectado
) else (
  echo [WARN] .venv no existe. Ejecuta bootstrap.cmd
)

if exist ".env" (
  echo [OK] .env presente
) else (
  echo [WARN] .env ausente. Ejecuta bootstrap.cmd
)

if exist "tools\orchestrator_ui\.env.local" (
  echo [OK] tools\orchestrator_ui\.env.local presente
) else (
  echo [WARN] tools\orchestrator_ui\.env.local ausente
)

set "PYTHON_EXE=.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"

powershell -NoProfile -Command "$ProgressPreference='SilentlyContinue'; try { $r=Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:9325/auth/check' -TimeoutSec 2; Write-Output ('[OK] Backend responde en 9325 (HTTP ' + $r.StatusCode + ')') } catch { Write-Output '[INFO] Backend no responde en 9325 (normal si no esta iniciado)' }"

rem Diagnóstico mesh: si mesh_enabled=true pero Core bindeado a loopback, avisar.
powershell -NoProfile -Command "$ProgressPreference='SilentlyContinue'; try { $t=(Get-Content '.env' -ErrorAction SilentlyContinue | Select-String '^ORCH_TOKEN=').ToString().Split('=',2)[1]; $headers=@{ Authorization = 'Bearer ' + $t }; $cfg=Invoke-RestMethod -Uri 'http://127.0.0.1:9325/ops/mesh/status' -Headers $headers -TimeoutSec 2 -ErrorAction Stop; if($cfg.mesh_enabled -eq $true){ $bind = netstat -an | Select-String ':9325\s' | Select-String 'LISTENING' ; if($bind -match '127.0.0.1:9325'){ Write-Output '[WARN] mesh_enabled=true pero Core bindeado a 127.0.0.1 — dispositivos LAN no podran conectar. Reinicia con ORCH_HOST=0.0.0.0.' } else { Write-Output '[OK] Mesh activo y Core accesible desde LAN.' } } else { Write-Output '[INFO] Mesh desactivado.' } } catch { Write-Output '[INFO] No se pudo verificar estado mesh.' }"

rem Diagnóstico de duplicados uvicorn
powershell -NoProfile -Command "$ProgressPreference='SilentlyContinue'; $procs = Get-CimInstance Win32_Process -Filter \"Name='python.exe' OR Name='python3.13.exe'\" | Where-Object { $_.CommandLine -like '*uvicorn tools.gimo_server*' }; if($procs.Count -gt 1){ Write-Output ('[WARN] ' + $procs.Count + ' procesos uvicorn de GIMO detectados. Se recomienda matar duplicados.') } elseif($procs.Count -eq 1){ Write-Output '[OK] Un unico proceso uvicorn GIMO.' } else { Write-Output '[INFO] Ningun uvicorn GIMO corriendo.' }"

echo.
echo [DONE] Doctor finalizado.
if "%FAIL%"=="1" (
  echo [ACTION] Faltan herramientas base. Instala prerequisitos y reintenta.
  exit /b 1
)
exit /b 0

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
