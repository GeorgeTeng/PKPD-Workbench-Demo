param([string]$Python = "python")
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$venvPython = Join-Path $projectRoot '.venv-context/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
    & $Python -m venv (Join-Path $projectRoot '.venv-context')
    if ($LASTEXITCODE -ne 0) { throw 'Python venv creation failed.' }
}
$packageSpec = $PSScriptRoot + '[test]'
& $venvPython -m pip install -e $packageSpec
if ($LASTEXITCODE -ne 0) { throw 'Package installation failed.' }
Write-Host 'Python setup complete. Set PKPD_RSCRIPT to Rscript; R packages required: jsonlite, minpack.lm, nlme.'
