<#
  ImageFabric launcher.
  Starts the FastAPI backend (port 8260) and the Vite dev server (port 5173),
  each in its own window. First run bootstraps the venv + npm deps.

  Usage:   .\scripts\run.ps1
#>

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$venvPy = Join-Path $root ".venv\Scripts\python.exe"

# --- bootstrap backend venv ---
if (-not (Test-Path $venvPy)) {
    Write-Host "[setup] creating venv + installing backend deps..." -ForegroundColor Cyan
    python -m venv .venv
    & $venvPy -m pip install --upgrade pip
    & $venvPy -m pip install -r backend\requirements.txt
}

# --- bootstrap frontend deps ---
if (-not (Test-Path (Join-Path $root "frontend\node_modules"))) {
    Write-Host "[setup] installing frontend deps..." -ForegroundColor Cyan
    Push-Location frontend; npm install; Pop-Location
}

Write-Host "[run] backend  -> http://127.0.0.1:8260" -ForegroundColor Green
Write-Host "[run] frontend -> http://localhost:5173" -ForegroundColor Green

# Backend (with autoreload). Working dir = backend so `app.main` resolves.
Start-Process powershell -ArgumentList @(
    "-NoExit", "-Command",
    "Set-Location '$root\backend'; & '$venvPy' -m uvicorn app.main:app --host 127.0.0.1 --port 8260 --reload"
)

# Frontend dev server.
Start-Process powershell -ArgumentList @(
    "-NoExit", "-Command",
    "Set-Location '$root\frontend'; npm run dev"
)

Write-Host "`nBoth started in separate windows. Open http://localhost:5173" -ForegroundColor Yellow
