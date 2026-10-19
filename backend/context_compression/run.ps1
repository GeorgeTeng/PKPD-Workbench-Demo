$ErrorActionPreference = 'Stop'
$taskPython = Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) '.venv-context/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    throw 'Run setup.ps1 once to install the local environment.'
}
& $taskPython -I -X utf8 -m ctxcomp @args
exit $LASTEXITCODE
