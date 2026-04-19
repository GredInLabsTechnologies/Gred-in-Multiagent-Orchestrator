@echo off
setlocal EnableDelayedExpansion

TITLE GIMO Dev Up

set "ROOT_DIR=%~dp0..\.."
cd /d "%ROOT_DIR%" || (echo [ERROR] No se pudo entrar al repo root & exit /b 1)

echo.
echo =======================================================
echo   GIMO Dev Up ^(portable runtime^)
echo =======================================================

set "PYTHON_EXE=.venv\Scripts\python.exe"
set "NEED_BOOTSTRAP=0"
if not exist "%PYTHON_EXE%" set "NEED_BOOTSTRAP=1"
if not exist ".venv\pyvenv.cfg" set "NEED_BOOTSTRAP=1"
if not exist "tools\orchestrator_ui\node_modules" set "NEED_BOOTSTRAP=1"
if not exist "apps\web\node_modules" set "NEED_BOOTSTRAP=1"

if "%NEED_BOOTSTRAP%"=="1" (
  echo [INFO] Entorno incompleto detectado. Ejecutando bootstrap...
  call "%ROOT_DIR%\scripts\dev\bootstrap.cmd" || exit /b 1
)

if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"

if not exist "tools\orchestrator_ui\.env.local" (
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
)

set "FB_API_KEY="
set "FB_AUTH_DOMAIN="
set "FB_PROJECT_ID="
set "FB_STORAGE_BUCKET="
set "FB_MESSAGING_SENDER_ID="
set "FB_APP_ID="

if exist ".env" (
  for /f "usebackq eol=# tokens=1,* delims==" %%A in (".env") do (
    if /I "%%A"=="VITE_FIREBASE_API_KEY" set "FB_API_KEY=%%B"
    if /I "%%A"=="VITE_FIREBASE_AUTH_DOMAIN" set "FB_AUTH_DOMAIN=%%B"
    if /I "%%A"=="VITE_FIREBASE_PROJECT_ID" set "FB_PROJECT_ID=%%B"
    if /I "%%A"=="VITE_FIREBASE_STORAGE_BUCKET" set "FB_STORAGE_BUCKET=%%B"
    if /I "%%A"=="VITE_FIREBASE_MESSAGING_SENDER_ID" set "FB_MESSAGING_SENDER_ID=%%B"
    if /I "%%A"=="VITE_FIREBASE_APP_ID" set "FB_APP_ID=%%B"

    if /I "%%A"=="FIREBASE_API_KEY" if not defined FB_API_KEY set "FB_API_KEY=%%B"
    if /I "%%A"=="FIREBASE_AUTH_DOMAIN" if not defined FB_AUTH_DOMAIN set "FB_AUTH_DOMAIN=%%B"
    if /I "%%A"=="FIREBASE_PROJECT_ID" if not defined FB_PROJECT_ID set "FB_PROJECT_ID=%%B"
    if /I "%%A"=="FIREBASE_STORAGE_BUCKET" if not defined FB_STORAGE_BUCKET set "FB_STORAGE_BUCKET=%%B"
    if /I "%%A"=="FIREBASE_MESSAGING_SENDER_ID" if not defined FB_MESSAGING_SENDER_ID set "FB_MESSAGING_SENDER_ID=%%B"
    if /I "%%A"=="FIREBASE_APP_ID" if not defined FB_APP_ID set "FB_APP_ID=%%B"

    if /I "%%A"=="NEXT_PUBLIC_FIREBASE_API_KEY" if not defined FB_API_KEY set "FB_API_KEY=%%B"
    if /I "%%A"=="NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN" if not defined FB_AUTH_DOMAIN set "FB_AUTH_DOMAIN=%%B"
    if /I "%%A"=="NEXT_PUBLIC_FIREBASE_PROJECT_ID" if not defined FB_PROJECT_ID set "FB_PROJECT_ID=%%B"
    if /I "%%A"=="NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET" if not defined FB_STORAGE_BUCKET set "FB_STORAGE_BUCKET=%%B"
    if /I "%%A"=="NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID" if not defined FB_MESSAGING_SENDER_ID set "FB_MESSAGING_SENDER_ID=%%B"
    if /I "%%A"=="NEXT_PUBLIC_FIREBASE_APP_ID" if not defined FB_APP_ID set "FB_APP_ID=%%B"
  )
)

