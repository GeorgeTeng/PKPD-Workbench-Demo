param([Parameter(ValueFromRemainingArguments=$true)][string[]]$TaskArgs)
$ErrorActionPreference = 'Stop'
$taskPython = Join-Path (Split-Path (Split-Path $PSScriptRoot)) '.venv-context/Scripts/python.exe'
& $taskPython -I -m research_pipeline @TaskArgs
exit $LASTEXITCODE
