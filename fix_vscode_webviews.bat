@echo off
echo ========================================================
echo      VS Code Webview Repair Script
echo ========================================================
echo.
echo This script will forcefully close VS Code and clear its 
echo internal caches to fix "Service Worker" and Webview errors.
echo.
echo [IMPORTANT] close all VS Code windows before proceeding.
echo.
pause

echo.
echo [1/3] Closing VS Code (Code.exe)...
taskkill /F /IM Code.exe >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo    - VS Code closed.
) else (
    echo    - VS Code was not running or could not be closed.
)

echo.
echo [2/3] Clearing Service Worker Cache...
set "SW_CACHE=%APPDATA%\Code\Service Worker"
if exist "%SW_CACHE%" (
    rmdir /s /q "%SW_CACHE%"
    echo    - Deleted: %SW_CACHE%
) else (
    echo    - Not found (already clean): %SW_CACHE%
)

echo.
echo [3/3] Clearing Cached Data...
set "CACHE_DATA=%APPDATA%\Code\CachedData"
if exist "%CACHE_DATA%" (
    rmdir /s /q "%CACHE_DATA%"
    echo    - Deleted: %CACHE_DATA%
) else (
    echo    - Not found (already clean): %CACHE_DATA%
)

echo.
echo ========================================================
echo Repair Complete!
echo Please restart VS Code and check if your extensions work.
echo ========================================================
pause
