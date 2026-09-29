# JouleMitra console — stage data, then screenshot every screen for the deck.
#
# Sequence (run_demo.py truncates and rebuilds the dev DB each time):
#   Stage A (guardrail): run_demo.py --shifted (operating conditions shift,
#     expect NOT_COMPARABLE) -> capture 10b-prove-guardrail (#impact, the
#     NOT_COMPARABLE refusal hero).
#   Stage B (lifecycle): run_demo.py (expect VERIFIED) -> capture every screen:
#     01-plant (#plant), 01b-plant-3d (?view=3d#plant), 02-detect (#detect),
#     03-heats (#heats), 04-twin (#twin), 05-bill (#bill), 06-health (#health),
#     07-plan (#optimise), 08-brief (#brief), 08b-brief-ta (?lang=ta#brief),
#     09-act (#act), 10-prove (#impact), 10c-prove-trail (?trail=impact#impact),
#     11-scale (#payback).
#
# Edge runs headless at 1920x1080 with ?static=1 plus swiftshader flags so the
# 3D screens render. A running backend on :8000 is reused when one answers.
#
# Usage: powershell -ExecutionPolicy Bypass -File scripts\demo\capture_console.ps1

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $Root
Write-Host "[1/4] repo: $Root"

$edge = Join-Path ${env:ProgramFiles(x86)} "Microsoft\Edge\Application\msedge.exe"
if (-not (Test-Path -LiteralPath $edge)) { Write-Host "Edge not found at $edge"; exit 1 }

$tmpRoot = Join-Path $Root ".worker-tmp"
if (-not (Test-Path -LiteralPath $tmpRoot)) { New-Item -ItemType Directory -Path $tmpRoot | Out-Null }

$shotDir = Join-Path $Root "docs\deck\screens"
if (-not (Test-Path -LiteralPath $shotDir)) { New-Item -ItemType Directory -Path $shotDir | Out-Null }
Write-Host "[2/4] deleting old PNGs..."
Get-ChildItem -Path $shotDir -Filter "*.png" | ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force }

$startedBackend = $false
$backend = $null
try { Invoke-WebRequest -UseBasicParsing http://localhost:8000/health/components -TimeoutSec 5 | Out-Null; Write-Host "[3/4] reusing backend on :8000" }
catch {
  Write-Host "[3/4] starting backend on :8000..."
  $env:DEMO_MODE = "true"
  $backend = Start-Process -FilePath ".\.venv\Scripts\python.exe" -ArgumentList "-m", "uvicorn", "apps.backend.main:app", "--port", "8000" -RedirectStandardOutput (Join-Path $tmpRoot "joulemitra-backend-out.log") -RedirectStandardError (Join-Path $tmpRoot "joulemitra-backend-err.log") -WindowStyle Hidden -PassThru
  $startedBackend = $true
  $up = $false
  for ($i = 0; $i -lt 30; $i++) {
    try { Invoke-WebRequest -UseBasicParsing http://localhost:8000/health/components -TimeoutSec 2 | Out-Null; $up = $true; break } catch { Start-Sleep -Seconds 1 }
  }
  if (-not $up) { Stop-Process -Id $backend.Id -Force; Write-Host "backend failed to start"; exit 1 }
}

function Capture-Screen($Query, $Hash, $File) {
  $url = "http://localhost:8000/console/" + $Query + "#" + $Hash
  $base = [System.IO.Path]::GetFileNameWithoutExtension($File)
  $prof = Join-Path $tmpRoot ("edge-shot-" + $base)
  if (Test-Path -LiteralPath $prof) { Remove-Item -LiteralPath $prof -Recurse -Force }
  if (Test-Path -LiteralPath $File) { Remove-Item -LiteralPath $File -Force }
  & { $ErrorActionPreference = "Continue"; & $edge --headless=new --hide-scrollbars --user-data-dir=$prof --window-size=1920,1080 --virtual-time-budget=25000 --use-angle=swiftshader --enable-unsafe-swiftshader --screenshot=$File $url }
  if ($LASTEXITCODE -ne 0) { Write-Host "capture $File failed"; exit 1 }
  # Headless Edge returns before the PNG hits disk: wait until the file
  # exists and its size is stable, so the next capture never runs against
  # a still-rendering page.
  $stable = 0
  $lastSize = -1
  for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 2
    if (Test-Path -LiteralPath $File) {
      $sz = (Get-Item -LiteralPath $File).Length
      if ($sz -eq $lastSize) {
        if ($sz -gt 0) { $stable++ }
        if ($stable -ge 2) { break }
      }
      else { $stable = 0; $lastSize = $sz }
    }
  }
  if ($stable -lt 2) { Write-Host "capture ${File}: PNG never stabilised"; exit 1 }
  Write-Host "captured $File"
}

try {
  Write-Host "[4/4] Stage A: guardrail (shifted)..."
  & .\.venv\Scripts\python.exe scripts/demo/run_demo.py --shifted
  if ($LASTEXITCODE -ne 0) { Write-Host "run_demo --shifted failed"; exit 1 }
  Capture-Screen "?static=1" "impact" (Join-Path $shotDir "10b-prove-guardrail.png")

  Write-Host "[4/4] Stage B: lifecycle..."
  & .\.venv\Scripts\python.exe scripts/demo/run_demo.py
  if ($LASTEXITCODE -ne 0) { Write-Host "run_demo failed"; exit 1 }
  Capture-Screen "?static=1" "plant" (Join-Path $shotDir "01-plant.png")
  Capture-Screen "?static=1&view=3d" "plant" (Join-Path $shotDir "01b-plant-3d.png")
  Capture-Screen "?static=1" "detect" (Join-Path $shotDir "02-detect.png")
  Capture-Screen "?static=1" "heats" (Join-Path $shotDir "03-heats.png")
  Capture-Screen "?static=1" "twin" (Join-Path $shotDir "04-twin.png")
  Capture-Screen "?static=1" "bill" (Join-Path $shotDir "05-bill.png")
  Capture-Screen "?static=1" "health" (Join-Path $shotDir "06-health.png")
  Capture-Screen "?static=1" "optimise" (Join-Path $shotDir "07-plan.png")
  Capture-Screen "?static=1" "brief" (Join-Path $shotDir "08-brief.png")
  Capture-Screen "?static=1&lang=ta" "brief" (Join-Path $shotDir "08b-brief-ta.png")
  Capture-Screen "?static=1" "act" (Join-Path $shotDir "09-act.png")
  Capture-Screen "?static=1" "impact" (Join-Path $shotDir "10-prove.png")
  Capture-Screen "?static=1&trail=impact" "impact" (Join-Path $shotDir "10c-prove-trail.png")
  Capture-Screen "?static=1" "payback" (Join-Path $shotDir "11-scale.png")
}
finally {
  if ($startedBackend) { Stop-Process -Id $backend.Id -Force; Write-Host "backend stopped." }
}

Write-Host "PNGs:"
Start-Sleep -Seconds 10
$ok = $true
$expected = @("01-plant.png", "01b-plant-3d.png", "02-detect.png", "03-heats.png",
  "04-twin.png", "05-bill.png", "06-health.png", "07-plan.png", "08-brief.png",
  "08b-brief-ta.png", "09-act.png", "10-prove.png", "10c-prove-trail.png",
  "10b-prove-guardrail.png", "11-scale.png")
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
