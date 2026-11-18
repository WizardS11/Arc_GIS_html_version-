# One-time setup on a Windows laptop (no admin rights needed).
# Requires only Python 3.11+ (x64 recommended - Windows-on-ARM Python lacks GDAL/pyarrow wheels).
# The UI in web/ is plain HTML/CSS/JS with MapLibre vendored locally: no Node.js, npm or build step.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$py = $env:HPW_PYTHON
if (-not $py) {
    $x64 = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
    if (Test-Path $x64) { $py = $x64 } else { $py = "python" }
}
Write-Host "Using Python: $py"
if (-not (Test-Path ".venv")) { & $py -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install --only-binary=:all: -e "backend[dev]"
& .\.venv\Scripts\python.exe -m hpw_gis.fixtures
Write-Host "`nSetup complete. Start with: .\scripts\run.ps1  then open http://127.0.0.1:8000"