if exist "apps\web\.env.local" (
  for /f "usebackq eol=# tokens=1,* delims==" %%A in ("apps\web\.env.local") do (
    if /I "%%A"=="NEXT_PUBLIC_FIREBASE_API_KEY" if not defined FB_API_KEY set "FB_API_KEY=%%B"
    if /I "%%A"=="NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN" if not defined FB_AUTH_DOMAIN set "FB_AUTH_DOMAIN=%%B"
    if /I "%%A"=="NEXT_PUBLIC_FIREBASE_PROJECT_ID" if not defined FB_PROJECT_ID set "FB_PROJECT_ID=%%B"
    if /I "%%A"=="NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET" if not defined FB_STORAGE_BUCKET set "FB_STORAGE_BUCKET=%%B"
    if /I "%%A"=="NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID" if not defined FB_MESSAGING_SENDER_ID set "FB_MESSAGING_SENDER_ID=%%B"
    if /I "%%A"=="NEXT_PUBLIC_FIREBASE_APP_ID" if not defined FB_APP_ID set "FB_APP_ID=%%B"
  )
)

if exist "apps\web\.env" (
  for /f "usebackq eol=# tokens=1,* delims==" %%A in ("apps\web\.env") do (
    if /I "%%A"=="NEXT_PUBLIC_FIREBASE_API_KEY" if not defined FB_API_KEY set "FB_API_KEY=%%B"
    if /I "%%A"=="NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN" if not defined FB_AUTH_DOMAIN set "FB_AUTH_DOMAIN=%%B"
    if /I "%%A"=="NEXT_PUBLIC_FIREBASE_PROJECT_ID" if not defined FB_PROJECT_ID set "FB_PROJECT_ID=%%B"
    if /I "%%A"=="NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET" if not defined FB_STORAGE_BUCKET set "FB_STORAGE_BUCKET=%%B"
    if /I "%%A"=="NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID" if not defined FB_MESSAGING_SENDER_ID set "FB_MESSAGING_SENDER_ID=%%B"
    if /I "%%A"=="NEXT_PUBLIC_FIREBASE_APP_ID" if not defined FB_APP_ID set "FB_APP_ID=%%B"
  )
)

if not defined FB_API_KEY if defined VITE_FIREBASE_API_KEY set "FB_API_KEY=%VITE_FIREBASE_API_KEY%"
if not defined FB_AUTH_DOMAIN if defined VITE_FIREBASE_AUTH_DOMAIN set "FB_AUTH_DOMAIN=%VITE_FIREBASE_AUTH_DOMAIN%"
if not defined FB_PROJECT_ID if defined VITE_FIREBASE_PROJECT_ID set "FB_PROJECT_ID=%VITE_FIREBASE_PROJECT_ID%"
if not defined FB_STORAGE_BUCKET if defined VITE_FIREBASE_STORAGE_BUCKET set "FB_STORAGE_BUCKET=%VITE_FIREBASE_STORAGE_BUCKET%"
if not defined FB_MESSAGING_SENDER_ID if defined VITE_FIREBASE_MESSAGING_SENDER_ID set "FB_MESSAGING_SENDER_ID=%VITE_FIREBASE_MESSAGING_SENDER_ID%"
if not defined FB_APP_ID if defined VITE_FIREBASE_APP_ID set "FB_APP_ID=%VITE_FIREBASE_APP_ID%"

if not defined FB_API_KEY if defined FIREBASE_API_KEY set "FB_API_KEY=%FIREBASE_API_KEY%"
if not defined FB_AUTH_DOMAIN if defined FIREBASE_AUTH_DOMAIN set "FB_AUTH_DOMAIN=%FIREBASE_AUTH_DOMAIN%"
if not defined FB_PROJECT_ID if defined FIREBASE_PROJECT_ID set "FB_PROJECT_ID=%FIREBASE_PROJECT_ID%"
if not defined FB_STORAGE_BUCKET if defined FIREBASE_STORAGE_BUCKET set "FB_STORAGE_BUCKET=%FIREBASE_STORAGE_BUCKET%"
if not defined FB_MESSAGING_SENDER_ID if defined FIREBASE_MESSAGING_SENDER_ID set "FB_MESSAGING_SENDER_ID=%FIREBASE_MESSAGING_SENDER_ID%"
if not defined FB_APP_ID if defined FIREBASE_APP_ID set "FB_APP_ID=%FIREBASE_APP_ID%"

if not defined FB_API_KEY if defined NEXT_PUBLIC_FIREBASE_API_KEY set "FB_API_KEY=%NEXT_PUBLIC_FIREBASE_API_KEY%"
if not defined FB_AUTH_DOMAIN if defined NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN set "FB_AUTH_DOMAIN=%NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN%"
if not defined FB_PROJECT_ID if defined NEXT_PUBLIC_FIREBASE_PROJECT_ID set "FB_PROJECT_ID=%NEXT_PUBLIC_FIREBASE_PROJECT_ID%"
if not defined FB_STORAGE_BUCKET if defined NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET set "FB_STORAGE_BUCKET=%NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET%"
if not defined FB_MESSAGING_SENDER_ID if defined NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID set "FB_MESSAGING_SENDER_ID=%NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID%"
if not defined FB_APP_ID if defined NEXT_PUBLIC_FIREBASE_APP_ID set "FB_APP_ID=%NEXT_PUBLIC_FIREBASE_APP_ID%"

