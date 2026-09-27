@echo off
title Claude Kill Switch - Windows
cd /d "%~dp0.."

echo ========================================================
echo         Claude Kill Switch for Windows (v1.0)
echo ========================================================
echo.

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in PATH!
    echo Please install Python 3 from https://www.python.org/ or Microsoft Store.
    pause
    exit /b 1
)

if not exist config.env (
    if exist config.env.example (
        copy config.env.example config.env >nul
        echo [INFO] Created config.env from example.
    )
)

echo Starting Background Daemon...
start "ClaudeKillSwitch-Daemon" /b python windows\enforce_windows.py

echo Starting Dashboard Web UI on http://127.0.0.1:54321 ...
start "ClaudeKillSwitch-UI" /b python bin\ui_server.py

timeout /t 2 >nul
start http://127.0.0.1:54321

echo.
echo [OK] Claude Kill Switch is active and running!
echo Dashboard opened at http://127.0.0.1:54321
echo You can minimize this window.
echo.
pause
