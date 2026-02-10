@echo off
setlocal

set "SERVICE_NAME=GILOrchestrator"

echo Configurando cuenta de servicio para %SERVICE_NAME%...
echo Se usará la cuenta LocalSystem (portable).
echo.

sc.exe config "%SERVICE_NAME%" obj= "LocalSystem" password= ""
set "SC_EXIT=%ERRORLEVEL%"

if not "%SC_EXIT%"=="0" (
  echo Fallo al configurar el servicio. Codigo: %SC_EXIT%
  exit /b %SC_EXIT%
)

echo Reiniciando servicio...
sc.exe stop "%SERVICE_NAME%" >nul 2>&1
timeout /t 2 >nul
sc.exe start "%SERVICE_NAME%"

echo Listo. Servicio configurado como LocalSystem.
endlocal
