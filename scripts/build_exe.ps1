# Build the Windows program into dist\ThermalFEA with PyInstaller, then smoke-test it.
# Uses the project's virtual environment only. Exits non-zero on any failure.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = "$root\.venv\Scripts\python.exe"
Push-Location $root
try {
    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    & $python -m PyInstaller packaging\thermalfea.spec --noconfirm --distpath dist --workpath build
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Write-Host ("Build time: {0:N0} s" -f $watch.Elapsed.TotalSeconds)
    $bytes = (Get-ChildItem dist\ThermalFEA -Recurse -File | Measure-Object -Property Length -Sum).Sum
    Write-Host ("dist\ThermalFEA: {0:N0} MB" -f ($bytes / 1MB))
    & $python scripts\smoke_exe.py --dist dist\ThermalFEA
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
