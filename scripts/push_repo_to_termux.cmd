@echo off
REM Empaqueta el subset del repo que GIMO Core necesita y lo hace adb push
REM al S10 en /sdcard/Download/ para que Termux lo consuma.
REM
REM Requiere:
REM   - adb.exe en PATH o en %LOCALAPPDATA%\Android\Sdk\platform-tools\
REM   - tar.exe nativo (Windows 10+ lo trae en System32)
REM   - S10 conectado en adb devices (USB debugging on + autorizado)
REM
REM Output:
REM   /sdcard/Download/gimo-repo.tar.gz         (~10-20 MB, subset Core)
REM   /sdcard/Download/termux_core_bootstrap.sh (script bootstrap)
REM
REM Uso:
REM   scripts\push_repo_to_termux.cmd

setlocal enabledelayedexpansion

set "REPO_ROOT=%~dp0.."
pushd "%REPO_ROOT%"

REM Resolver adb
set "ADB=adb"
where adb >nul 2>&1 || set "ADB=%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe"
if not exist "%ADB%" (
    if "%ADB%" == "adb" (
        echo [err] adb no encontrado en PATH ni en %%LOCALAPPDATA%%\Android\Sdk\platform-tools\
        exit /b 1
    )
)

REM Resolver tar nativo Windows (System32)
set "TAR=%SystemRoot%\System32\tar.exe"
if not exist "%TAR%" (
    echo [err] tar.exe no encontrado en %TAR%. Requires Windows 10+ o instalar bsdtar.
    exit /b 1
)

REM Verificar device conectado
"%ADB%" devices | findstr /R /C:"	device$" >nul
if errorlevel 1 (
    echo [err] No hay device conectado en adb. Conecta el S10 con USB debugging + autorizado.
    exit /b 1
)

echo [step] Packing minimal GIMO Core subset...
set "OUT_TARBALL=%TEMP%\gimo-repo.tar.gz"
if exist "%OUT_TARBALL%" del /q "%OUT_TARBALL%"

REM Subset: solo lo que tools.gimo_server.main necesita at runtime.
REM NUNCA empaqueta tokens/credenciales — el bootstrap los carga aparte del
REM .orch_token que viaja por canal separado.
"%TAR%" -czf "%OUT_TARBALL%" ^
    --exclude=__pycache__ ^
    --exclude=*.pyc ^
    --exclude=.orch_data ^
    --exclude=.orch_snapshots ^
    --exclude=.gimo_credentials ^
    --exclude=.orch_token ^
    --exclude=.orch_actions_token ^
    --exclude=.orch_operator_token ^
    --exclude=.tmp_cookie.txt ^
    --exclude=*.key ^
    --exclude=*.pem ^
    tools\__init__.py ^
    tools\gimo_server ^
    tools\gimo_mesh_agent ^
    gimo_cli ^
    gimo.py ^
    requirements.txt ^
    docs\SECURITY.md

if errorlevel 1 (
    echo [err] tar packing failed
    exit /b 1
)

for %%F in ("%OUT_TARBALL%") do set "SIZE=%%~zF"
set /a SIZE_MB=!SIZE! / 1048576
echo [step] Tarball ready: %OUT_TARBALL% (!SIZE_MB! MiB)

echo [step] Pushing to device /sdcard/Download/...
"%ADB%" push "%OUT_TARBALL%" /sdcard/Download/gimo-repo.tar.gz
if errorlevel 1 (
    echo [err] adb push del tarball falló
    exit /b 1
)

"%ADB%" push "%REPO_ROOT%\scripts\termux_core_bootstrap.sh" /sdcard/Download/termux_core_bootstrap.sh
if errorlevel 1 (
    echo [err] adb push del bootstrap script falló
    exit /b 1
)

REM Opcional: .orch_token
if exist "%REPO_ROOT%\.orch_token" (
    "%ADB%" push "%REPO_ROOT%\.orch_token" /sdcard/Download/.orch_token
    echo [step] .orch_token pushed — el bootstrap lo cargará automaticamente si lo copias junto al repo.
)

echo.
echo [ok] Push completo. En el S10, abre la app Termux y pega:
echo.
echo    termux-setup-storage     (una vez, acepta el prompt de permiso)
echo    bash /storage/emulated/0/Download/termux_core_bootstrap.sh
echo.
echo   El bootstrap auto-detecta el tarball y el token. Primera corrida
echo   tarda ~3-5 min (pkg install + pip). Siguientes son instantaneas.
echo.
echo   El Core queda escuchando en http://^<s10-lan-ip^>:9325 (role=server).
echo.

popd
endlocal
