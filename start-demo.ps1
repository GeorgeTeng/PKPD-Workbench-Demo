param([int]$Port = 8772, [switch]$NoBrowser,
      [ValidateSet('codex','openai','claude')][string]$Provider = 'codex',
      [string]$Model = '',
      [ValidateSet('low','medium','high','xhigh','max','ultra')][string]$ReasoningEffort = 'high',
      [string]$ApiBase = '', [string]$StateDirectory = '', [switch]$AllowResponseReuse)
$ErrorActionPreference = 'Stop'
$demoRoot = $PSScriptRoot
$python = Join-Path $demoRoot 'runtime\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Portable runtime missing. Extract the complete Windows release ZIP.' }
$state = if ($StateDirectory) { [IO.Path]::GetFullPath($StateDirectory) } else { Join-Path $demoRoot 'state' }
New-Item -ItemType Directory -Force -Path $state | Out-Null
$url = "http://127.0.0.1:$Port"
$receipt = Join-Path $state "server-$Port.json"
$existing = $null
try { $existing = Invoke-RestMethod "$url/demo-api/health" -TimeoutSec 2 } catch { }
if ($existing) {
    if ($existing.mode -ne 'DEMO' -or $existing.backend -ne 'research_pipeline.workbench') { throw "Port $Port is occupied by another service." }
    if ($StateDirectory -and -not (Test-Path -LiteralPath $receipt)) { throw "Port $Port already serves another state directory. Stop that server or choose a different port." }
    $capabilities = Invoke-RestMethod "$url/workspace-api/capabilities" -TimeoutSec 5
    $expectedModel = if ($Model) { $Model } elseif ($Provider -eq 'codex') { 'gpt-6.1-sol' } else { '' }
    if ($capabilities.model_executor.provider -ne $Provider -or
        ($expectedModel -and $capabilities.model_executor.requested_model -ne $expectedModel) -or
        ($Provider -eq 'codex' -and $capabilities.model_executor.requested_reasoning_effort -ne $ReasoningEffort) -or
        $capabilities.response_reuse_disabled -ne (-not $AllowResponseReuse)) {
        throw 'The running server has different model/reuse settings. Stop it before changing configuration.'
    }
    Write-Host "Demo is already available at $url"
    if (-not $NoBrowser) { Start-Process $url }
    exit 0
}
$arguments = @('-I', '-B', '-X', 'utf8', ('"' + (Join-Path $demoRoot 'app.py') + '"'), '--port', $Port)
$arguments += @('--state', ('"' + $state + '"'))
if ($AllowResponseReuse) { $arguments += '--allow-response-reuse' }
$arguments += @('--provider', $Provider, '--reasoning-effort', $ReasoningEffort)
if ($Model) {
    if ($Model -match '[\s"`]' ) { throw 'Use a model identifier without whitespace or quotes.' }
    $arguments += @('--model', $Model)
}
if ($ApiBase) {
    if ($ApiBase -match '[\s"`]' ) { throw 'Use an API base URL without whitespace or quotes.' }
    $arguments += @('--api-base', $ApiBase)
}
$process = Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $demoRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $state "server-$Port.stdout.log") -RedirectStandardError (Join-Path $state "server-$Port.stderr.log")
@{ pid = $process.Id; started = $process.StartTime.ToUniversalTime().ToString('o'); executable = $python; port = $Port } | ConvertTo-Json | Set-Content -LiteralPath $receipt -Encoding UTF8
for ($attempt = 0; $attempt -lt 40; $attempt++) {
    if ($process.HasExited) { throw "Demo exited. See state\server-$Port.stderr.log." }
    try {
        $health = Invoke-RestMethod "$url/demo-api/health" -TimeoutSec 1
        if ($health.status -eq 'OK') {
            Write-Host "Demo ready: $url"
            if (-not $NoBrowser) { Start-Process $url }
            exit 0
        }
    } catch { }
    Start-Sleep -Milliseconds 300
}
throw "Startup timed out. See state\server-$Port.stderr.log."

