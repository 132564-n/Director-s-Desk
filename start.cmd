@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"
set "start_status=%ERRORLEVEL%"
if not "%start_status%"=="0" (
    echo.
    echo Startup failed. Check data\logs for details.
    pause
)
exit /b %start_status%
