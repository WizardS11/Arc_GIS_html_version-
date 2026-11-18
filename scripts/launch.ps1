# Open the workbench as a desktop-style window (no address bar).
# Starts the GIS engine hidden, opens an Edge app window, and stops the engine when the window closes.
param([int]$Port = 8000)
$root = Split-Path -Parent $PSScriptRoot
$url = "http://127.0.0.1:$Port/"

function Test-Engine {
  try { Invoke-WebRequest "${url}api/health" -UseBasicParsing -TimeoutSec 2 | Out-Null; $true } catch { $false }
}

$server = $null
if (-not (Test-Engine)) {
  $server = Start-Process -PassThru -WindowStyle Hidden `
    -FilePath (Join-Path $root ".venv\Scripts\python.exe") `
    -WorkingDirectory (Join-Path $root "backend") `
    -ArgumentList "-m", "uvicorn", "hpw_gis.api.main:create_app", "--factory", "--host", "127.0.0.1", "--port", "$Port"
  for ($i = 0; $i -lt 60 -and -not (Test-Engine); $i++) { Start-Sleep -Milliseconds 500 }
  if (-not (Test-Engine)) {
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show("The GIS engine did not start. Run scripts\run.ps1 to see the error.", "HPW GIS Workbench") | Out-Null
    exit 1
  }
}

$edge = @("${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
          "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
$profileDir = Join-Path $env:LOCALAPPDATA "HPW-GIS-Workbench\window"
if ($edge) {
  # A dedicated profile keeps this window in its own Edge process, so -Wait returns when it closes.
  Start-Process -Wait -FilePath $edge -ArgumentList "--app=$url", "--user-data-dir=`"$profileDir`"", "--no-first-run", "--start-maximized"
} else {
  Start-Process $url
  Add-Type -AssemblyName PresentationFramework
  [System.Windows.MessageBox]::Show("Click OK to stop the GIS engine.", "HPW GIS Workbench") | Out-Null
}

# Stop only the engine this script started (the venv launcher plus its child python).
if ($server) {
  Get-CimInstance Win32_Process -Filter "ParentProcessId=$($server.Id)" | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
  Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue
}
