param([switch]$Shifted, [switch]$Detection, [switch]$Dashboard)
$ErrorActionPreference = "Stop"
# Repo root is two levels above this script (scripts/demo -> repo).
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $Root
Write-Host "[1/6] repo: $Root"
& { $ErrorActionPreference = "Continue"; docker info *> $null }
if ($LASTEXITCODE -ne 0) { Write-Host "Start Docker Desktop first"; exit 1 }
Write-Host "[2/6] docker ok; starting db + mqtt..."
& { $ErrorActionPreference = "Continue"; docker compose up -d db mqtt }
$healthy = $false
for ($i = 0; $i -lt 12; $i++) {
  $s = & { $ErrorActionPreference = "Continue"; docker inspect -f '{{.State.Health.Status}}' joulemitra-db-1 2>$null }
  if ($s -eq "healthy") { $healthy = $true; break }
  Start-Sleep -Seconds 5
}
if (-not $healthy) { Write-Host "db never became healthy"; exit 1 }
Write-Host "[3/6] db healthy; init schema..."
& .\.venv\Scripts\python.exe scripts\setup\init_db.py
if ($LASTEXITCODE -ne 0) { Write-Host "init_db failed"; exit 1 }
$startedBackend = $false
$backend = $null
try { Invoke-WebRequest -UseBasicParsing http://localhost:8000/health/components -TimeoutSec 5 | Out-Null; Write-Host "[4/6] reusing backend on :8000" }
catch {
  Write-Host "[4/6] starting backend on :8000..."
  $backend = Start-Process -FilePath ".\.venv\Scripts\python.exe" -ArgumentList "-m", "uvicorn", "apps.backend.main:app", "--port", "8000" -RedirectStandardOutput "$env:TEMP\joulemitra-backend-out.log" -RedirectStandardError "$env:TEMP\joulemitra-backend-err.log" -WindowStyle Hidden -PassThru
  $startedBackend = $true
  $up = $false
  for ($i = 0; $i -lt 30; $i++) {
    try { Invoke-WebRequest -UseBasicParsing http://localhost:8000/health/components -TimeoutSec 2 | Out-Null; $up = $true; break } catch { Start-Sleep -Seconds 1 }
  }
  if (-not $up) { Stop-Process -Id $backend.Id -Force; Write-Host "backend failed to start (see $env:TEMP\joulemitra-backend-err.log)"; exit 1 }
}
$demo = @("scripts/demo/run_demo.py")
if ($Detection) { $demo = @("scripts/demo/phase2_table.py") }
elseif ($Shifted) { $demo += "--shifted" }
$demoCode = 1
try {
  Write-Host "[5/6] running $($demo -join ' ')..."
  & .\.venv\Scripts\python.exe @demo
  $demoCode = $LASTEXITCODE
  if ($Dashboard) {
    Write-Host "[6/6] starting dashboard on :8501..."
    $dash = Start-Process -FilePath ".\.venv\Scripts\python.exe" -ArgumentList "-m", "streamlit", "run", "apps/dashboard/app.py", "--server.port", "8501" -RedirectStandardOutput "$env:TEMP\joulemitra-dash-out.log" -RedirectStandardError "$env:TEMP\joulemitra-dash-err.log" -WindowStyle Hidden -PassThru
    Start-Sleep -Seconds 3
    Start-Process "http://localhost:8501"
    if ($startedBackend) { Write-Host "Dashboard (PID $($dash.Id)) + backend (PID $($backend.Id)) left running. Stop with: Stop-Process -Id $($backend.Id), $($dash.Id)" }
    else { Write-Host "Dashboard (PID $($dash.Id)) left running (backend on :8000 was already running). Stop with: Stop-Process -Id $($dash.Id)" }
  }
}
finally {
  if ($startedBackend -and -not $Dashboard) { Stop-Process -Id $backend.Id -Force; Write-Host "[6/6] backend stopped." }
}
exit $demoCode
