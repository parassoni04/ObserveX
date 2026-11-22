@echo off
title ObserveX Windows Agent
color 0b
echo ============================================================
echo   ObserveX Windows Agent Launcher
echo ============================================================
echo.
echo Starting ObserveX Windows Agent...
echo.
"%~dp0ObserveXAgent.exe" %*
set AGENT_ERR=%ERRORLEVEL%
echo.
if %AGENT_ERR% NEQ 0 (
    echo [ObserveX] Agent exited with code %AGENT_ERR%.
) else (
    echo [ObserveX] Agent exited normally.
)
echo.
pause
