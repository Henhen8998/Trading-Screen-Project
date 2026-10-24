@echo off
title TradeOps
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo TradeOps Python environment is missing. Follow the setup steps in README.md.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" launch_tradeops.py
if errorlevel 1 pause
