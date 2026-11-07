@echo off
setlocal
cd /d "%~dp0"
title Nova Macro Hub - Build EXE
if not exist ".venv\Scripts\python.exe" (
    echo Please run "1 - Install (first time).bat" first.
    pause
    exit /b 1
)
echo  Installing the EXE builder (PyInstaller)...
".venv\Scripts\python.exe" -m pip install "pyinstaller>=6.3" --retries 10 --timeout 120 -q
if errorlevel 1 goto :fail

echo  Building... (1-3 minutes)
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --windowed ^
    --name "NovaMacroHub" --icon "assets\icon.ico" ^
    --add-data "assets;assets" ^
    --hidden-import pynput.keyboard._win32 --hidden-import pynput.mouse._win32 ^
    --collect-submodules keyring.backends ^
    run.py
if errorlevel 1 goto :fail

echo.
echo  ===  Done!  Your app is in:  dist\NovaMacroHub\NovaMacroHub.exe  ===
echo  Keep the whole "NovaMacroHub" folder together (the .exe needs the files next to it).
echo  Tip: right-click NovaMacroHub.exe - Send to - Desktop (create shortcut).
echo.
explorer "dist\NovaMacroHub"
pause
exit /b 0

:fail
echo.
echo  The build failed - see the text above, and README.txt - Troubleshooting.
pause
exit /b 1
