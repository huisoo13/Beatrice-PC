param([switch]$Publish)
$ErrorActionPreference = 'Stop'
$nativeProjectRoot = Split-Path (Split-Path $PSScriptRoot)
$env:DOTNET_CLI_HOME = Join-Path $nativeProjectRoot 'outputs/dotnet-home'
$env:NUGET_PACKAGES = Join-Path $nativeProjectRoot 'outputs/nuget'
$nativeDotnet = Join-Path $nativeProjectRoot 'outputs/dotnet/dotnet.exe'
if (-not (Test-Path -LiteralPath $nativeDotnet)) { $nativeDotnet = 'dotnet' }
$nativeProject = Join-Path $PSScriptRoot 'Beatrice.App.csproj'
& $nativeDotnet restore $nativeProject -p:Platform=x64 --ignore-failed-sources
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
if ($Publish) {
    & $nativeDotnet publish $nativeProject -c Release -p:Platform=x64 --no-restore -o (Join-Path $nativeProjectRoot 'build/native-ui')
} else {
    & $nativeDotnet build $nativeProject -c Release -p:Platform=x64 --no-restore
}
exit $LASTEXITCODE
