$ErrorActionPreference = "Stop"
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    throw "Python 3.12+ was not found on PATH."
}
& $python.Source "$PSScriptRoot\run.py" @args
exit $LASTEXITCODE