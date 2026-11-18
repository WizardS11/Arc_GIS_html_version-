# Run backend tests, plus a JavaScript syntax check of the web UI when Node.js is available.
$root = Split-Path -Parent $PSScriptRoot
Set-Location (Join-Path $root "backend")
& (Join-Path $root ".venv\Scripts\python.exe") -m pytest -q
$code = $LASTEXITCODE
if (Get-Command node -ErrorAction SilentlyContinue) {
    Get-ChildItem (Join-Path $root "web\js\*.js") | ForEach-Object {
        node --check $_.FullName
        if ($LASTEXITCODE) { $code = 1; Write-Host "Syntax error in $($_.Name)" }
    }
    Write-Host "web/js syntax check done"
}
exit $code
