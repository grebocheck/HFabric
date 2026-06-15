<#
  HFabric launcher — ONE window, both servers.

    .\scripts\run.ps1          # Auto mode (hardware probe selects REAL/STUB)
    .\scripts\run.ps1 -Stub    # STUB mode (full pipeline, no GPU/ML stack)
    .\scripts\run.ps1 -Prod    # one-port production mode (serves frontend/dist)

  Before starting it frees the backend/frontend ports, killing stale instances
  left over from earlier runs. Those leftovers are the cause of the
  "WinError 10013 / socket forbidden" failure: a previous backend was still
  holding port 8260, so a new one could not bind. Bootstraps venv + npm on the
  first run, then runs the FastAPI backend and the Vite dev server in THIS
  console. Ctrl+C stops both.
#>
param(
    [switch]$Stub,
    [switch]$Prod,
    [int]$Port = 0,
    [int]$FrontendPort = 0,
    [string]$BindHost = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$venvPy = Join-Path $root ".venv\Scripts\python.exe"

function Import-DotEnv([string]$Path) {
    if (-not (Test-Path $Path)) { return }
    foreach ($line in Get-Content $Path) {
        $trimmed = $line.Trim()
        if ([string]::IsNullOrWhiteSpace($trimmed) -or $trimmed.StartsWith("#")) { continue }

        $eq = $trimmed.IndexOf("=")
        if ($eq -lt 1) { continue }

        $key = $trimmed.Substring(0, $eq).Trim()
        $value = $trimmed.Substring($eq + 1).Trim()
        if (
            ($value.StartsWith('"') -and $value.EndsWith('"')) -or
            ($value.StartsWith("'") -and $value.EndsWith("'"))
        ) {
            $value = $value.Substring(1, $value.Length - 2)
        }

        if ([Environment]::GetEnvironmentVariable($key, "Process") -eq $null) {
            Set-Item -Path "Env:$key" -Value $value
        }
    }
}

function Get-EnvInt([string]$Name, [int]$Default) {
    $value = [Environment]::GetEnvironmentVariable($Name, "Process")
    if ([string]::IsNullOrWhiteSpace($value)) { return $Default }
    return [int]$value
}

function Test-Truthy([string]$Value) {
    if ([string]::IsNullOrWhiteSpace($Value)) { return $false }
    return @("1", "true", "yes", "on").Contains($Value.ToLowerInvariant())
}

function Resolve-InstallProfile([string]$Prefer = "") {
    $profilePython = "python"
    if (Test-Path $venvPy) { $profilePython = $venvPy }

    $args = @("scripts\install_profiles.py")
    if (-not [string]::IsNullOrWhiteSpace($Prefer)) {
        $args += @("--prefer", $Prefer)
    }

    $json = & $profilePython @args 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[profile] hardware profile resolution failed" -ForegroundColor Red
        Write-Host $json -ForegroundColor Red
        exit 1
    }
    return (($json -join "`n") | ConvertFrom-Json)
}

function Write-ProfileSummary($Profile) {
    if (-not $Profile) { return }
    $profileId = [string]$Profile.selected_profile
    $tier = [string]$Profile.hardware_tier
    if ([string]::IsNullOrWhiteSpace($tier)) { $tier = "unknown" }

    Write-Host "[profile] $profileId ($tier)" -ForegroundColor Cyan
    if (-not [string]::IsNullOrWhiteSpace($Profile.reason)) {
        Write-Host "[profile] $($Profile.reason)" -ForegroundColor DarkGray
    }
    foreach ($warning in @($Profile.warnings)) {
        if (-not [string]::IsNullOrWhiteSpace($warning)) {
            Write-Host "[profile] warning: $warning" -ForegroundColor Yellow
        }
    }
}

function Write-AcceleratorInstallHint($Profile) {
    Write-Host "[setup] REAL mode also needs the accelerator stack." -ForegroundColor Yellow
    if (-not $Profile) {
        Write-Host "        Run setup.bat real or .\setup.ps1 -Real to install it." -ForegroundColor Yellow
        return
    }

    $torchPackages = @($Profile.install.torch.packages)
    $indexUrl = [string]$Profile.install.torch.index_url
    if ($torchPackages.Count -gt 0 -and -not [string]::IsNullOrWhiteSpace($indexUrl)) {
        Write-Host "        & '$venvPy' -m pip install $($torchPackages -join ' ') --index-url $indexUrl" -ForegroundColor Yellow
    } elseif ($torchPackages.Count -gt 0) {
        Write-Host "        & '$venvPy' -m pip install $($torchPackages -join ' ')" -ForegroundColor Yellow
    }
    foreach ($req in @($Profile.install.requirements)) {
        if (-not [string]::IsNullOrWhiteSpace($req)) {
            Write-Host "        & '$venvPy' -m pip install -r $req" -ForegroundColor Yellow
        }
    }
    Write-Host "        Or run setup.bat real / .\setup.ps1 -Real for the guided install." -ForegroundColor Yellow
}

