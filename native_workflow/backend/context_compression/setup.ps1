param([string]$Python = '')
$ErrorActionPreference = 'Stop'
if (-not $Python) {
    $taskOnPath = Get-Command python -ErrorAction SilentlyContinue | Where-Object { $_.Source -notlike '*WindowsApps*' } | Select-Object -First 1
    $taskBundled = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
    if ($taskOnPath) { $Python = $taskOnPath.Source }
    elseif (Test-Path -LiteralPath $taskBundled) { $Python = $taskBundled }
    else { throw 'Python 3.12 was not found on PATH.' }
}
$taskVenv = Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) '.venv-context'
$taskPython = Join-Path $taskVenv 'Scripts/python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    & $Python -m venv --system-site-packages $taskVenv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create virtual environment.' }
}
& $taskPython -m pip install -e "$PSScriptRoot[documents,test]"
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& $taskPython -X utf8 -m ctxcomp doctor
