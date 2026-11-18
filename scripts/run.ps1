# Start the workbench (API + built UI) on http://127.0.0.1:8000 (local only).
param([int]$Port = 8000, [switch]$Reload)
$root = Split-Path -Parent $PSScriptRoot
Set-Location (Join-Path $root "backend")
$uvArgs = @("-m", "uvicorn", "hpw_gis.api.main:create_app", "--factory", "--host", "127.0.0.1", "--port", "$Port")
if ($Reload) { $uvArgs += "--reload" }
& (Join-Path $root ".venv\Scripts\python.exe") @uvArgs