function Get-NewestWriteUtc([string[]]$Paths) {
    $latest = [datetime]::MinValue
    foreach ($path in $Paths) {
        if (-not (Test-Path $path)) { continue }
        Get-ChildItem -LiteralPath $path -Recurse -File -ErrorAction SilentlyContinue | ForEach-Object {
            if ($_.LastWriteTimeUtc -gt $latest) { $latest = $_.LastWriteTimeUtc }
        }
    }
    return $latest
}

function Test-DistStale {
    $frontend = Join-Path $root "frontend"
    $distIndex = Join-Path $frontend "dist\index.html"
    if (-not (Test-Path $distIndex)) { return $true }
    $sourceLatest = Get-NewestWriteUtc @(
        (Join-Path $frontend "src"),
        (Join-Path $frontend "public"),
        (Join-Path $frontend "index.html"),
        (Join-Path $frontend "package.json"),
        (Join-Path $frontend "package-lock.json"),
        (Join-Path $frontend "vite.config.ts"),
        (Join-Path $frontend "tsconfig.json")
    )
    return $sourceLatest -gt (Get-Item $distIndex).LastWriteTimeUtc
}

function Wait-Health([string]$Url) {
    $deadline = (Get-Date).AddSeconds(45)
    while ((Get-Date) -lt $deadline) {
        try {
            $res = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2
            if ($res.StatusCode -eq 200) { return $true }
        } catch {}
        Start-Sleep -Milliseconds 500
    }
    return $false
}

Import-DotEnv (Join-Path $root ".env")

if ($Port -le 0) { $Port = Get-EnvInt "HFAB_PORT" 8260 }
if ($FrontendPort -le 0) { $FrontendPort = Get-EnvInt "HFAB_FRONTEND_PORT" 5173 }
if ([string]::IsNullOrWhiteSpace($BindHost)) {
    if ([string]::IsNullOrWhiteSpace($env:HFAB_HOST)) {
        $BindHost = "127.0.0.1"
    } else {
        $BindHost = $env:HFAB_HOST
    }
}

$env:HFAB_HOST = $BindHost
$env:HFAB_PORT = "$Port"

$selectedProfile = $null
$stubModeRaw = [Environment]::GetEnvironmentVariable("HFAB_STUB_MODE", "Process")
if ($Stub) {
    $env:HFAB_STUB_MODE = "true"
    Write-Host "[mode] STUB - architectural pipeline only, no GPU/ML stack" -ForegroundColor DarkYellow
} elseif (-not [string]::IsNullOrWhiteSpace($stubModeRaw)) {
    if (Test-Truthy $stubModeRaw) {
        $env:HFAB_STUB_MODE = "true"
        Write-Host "[mode] STUB - HFAB_STUB_MODE override" -ForegroundColor DarkYellow
    } else {
        $env:HFAB_STUB_MODE = "false"
        Write-Host "[mode] REAL - HFAB_STUB_MODE override" -ForegroundColor Green
    }
} else {
    $selectedProfile = Resolve-InstallProfile
    Write-ProfileSummary $selectedProfile
    if ([string]$selectedProfile.selected_profile -eq "cpu-safe") {
        $env:HFAB_STUB_MODE = "true"
        Write-Host "[mode] STUB - CPU-safe profile selected automatically" -ForegroundColor DarkYellow
    } else {
        $env:HFAB_STUB_MODE = "false"
        Write-Host "[mode] REAL - $($selectedProfile.selected_profile) profile selected automatically" -ForegroundColor Green
    }
}
$isStubMode = Test-Truthy $env:HFAB_STUB_MODE

# .env can opt into one-port serving permanently (HFAB_SERVE_FRONTEND=true):
# then a plain double-click behaves exactly like -Prod, so the UI lives on the
# same host:port the .env advertises instead of a localhost-only Vite :5173.
if (-not $Prod -and (Test-Truthy $env:HFAB_SERVE_FRONTEND)) { $Prod = $true }
if ($Prod) {
    $env:HFAB_SERVE_FRONTEND = "true"
    Write-Host "[mode] PROD - FastAPI serves frontend/dist on one port" -ForegroundColor Cyan
} elseif ([string]::IsNullOrWhiteSpace($env:HFAB_SERVE_FRONTEND)) {
    $env:HFAB_SERVE_FRONTEND = "false"
}

