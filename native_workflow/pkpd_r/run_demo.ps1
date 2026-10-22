param([string]$Out = '')
$ErrorActionPreference = 'Stop'
$taskR = 'C:/Users/georg/Documents/Codex/ScienceEnv/R/bin/Rscript.exe'
if (-not (Test-Path -LiteralPath $taskR)) { $taskR = (Get-Command Rscript -ErrorAction Stop).Source }
if (-not $Out) { $Out = Join-Path $PSScriptRoot ('outputs/demo_' + (Get-Date -Format 'yyyyMMdd_HHmmss')) }
& $taskR --vanilla (Join-Path $PSScriptRoot 'scripts/run_demo.R') $Out
exit $LASTEXITCODE
