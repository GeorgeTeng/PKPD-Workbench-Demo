param([int]$Port = 8767)
$Workspace = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Python = Join-Path $Workspace '.venv-context/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $Python)) { throw 'Python environment not found. Run the project setup first.' }
Set-Location -LiteralPath $Workspace
# Pin this project's launcher even when invoked from a shell with old Claude settings.
$env:CTXCOMP_MODEL_PROVIDER = 'codex'
$env:CTXCOMP_CODEX_MODEL = 'gpt-6-luna'
& $Python -I -X utf8 -m research_pipeline.workbench --port $Port
exit $LASTEXITCODE
