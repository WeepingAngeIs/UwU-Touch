@echo off
cd /d "%~dp0"
title Nova Macro Hub - Tests
if not exist ".venv\Scripts\python.exe" (
    echo Please run "1 - Install (first time).bat" first.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m pip install pytest -q --retries 10 --timeout 120
".venv\Scripts\python.exe" -m pytest -q tests
pause
