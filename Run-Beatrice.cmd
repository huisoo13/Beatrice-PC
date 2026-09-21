@echo off
setlocal
cd /d "%~dp0"
if not exist "%~dp0.venv-win\Scripts\python.exe" (
    echo Python environment .venv-win is missing.
    pause
    exit /b 1
)
"%~dp0.venv-win\Scripts\python.exe" "%~dp0app_launcher.py"
if errorlevel 1 (
    echo Beatrice failed. Check %%LOCALAPPDATA%%\BeatricePC logs.
    pause
    exit /b 1
)
