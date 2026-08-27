$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$buildScript = Join-Path $PSScriptRoot "build_plugin.py"
$pluginZip = Join-Path $repositoryRoot "dist\MangaNana-Calibre-dev.zip"

& python $buildScript
if ($LASTEXITCODE -ne 0) {
    throw "Plugin build failed with exit code $LASTEXITCODE."
}

$calibreCommand = Get-Command "calibre-customize" -ErrorAction SilentlyContinue
if ($null -ne $calibreCommand) {
    $calibreCustomize = $calibreCommand.Source
} else {
    $calibreCustomize = "C:\Program Files\Calibre2\calibre-customize.exe"
    if (-not (Test-Path -LiteralPath $calibreCustomize -PathType Leaf)) {
        throw "calibre-customize was not found on PATH or at '$calibreCustomize'."
    }
}

& $calibreCustomize -a $pluginZip
if ($LASTEXITCODE -ne 0) {
    throw "Plugin installation failed with exit code $LASTEXITCODE."
}

Write-Host "MangaNana development plugin installed successfully from '$pluginZip'."
