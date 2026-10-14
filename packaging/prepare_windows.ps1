param([switch]$Offline)
$ErrorActionPreference = 'Stop'
$packageRoot = Split-Path $PSScriptRoot
$packagePython = Join-Path $packageRoot '.venv-win/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $packagePython)) { $packagePython = 'python' }
Push-Location $packageRoot
try {
    $packageRuntimeArgs = @('packaging/download_runtime.py')
    if ($Offline) { $packageRuntimeArgs += '--offline' }
    & $packagePython @packageRuntimeArgs
    if ($LASTEXITCODE -ne 0) { throw 'Runtime preparation failed' }
    $packagePipArgs = @('-m', 'pip', 'download', '--only-binary=:all:', '--platform', 'win_amd64',
        '--python-version', '3.12', '--implementation', 'cp', '--abi', 'cp312', '--require-hashes',
        '-r', 'packaging/requirements-windows-lock.txt', '-d', 'build/windows-wheels')
    if ($Offline) { $packagePipArgs += @('--no-index', '--find-links', 'build/windows-wheels') }
    & $packagePython @packagePipArgs
    if ($LASTEXITCODE -ne 0) { throw 'Wheel preparation failed' }
    if (-not (Test-Path -LiteralPath 'build/obs-runtime/manifest.json')) {
        if ($Offline) { throw 'Offline preparation requires build/obs-runtime' }
        & $packagePython packaging/prepare_obs.py
        if ($LASTEXITCODE -ne 0) { throw 'OBS preparation failed' }
    }
    if (-not $Offline) {
        & $packagePython packaging/prepare_sources.py
        if ($LASTEXITCODE -ne 0) { throw 'Source preparation failed' }
    }
    & ./ui/Beatrice.App/build.ps1 -Publish
    if ($LASTEXITCODE -ne 0) { throw 'WinUI publish failed' }
    & $packagePython packaging/build_single_exe.py --stage-only
    if ($LASTEXITCODE -ne 0) { throw 'Staging failed' }
    & ./build/windows-app/runtime/python.exe packaging/verify_windows_stage.py
    if ($LASTEXITCODE -ne 0) { throw 'Staged runtime verification failed' }
} finally { Pop-Location }
