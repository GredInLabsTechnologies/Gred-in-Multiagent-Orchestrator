@echo off
REM ========================================================================
REM Local SonarQube & Coverage Automation Script
REM Combines testing, coverage generation, and SonarQube scanning.
REM ========================================================================

echo [1/3] Running Python Tests & Generating Coverage...
python -m pytest --cov=tools --cov=scripts --cov-report=xml:coverage.xml --cov-report=term
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python tests failed! Check the output above.
    exit /b %ERRORLEVEL%
)

echo [2/3] Checking UI Tests (if applicable)...
if exist "tools\orchestrator_ui" (
    cd tools\orchestrator_ui
    call npm run test:coverage
    if exist "coverage\lcov.info" (
        REM Adjust paths in lcov.info for SonarQube
        powershell -Command "(Get-Content coverage\lcov.info) -replace 'SF:', 'SF:tools/orchestrator_ui/' | Set-Content coverage\lcov.info"
    )
    cd ..\..
)

echo [3/3] Running SonarScanner...
REM Ensure sonar-scanner is in your PATH and SONAR_TOKEN is set in your environment
sonar-scanner.bat
if %ERRORLEVEL% neq 0 (
    echo [ERROR] SonarQube scan failed!
    exit /b %ERRORLEVEL%
)

echo [SUCCESS] Local coverage generated and SonarQube analysis completed!
pause
