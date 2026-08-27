$ErrorActionPreference = "Stop"

$installerScript = Join-Path $PSScriptRoot "install_dev_plugin.ps1"
$testLibrary = "C:\MangaNana-Dev\Test-Library"

& $installerScript
if ($LASTEXITCODE -ne 0) {
    throw "Plugin build or installation failed with exit code $LASTEXITCODE."
}

$calibreCommand = Get-Command "calibre.exe" -ErrorAction SilentlyContinue
if ($null -ne $calibreCommand) {
    $calibreExecutable = $calibreCommand.Source
} else {
    $calibreExecutable = "C:\Program Files\Calibre2\calibre.exe"
    if (-not (Test-Path -LiteralPath $calibreExecutable -PathType Leaf)) {
        throw "calibre.exe was not found on PATH or at '$calibreExecutable'."
    }
}

Write-Host "Launching Calibre with test library: '$testLibrary'"
$calibreProcess = Start-Process `
    -FilePath $calibreExecutable `
    -ArgumentList @("--with-library", "`"$testLibrary`"") `
    -PassThru
Write-Host "Calibre launched successfully (process ID $($calibreProcess.Id))."
