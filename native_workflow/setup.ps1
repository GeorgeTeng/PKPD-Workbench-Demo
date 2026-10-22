# Creates .venv-context at the repository root and installs both backend packages (editable)
# with the dependency versions recorded in requirements-tested.txt.
param([string]$Python = '')
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$cc = Join-Path $root 'backend\context_compression'
$rp = Join-Path $root 'backend\research_pipeline'
if (-not $Python) {
    $found = Get-Command python -ErrorAction SilentlyContinue | Where-Object { $_.Source -notlike '*WindowsApps*' } | Select-Object -First 1
    if (-not $found) { throw 'Python 3.12 was not found on PATH.' }
    $Python = $found.Source
}
$venv = Join-Path $root '.venv-context'
$py = Join-Path $venv 'Scripts\python.exe'
$uv = Get-Command uv -ErrorAction SilentlyContinue
if (-not (Test-Path -LiteralPath $py)) {
    if ($uv) { & $uv.Source venv $venv --python $Python } else { & $Python -m venv $venv }
    if ($LASTEXITCODE -ne 0) { throw 'Could not create .venv-context.' }
}
$installArgs = @('-r', "$rp\requirements-tested.txt", '-r', "$cc\requirements-tested.txt",
                 '-e', "$cc[documents,test]", '-e', "$rp[test,workflow]")
if ($uv) { & $uv.Source pip install --python $py @installArgs }
else { & $py -m pip install @installArgs }
if ($LASTEXITCODE -ne 0) { throw 'Package installation failed.' }
& $py -I -c "import sys, research_pipeline, ctxcomp; print('Python', sys.version.split()[0], '- research_pipeline and ctxcomp ready')"
