param([int]$Port = 8772, [string]$StateDirectory = '')
$ErrorActionPreference = 'Stop'
$state = if ($StateDirectory) { [IO.Path]::GetFullPath($StateDirectory) } else { Join-Path $PSScriptRoot 'state' }
$receipt = Join-Path $state "server-$Port.json"
if (-not (Test-Path -LiteralPath $receipt)) { Write-Host 'No managed demo process recorded.'; exit 0 }
$record = Get-Content -LiteralPath $receipt -Raw | ConvertFrom-Json
$process = Get-Process -Id $record.pid -ErrorAction SilentlyContinue
if ($process) {
    $recordedStart = ([datetime]$record.started).ToUniversalTime()
    if ($process.Path -ne $record.executable -or [Math]::Abs(($process.StartTime.ToUniversalTime() - $recordedStart).TotalMilliseconds) -gt 1) { throw 'Process identity changed; refusing to stop a different process.' }
    Stop-Process -Id $process.Id
}
Remove-Item -LiteralPath $receipt
Write-Host 'Demo stopped. Review notes are retained in state\.'

