@echo off
setlocal
set "BEATRICE_LAUNCH_ROOT=%~dp0"
powershell -NoProfile -Command "$ErrorActionPreference='Stop'; try { $captureAppRoot=$env:BEATRICE_LAUNCH_ROOT; $captureAppPython=Join-Path $captureAppRoot 'runtime/pythonw.exe'; if (-not (Test-Path -LiteralPath $captureAppPython)) { $captureAppPython=Join-Path $captureAppRoot '.venv-win/Scripts/pythonw.exe' }; if (-not (Test-Path -LiteralPath $captureAppPython)) { throw 'App Python runtime missing' }; if (-not (Test-Path -LiteralPath (Join-Path $captureAppRoot 'app_launcher.py'))) { throw 'App launcher missing' }; $captureAppIdentity=[Security.Principal.WindowsIdentity]::GetCurrent(); $captureAppPrincipal=[Security.Principal.WindowsPrincipal]::new($captureAppIdentity); if ($captureAppPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { Start-Process -FilePath $captureAppPython -ArgumentList 'app_launcher.py' -WorkingDirectory $captureAppRoot -WindowStyle Hidden } else { Start-Process -FilePath $captureAppPython -ArgumentList 'app_launcher.py' -WorkingDirectory $captureAppRoot -Verb RunAs -WindowStyle Hidden }; exit 0 } catch { Write-Host ('Beatrice launch failed: '+$_.Exception.Message); exit 1 }"
if errorlevel 1 (
    echo Administrator approval is required. Check the message above.
    pause
    exit /b 1
)
exit /b 0
