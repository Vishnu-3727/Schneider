# JouleMitra Impact Console — stage data, then screenshot all 6 screens.
#
# Sequence (each stage replaces the previous data; run_demo.py and
# phase2_table.py are NOT edited):
#   Stage A (detection, all machines): truncate -> simulator 7 NORMAL days +
#     24 h IDLE_WASTE --post -> baseline fit [end-8d, end-1d] -> anomalies
#     detect [end-1d, end] -> machine-health fit [end-8d, end-1d] + score
#     [end-1d, end] -> capture 01-plant, 02-detect, 03-health.
#     (Stage A already fits + scores health for all three machines, and
#     #health also renders the insights list there, so 03-health is
#     captured in Stage A, not Stage C.)
#   Stage B (guardrail): run_demo.py --shifted (operating conditions shift,
#     expect NOT_COMPARABLE) -> capture 06b-impact-guardrail (#impact).
#     #impact renders its NOT_COMPARABLE panel from the latest NOT_COMPARABLE
#     row when one exists; the VERIFIED hero shows no verified saving honestly.
#   Stage C (lifecycle): run_demo.py (expect VERIFIED) -> capture
#     04-optimise, 05-act, 06-impact. #impact renders the VERIFIED hero from
#     the latest VERIFIED row when one exists.
#
# Usage: powershell -ExecutionPolicy Bypass -File scripts\demo\capture_console.ps1

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $Root
Write-Host "[1/7] repo: $Root"

& { $ErrorActionPreference = "Continue"; docker info *> $null }
if ($LASTEXITCODE -ne 0) { Write-Host "Start Docker Desktop first"; exit 1 }

$edge = Join-Path ${env:ProgramFiles(x86)} "Microsoft\Edge\Application\msedge.exe"
if (-not (Test-Path -LiteralPath $edge)) { Write-Host "Edge not found at $edge"; exit 1 }

Write-Host "[2/7] docker ok; starting db + mqtt..."
& { $ErrorActionPreference = "Continue"; docker compose up -d db mqtt }
$healthy = $false
for ($i = 0; $i -lt 12; $i++) {
  $s = & { $ErrorActionPreference = "Continue"; docker inspect -f '{{.State.Health.Status}}' joulemitra-db-1 2>$null }
  if ($s -eq "healthy") { $healthy = $true; break }
  Start-Sleep -Seconds 5
}
if (-not $healthy) { Write-Host "db never became healthy"; exit 1 }

Write-Host "[3/7] db healthy; init schema..."
& .\.venv\Scripts\python.exe scripts\setup\init_db.py
if ($LASTEXITCODE -ne 0) { Write-Host "init_db failed"; exit 1 }

