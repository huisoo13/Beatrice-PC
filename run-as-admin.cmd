@echo off
set "BEATRICE_LAUNCH_ROOT=%~dp0"
powershell -NoProfile -Command "$captureAppRoot=$env:BEATRICE_LAUNCH_ROOT; $captureAppPython=Join-Path $captureAppRoot 'runtime/pythonw.exe'; if (-not (Test-Path -LiteralPath $captureAppPython)) { $captureAppPython=Join-Path $captureAppRoot '.venv-win/Scripts/pythonw.exe' }; if (-not (Test-Path -LiteralPath $captureAppPython)) { throw 'App Python runtime missing' }; Start-Process -FilePath $captureAppPython -ArgumentList 'app_launcher.py' -WorkingDirectory $captureAppRoot -Verb RunAs -WindowStyle Hidden"
