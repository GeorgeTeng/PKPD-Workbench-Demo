param([string]$Out = '')
$ErrorActionPreference = 'Stop'
$taskPython = Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) '.venv-context/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { throw 'Run setup.ps1 first.' }
if (-not $Out) {
    $taskStamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    $Out = Join-Path $PSScriptRoot "runs/demo_$taskStamp"
}
& $taskPython -X utf8 (Join-Path $PSScriptRoot 'examples/replay_demo.py') --out $Out
exit $LASTEXITCODE
