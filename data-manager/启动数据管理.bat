@echo off
chcp 65001 >nul
title AWA Data Manager - local service
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo.
    echo  [ERROR] Python not found in PATH.
    echo  Install Python 3.8+ and make sure "python" works in cmd.
    echo.
    pause
    exit /b 1
)

echo.
echo  Starting AWA data manager...
echo  Browser will open automatically. Close this window to stop the service.
echo.

python server.py
echo.
echo  Service stopped.
pause