call :upsert_env_value "tools\orchestrator_ui\.env.local" "VITE_FIREBASE_API_KEY" "!FB_API_KEY!"
call :upsert_env_value "tools\orchestrator_ui\.env.local" "VITE_FIREBASE_AUTH_DOMAIN" "!FB_AUTH_DOMAIN!"
call :upsert_env_value "tools\orchestrator_ui\.env.local" "VITE_FIREBASE_PROJECT_ID" "!FB_PROJECT_ID!"
call :upsert_env_value "tools\orchestrator_ui\.env.local" "VITE_FIREBASE_STORAGE_BUCKET" "!FB_STORAGE_BUCKET!"
call :upsert_env_value "tools\orchestrator_ui\.env.local" "VITE_FIREBASE_MESSAGING_SENDER_ID" "!FB_MESSAGING_SENDER_ID!"
call :upsert_env_value "tools\orchestrator_ui\.env.local" "VITE_FIREBASE_APP_ID" "!FB_APP_ID!"

if not defined ORCH_HOST set "ORCH_HOST=0.0.0.0"

echo [1/4] Probando si el backend ya responde ...
powershell -NoProfile -Command "try { $r=Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:9325/auth/check' -TimeoutSec 1; if($r.StatusCode -ge 200){ exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>&1
if not errorlevel 1 (
  echo [OK] Backend ya corriendo en 9325, no relanzo.
  set "HEALTH_OK=1"
  goto :HEALTH_DONE
)

echo [1/4] Limpiando puertos ^(9325, 5173, 3000^) ...
"%PYTHON_EXE%" scripts\ops\kill_port.py 9325 5173 3000 >nul 2>&1

echo [2/4] Lanzando backend en %ORCH_HOST%:9325 ...
start "GIMO Backend" cmd /k "title GIMO Backend && cd /d "%ROOT_DIR%" && "%PYTHON_EXE%" -m uvicorn tools.gimo_server.main:app --host %ORCH_HOST% --port 9325 --reload --log-level info"

echo [3/4] Esperando health backend ...
set "HEALTH_OK=0"
for /L %%I in (1,1,40) do (
  powershell -NoProfile -Command "try { $r=Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:9325/auth/check' -TimeoutSec 2; if($r.StatusCode -ge 200){ exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>&1
  if not errorlevel 1 (
    set "HEALTH_OK=1"
    goto :HEALTH_DONE
  )
  timeout /t 1 /nobreak >nul
)

:HEALTH_DONE
if "%HEALTH_OK%"=="1" (
  echo [OK] Backend listo.
) else (
  echo [WARN] Backend no respondio a tiempo, continuando con frontend...
)

echo [4/4] Lanzando frontend y web ...
start "GIMO Frontend" cmd /k "title GIMO Frontend && cd /d "%ROOT_DIR%\tools\orchestrator_ui" && npm run dev -- --host %ORCH_HOST%"
start "GIMO Web" cmd /k "title GIMO Web && cd /d "%ROOT_DIR%\apps\web" && npm run dev"

echo.
echo [OK] Servicios lanzados:
echo      Backend:  http://%ORCH_HOST%:9325 ^(acceso local: http://127.0.0.1:9325^)
echo      UI:       http://%ORCH_HOST%:5173 ^(acceso local: http://127.0.0.1:5173^)
echo      Web:      http://localhost:3000
echo.
if /I not "%ORCH_HOST%"=="127.0.0.1" (
  echo [AVISO] Backend expuesto a LAN. Verifica firewall Windows para 9325/tcp.
  echo.
)
start "" http://127.0.0.1:5173
exit /b 0

:upsert_env_value
set "ENV_FILE=%~1"
set "ENV_KEY=%~2"
set "ENV_VALUE=%~3"
if not defined ENV_VALUE goto :eof
powershell -NoProfile -Command "$p='%ENV_FILE%'; $k='%ENV_KEY%'; $v=$env:ENV_VALUE; if (-not (Test-Path $p)) { New-Item -ItemType File -Path $p -Force | Out-Null }; $lines=@(Get-Content -Path $p -ErrorAction SilentlyContinue); if (-not $lines) { $lines=@() }; $pattern='^' + [regex]::Escape($k) + '='; $found=$false; $out=@(); foreach ($line in $lines) { if ($line -match $pattern) { $out += ($k + '=' + $v); $found=$true } else { $out += $line } }; if (-not $found) { $out += ($k + '=' + $v) }; Set-Content -Path $p -Value $out -Encoding UTF8"
goto :eof
