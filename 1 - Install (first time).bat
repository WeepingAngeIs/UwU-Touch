@echo off
setlocal
cd /d "%~dp0"
title Nova Macro Hub - Install
echo.
echo  ===  Nova Macro Hub - first-time install  ===
echo.

rem ---- find Python (the "py" launcher is the most reliable on Windows)
set "PY="
py -3 --version >nul 2>nul && set "PY=py -3"
if not defined PY (
    python --version >nul 2>nul && set "PY=python"
)
if not defined PY goto :nopython

echo  Found Python:
%PY% --version
echo.

if not exist ".venv\Scripts\python.exe" (
    echo  Creating a private Python folder for the app ^(.venv^)...
    %PY% -m venv .venv
    if errorlevel 1 goto :fail
)

echo  Downloading the app's parts. This is about 90 MB - on slow internet it can take a while.
echo  If it stops with an error, just run this file again: it continues where it left off.
echo.
".venv\Scripts\python.exe" -m pip install --upgrade pip --retries 10 --timeout 120 -q
".venv\Scripts\python.exe" -m pip install -r requirements.txt --retries 10 --timeout 120
if errorlevel 1 goto :fail

echo.
echo  ===  Done!  Double-click "2 - Start Nova Macro Hub.bat" to open the app.  ===
echo.
pause
exit /b 0

:nopython
echo  Python is not installed.
echo.
echo  Easiest fix: press any key and this window will install Python 3.12 for you
echo  (uses Windows' own "winget" installer). Then run this file again.
echo  Or install it yourself from https://www.python.org/downloads/  and tick
echo  "Add python.exe to PATH" on the first installer screen.
echo.
pause
winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
echo.
echo  When the install has finished, CLOSE this window and run "1 - Install (first time).bat" again.
pause
exit /b 1

:fail
echo.
echo  Something went wrong (see the red text above). Usually it is the internet connection:
echo  just run this file again. See README.txt - Troubleshooting for more help.
pause
exit /b 1