$startedBackend = $false
$backend = $null
try { Invoke-WebRequest -UseBasicParsing http://localhost:8000/health/components -TimeoutSec 5 | Out-Null; Write-Host "[4/7] reusing backend on :8000" }
catch {
  Write-Host "[4/7] starting backend on :8000..."
  $backend = Start-Process -FilePath ".\.venv\Scripts\python.exe" -ArgumentList "-m", "uvicorn", "apps.backend.main:app", "--port", "8000" -RedirectStandardOutput "$env:TEMP\joulemitra-backend-out.log" -RedirectStandardError "$env:TEMP\joulemitra-backend-err.log" -WindowStyle Hidden -PassThru
  $startedBackend = $true
  $up = $false
  for ($i = 0; $i -lt 30; $i++) {
    try { Invoke-WebRequest -UseBasicParsing http://localhost:8000/health/components -TimeoutSec 2 | Out-Null; $up = $true; break } catch { Start-Sleep -Seconds 1 }
  }
  if (-not $up) { Stop-Process -Id $backend.Id -Force; Write-Host "backend failed to start (see $env:TEMP\joulemitra-backend-err.log)"; exit 1 }
}

function Invoke-ApiPost($Path, $Body) {
  try {
    Invoke-RestMethod -Method Post -Uri ("http://localhost:8000" + $Path) -ContentType "application/json" -Body ($Body | ConvertTo-Json) -TimeoutSec 300 | Out-Null
  }
  catch {
    Write-Host "POST $Path failed: $($_.Exception.Message)"; exit 1
  }
}

function Capture-Screen($Screen, $File) {
  $url = "http://localhost:8000/console/?static=1#$Screen"
  # Fresh profile every run: a reused profile serves the previous round's
  # cached console.js and the deck would screenshot stale code.
  $prof = Join-Path $env:TEMP ("edge-shot-" + $Screen)
  if (Test-Path -LiteralPath $prof) { Remove-Item -LiteralPath $prof -Recurse -Force }
  if (Test-Path -LiteralPath $File) { Remove-Item -LiteralPath $File -Force }
  & { $ErrorActionPreference = "Continue"; & $edge --headless=new --disable-gpu --hide-scrollbars --user-data-dir=$prof --window-size=1920,1080 --virtual-time-budget=15000 --screenshot=$File $url }
  if ($LASTEXITCODE -ne 0) { Write-Host "capture $Screen failed"; exit 1 }
  # Headless Edge returns before the PNG hits disk: wait until the file
  # exists and its size is stable, so the next stage never pulls the DB
  # (or stops the backend) from under a still-rendering page.
  $stable = 0
  $lastSize = -1
  for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 2
    if (Test-Path -LiteralPath $File) {
      $sz = (Get-Item -LiteralPath $File).Length
      if ($sz -eq $lastSize -and $sz -gt 0) { $stable++; if ($stable -ge 2) { break } }
      else { $stable = 0; $lastSize = $sz }
    }
  }
  if ($stable -lt 2) { Write-Host "capture ${Screen}: PNG never stabilised"; exit 1 }
  Write-Host "captured $File"
}

$shotDir = Join-Path $Root "docs\deck\screens"
if (-not (Test-Path -LiteralPath $shotDir)) { New-Item -ItemType Directory -Path $shotDir | Out-Null }

try {
  Write-Host "[5/7] Stage A: detection data (all machines)..."
  & .\.venv\Scripts\python.exe -c "from scripts.demo.run_demo import truncate; truncate()"
  if ($LASTEXITCODE -ne 0) { Write-Host "truncate failed"; exit 1 }
  $now = Get-Date
  # Floor to the MINUTE (not the hour): staging must end near "now" or the
  # Plant screen marks every machine STALE (15 min threshold).
  $endLocal = Get-Date -Year $now.Year -Month $now.Month -Day $now.Day -Hour $now.Hour -Minute $now.Minute -Second 0
  $endIso = $endLocal.ToString("yyyy-MM-ddTHH:mm:ss") + "+05:30"
  $fitStart = $endLocal.AddDays(-8).ToString("yyyy-MM-ddTHH:mm:ss") + "+05:30"
  $fitEnd = $endLocal.AddDays(-1).ToString("yyyy-MM-ddTHH:mm:ss") + "+05:30"
  & .\.venv\Scripts\python.exe -m apps.simulator --normal-days 7 --scenario IDLE_WASTE --hours 24 --post --end $endIso
  if ($LASTEXITCODE -ne 0) { Write-Host "simulator post failed"; exit 1 }
  Invoke-ApiPost "/energy/baseline/fit" @{ start = $fitStart; end = $fitEnd }
  Invoke-ApiPost "/energy/anomalies/detect" @{ start = $fitEnd; end = $endIso }
  Invoke-ApiPost "/machine-health/fit" @{ start = $fitStart; end = $fitEnd }
  Invoke-ApiPost "/machine-health/score" @{ start = $fitEnd; end = $endIso }
  Capture-Screen "plant" (Join-Path $shotDir "01-plant.png")
  Capture-Screen "detect" (Join-Path $shotDir "02-detect.png")
  Capture-Screen "health" (Join-Path $shotDir "03-health.png")

  Write-Host "[6/7] Stage B: guardrail (shifted)..."
  & .\.venv\Scripts\python.exe scripts/demo/run_demo.py --shifted
  if ($LASTEXITCODE -ne 0) { Write-Host "run_demo --shifted failed"; exit 1 }
  Capture-Screen "impact" (Join-Path $shotDir "06b-impact-guardrail.png")

  Write-Host "[7/7] Stage C: lifecycle..."
  & .\.venv\Scripts\python.exe scripts/demo/run_demo.py
  if ($LASTEXITCODE -ne 0) { Write-Host "run_demo failed"; exit 1 }
  Capture-Screen "optimise" (Join-Path $shotDir "04-optimise.png")
  Capture-Screen "act" (Join-Path $shotDir "05-act.png")
  Capture-Screen "impact" (Join-Path $shotDir "06-impact.png")
}
finally {
  if ($startedBackend) { Stop-Process -Id $backend.Id -Force; Write-Host "backend stopped." }
}

Write-Host "PNGs:"
Start-Sleep -Seconds 10
$ok = $true
$expected = @("01-plant.png", "02-detect.png", "03-health.png", "04-optimise.png",
  "05-act.png", "06-impact.png", "06b-impact-guardrail.png")
foreach ($name in $expected) {
  $p = Join-Path $shotDir $name
  if (-not (Test-Path -LiteralPath $p)) { Write-Host ("  {0}  MISSING" -f $name); $ok = $false }
  else {
    $kb = [math]::Round((Get-Item -LiteralPath $p).Length / 1KB, 1)
    Write-Host ("  {0}  {1} KB" -f $name, $kb)
    if ((Get-Item -LiteralPath $p).Length -le 50KB) { $ok = $false }
  }
}
if (-not $ok) { Write-Host "a PNG is missing or <= 50 KB"; exit 1 }
