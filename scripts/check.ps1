# Lint, then run the whole test suite. Exits non-zero on the first failure.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    & "$root\.venv\Scripts\ruff.exe" check .
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & "$root\.venv\Scripts\python.exe" -m pytest -q
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
