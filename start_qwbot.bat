@echo off
setlocal
cd /d "%~dp0"
echo QWbot supervisor running. Press Ctrl+C to stop QWbot and the configured QQ account.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_qwbot.ps1"
if errorlevel 1 (
    echo.
    echo QWbot launcher exited with an error. See data\launcher.log
    pause
)