# --- free ports held by stale instances of this app ---------------------------
function Stop-Port([int]$p) {
    $owners = Get-NetTCPConnection -LocalPort $p -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($procId in $owners) {
        if ($procId -and $procId -ne 0) {
            try {
                $name = (Get-Process -Id $procId -ErrorAction Stop).ProcessName
                Write-Host "[ports] port $p busy -> stopping $name (pid $procId)" -ForegroundColor DarkGray
                Stop-Process -Id $procId -Force -ErrorAction Stop
            } catch {}
        }
    }
}
Stop-Port $Port
Stop-Port (Get-EnvInt "HFAB_LLAMA_PORT" 8261)          # llama-server (LLM)
Stop-Port (Get-EnvInt "HFAB_LLAMA_EMBED_PORT" 8262)    # llama-server (RAG embeddings)
Stop-Port $FrontendPort

# Safety net: a run closed via the window 'X' (not Ctrl+C) skips the finally
# block below, so its child llama processes can survive — orphaned, holding
# RAM/VRAM and shrinking the "available RAM" the pre-load guard checks. Sweep
# any strays so every launch starts from a clean slate.
foreach ($n in @("llama-server", "llama-tts")) {
    Get-Process -Name $n -ErrorAction SilentlyContinue | ForEach-Object {
        Write-Host "[ports] stray $($_.ProcessName) (pid $($_.Id)) -> stopping" -ForegroundColor DarkGray
        try { Stop-Process -Id $_.Id -Force -ErrorAction Stop } catch {}
    }
}
Start-Sleep -Milliseconds 400

# --- bootstrap backend venv ---------------------------------------------------
if (-not (Test-Path $venvPy)) {
    Write-Host "[setup] creating venv + installing foundation deps..." -ForegroundColor Cyan
    python -m venv .venv
    & $venvPy -m pip install --upgrade pip
    & $venvPy -m pip install -r backend\requirements.txt
    if (-not $isStubMode) {
        Write-AcceleratorInstallHint $selectedProfile
    }
}

# --- bootstrap frontend deps --------------------------------------------------
if (-not (Test-Path (Join-Path $root "frontend\node_modules"))) {
    Write-Host "[setup] installing frontend deps..." -ForegroundColor Cyan
    Push-Location frontend; npm install; Pop-Location
}

if ($Prod -and (Test-DistStale)) {
    Write-Host "[build] frontend/dist is missing or stale -> npm run build" -ForegroundColor Cyan
    Push-Location frontend
    npm run build
    Pop-Location
}

Write-Host "[run] backend  -> http://${BindHost}:$Port"       -ForegroundColor Green
if ($Prod) {
    Write-Host "[run] frontend -> http://localhost:$Port (served by FastAPI)" -ForegroundColor Green
    Write-Host "[run] one server runs in THIS window; press Ctrl+C to stop.`n" -ForegroundColor Yellow
} else {
    Write-Host "[run] frontend -> http://localhost:$FrontendPort" -ForegroundColor Green
    Write-Host "[run] both run in THIS window; press Ctrl+C to stop.`n" -ForegroundColor Yellow
}

# Backend shares this console (one window). No --reload -> a single PID to manage.
$backend = Start-Process -FilePath $venvPy `
    -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "$BindHost", "--port", "$Port") `
    -WorkingDirectory (Join-Path $root "backend") `
    -NoNewWindow -PassThru

try {
    if ($Prod) {
        $healthUrl = "http://127.0.0.1:$Port/api/health"
        if (Wait-Health $healthUrl) {
            Start-Process "http://localhost:$Port"
        } else {
            Write-Host "[warn] backend did not answer $healthUrl before timeout" -ForegroundColor Yellow
        }
        Wait-Process -Id $backend.Id
    } else {
        # Open the UI once the servers have had a moment to come up.
        Start-Job -ScriptBlock {
            param($url)
            Start-Sleep -Seconds 6
            Start-Process $url
        } -ArgumentList "http://localhost:$FrontendPort" | Out-Null

        Push-Location frontend
        npm run dev          # foreground; blocks until Ctrl+C
    }
} finally {
    if (-not $Prod) { Pop-Location }
    if ($backend -and -not $backend.HasExited) {
        Write-Host "`n[stop] shutting down backend (pid $($backend.Id))..." -ForegroundColor DarkGray
        taskkill /PID $backend.Id /T /F 2>$null | Out-Null
    }
    Stop-Port $Port
    Get-Job | Remove-Job -Force -ErrorAction SilentlyContinue
}
