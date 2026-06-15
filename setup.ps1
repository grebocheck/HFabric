<#
  HFabric automated setup script

    .\setup.ps1              # Auto setup (hardware probe → recommended profile)
    .\setup.ps1 -Stub        # STUB mode only (no GPU/ML stack)
    .\setup.ps1 -Real        # Force accelerator profile when available
    .\setup.ps1 -DownloadAll # Accelerator profile + starter models

  This script:
  1. Checks prerequisites (Python 3.12+, Node.js 18+)
  2. Creates Python venv + installs pip dependencies
  3. Installs npm dependencies
  4. Auto-selects CPU/CUDA/ROCm profile and installs matching packages
  5. Optionally downloads the profile starter model set
#>
param(
    [switch]$Stub,                  # STUB mode only
    [switch]$Real,                  # REAL mode + accelerator stack
    [switch]$DownloadAll,           # REAL mode + accelerator stack + starter models
    [switch]$SkipPrerequiteCheck,   # Skip Python/Node.js/NVIDIA checks
    [switch]$Force                  # Force reinstall even if venv exists
)

$ErrorActionPreference = "Stop"
# setup.ps1 lives at the repo root, so $PSScriptRoot *is* the root. (Do NOT take
# its parent — that would create the venv/deps one level above the project.)
$root = $PSScriptRoot
Set-Location $root

$venvPath = ".venv"
$venvPy = Join-Path $venvPath "Scripts\python.exe"
$venvPip = Join-Path $venvPath "Scripts\pip.exe"

Write-Host "`n╔══════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║       HFabric Automated Setup                              ║" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════════════════════════════╝`n" -ForegroundColor Cyan

# --- Helper functions ---------------------------------------------------------

function Test-Command {
    param([string]$cmd)
    try {
        $null = & $cmd --version 2>&1
        return $true
    } catch {
        return $false
    }
}

function Write-Section {
    param([string]$title)
    Write-Host "`n► $title" -ForegroundColor Green -BackgroundColor DarkGray
}

function Write-Success {
    param([string]$msg)
    Write-Host "  ✓ $msg" -ForegroundColor Green
}

function Write-Warning-Text {
    param([string]$msg)
    Write-Host "  ⚠ $msg" -ForegroundColor Yellow
}

function Write-Error-Text {
    param([string]$msg)
    Write-Host "  ✗ $msg" -ForegroundColor Red
}

function Assert-LastExit {
    # pip/npm are native exes: a non-zero exit does NOT throw in PowerShell, so a
    # failed install would otherwise be silently swallowed by "| Out-Null".
    param([string]$what)
    if ($LASTEXITCODE -ne 0) {
        Write-Error-Text "$what failed (exit $LASTEXITCODE). Re-run without '| Out-Null' suppression to see the error, or check your network / Python version."
        exit 1
    }
}

function Resolve-InstallProfile {
    param([string]$Prefer = "")
    $args = @("scripts\install_profiles.py")
    if (-not [string]::IsNullOrWhiteSpace($Prefer)) {
        $args += @("--prefer", $Prefer)
    }
    $json = & python @args 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Error-Text "hardware profile resolution failed"
        Write-Host $json -ForegroundColor Red
        exit 1
    }
    return (($json -join "`n") | ConvertFrom-Json)
}

# --- Check prerequisites ------------------------------------------------------

if (-not $SkipPrerequiteCheck) {
    Write-Section "Checking prerequisites"
    
    # Python 3.12+
    if (-not (Test-Command "python")) {
        Write-Error-Text "Python not found or not in PATH"
        Write-Host "`n  → Install Python 3.12+: https://www.python.org/downloads/" -ForegroundColor Cyan
        Write-Host "  → Make sure 'Add Python to PATH' is checked during install`n" -ForegroundColor Cyan
        exit 1
    }
    $pyVersion = & python --version 2>&1
    Write-Success "Python found: $pyVersion"
    
    # Node.js 18+
    if (-not (Test-Command "node")) {
        Write-Error-Text "Node.js not found or not in PATH"
        Write-Host "`n  → Install Node.js 18+: https://nodejs.org/" -ForegroundColor Cyan
        Write-Host "  → Make sure 'Add to PATH' is checked during install`n" -ForegroundColor Cyan
        exit 1
    }
    $nodeVersion = & node --version 2>&1
    Write-Success "Node.js found: $nodeVersion"
    
    # Optional NVIDIA summary. Final install decision is made by
    # scripts/install_profiles.py, which also handles AMD/CPU-safe profiles.
    if (-not $Stub -and (Test-Command "nvidia-smi")) {
        $gpuInfo = & nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>&1 | Select-Object -First 1
        Write-Success "NVIDIA GPU found: $gpuInfo"
    }
}

# --- Determine install profile ------------------------------------------------

Write-Section "Hardware profile"

$profile = $null
$mode = "auto"
if ($Stub) {
    $profile = Resolve-InstallProfile -Prefer "cpu-safe"
    $mode = "stub"
} else {
    $profile = Resolve-InstallProfile
    if ($DownloadAll) { $mode = "download-all" }
    elseif ($Real) { $mode = "real" }
}

$profileId = [string]$profile.selected_profile
$isAccelerated = $profileId -ne "cpu-safe"
if (-not $isAccelerated) {
    $Stub = $true
    $Real = $false
} else {
    $Stub = $false
    $Real = $true
}
if ($DownloadAll -and -not $isAccelerated) {
    Write-Warning-Text "DownloadAll requested, but no supported accelerator profile was found; setup will stay CPU-safe."
    $DownloadAll = $false
}

Write-Host "  Selected profile: " -NoNewline -ForegroundColor White
if ($isAccelerated) {
    Write-Host "$profileId ($($profile.hardware_tier))" -ForegroundColor Green
} else {
    Write-Host "$profileId" -ForegroundColor Yellow
}
Write-Host "  $($profile.reason)" -ForegroundColor DarkGray
foreach ($warning in @($profile.warnings)) {
    Write-Warning-Text $warning
}
if ($profile.primary_gpu) {
    Write-Host "  GPU: $($profile.primary_gpu.vendor) $($profile.primary_gpu.name) ($($profile.primary_gpu.vram_mb) MB VRAM)" -ForegroundColor DarkGray
}

# --- Create/update venv -------------------------------------------------------

Write-Section "Python virtual environment"

if ((Test-Path $venvPath) -and -not $Force) {
    Write-Success "venv already exists at $venvPath"
} else {
    if (Test-Path $venvPath) {
        Write-Warning-Text "Removing existing venv (Force flag used)"
        Remove-Item -Recurse -Force $venvPath
    }
    Write-Host "  Creating venv..." -ForegroundColor Cyan
    & python -m venv $venvPath
    Assert-LastExit "venv creation"
    Write-Success "venv created"
}

if (-not (Test-Path $venvPy)) {
    Write-Error-Text "venv python not found at $venvPy — venv creation may have failed."
    exit 1
}

Write-Host "  Upgrading pip..." -ForegroundColor Cyan
& $venvPy -m pip install --upgrade pip 2>&1 | Out-Null
Assert-LastExit "pip upgrade"
Write-Success "pip upgraded"

# --- Install foundation deps --------------------------------------------------

Write-Section "Installing foundation dependencies"
Write-Host "  Installing from backend/requirements.txt..." -ForegroundColor Cyan
& $venvPip install -r backend\requirements.txt 2>&1 | Out-Null
Assert-LastExit "foundation dependency install"
Write-Success "Foundation packages installed (FastAPI, SQLAlchemy, Pydantic, etc.)"

# --- Install GPU deps if needed -----------------------------------------------

if ($Real) {
    Write-Section "Installing accelerated ML stack"

    $torchPackages = @($profile.install.torch.packages)
    $torchIndex = [string]$profile.install.torch.index_url
    Write-Host "  Installing PyTorch for $profileId..." -ForegroundColor Cyan
    if ([string]::IsNullOrWhiteSpace($torchIndex)) {
        Write-Host "  Index: default PyPI" -ForegroundColor DarkGray
        & $venvPip install @torchPackages 2>&1 | Out-Null
    } else {
        Write-Host "  Index: $torchIndex" -ForegroundColor DarkGray
        & $venvPip install @torchPackages --index-url $torchIndex 2>&1 | Out-Null
    }
    Assert-LastExit "PyTorch install"
    Write-Success "PyTorch installed"

    Write-Host "  Verifying PyTorch profile..." -ForegroundColor Cyan
    $verify = [string]$profile.install.verify
    $torchCheck = & $venvPy -c $verify 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Warning-Text "PyTorch verification failed for $profileId"
        Write-Host "    $torchCheck" -ForegroundColor Yellow
    } else {
        Write-Host "    $torchCheck" -ForegroundColor DarkGray
        Write-Success "PyTorch verified"
    }

    foreach ($req in @($profile.install.requirements)) {
        Write-Host "  Installing backend requirements from $req..." -ForegroundColor Cyan
        & $venvPip install -r $req 2>&1 | Out-Null
        Assert-LastExit "backend requirement install ($req)"
    }
    Write-Success "Accelerated backend packages installed"
    
    # Optional: Nunchaku for FLUX (CUDA-only for now).
    $installNunchaku = $false
    $canInstallNunchaku = @($profile.optional_features) -contains "nunchaku_cuda"
    if ($canInstallNunchaku) {
        if ($DownloadAll) {
            $installNunchaku = $true
        } else {
            Write-Host ""
            $nChoice = Read-Host "Install Nunchaku acceleration for FLUX? (y/n, default: n)"
            if ($nChoice -eq "y") { $installNunchaku = $true }
        }
    }

    if ($installNunchaku) {
        Write-Host "`n  Installing Nunchaku (FLUX acceleration)..." -ForegroundColor Cyan
        Write-Host "  (Matching cu12.8+torch2.11+cp312 wheel, ~300 MB)" -ForegroundColor DarkGray
        $nunchakuUrl = "https://github.com/nunchaku-ai/nunchaku/releases/download/v1.3.0dev20260213/nunchaku-1.3.0.dev20260213+cu12.8torch2.11-cp312-cp312-win_amd64.whl"
        & $venvPip install $nunchakuUrl 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Warning-Text "Nunchaku wheel install failed; continuing without FLUX acceleration."
        } else {
            Write-Success "Nunchaku installed"
        }
    }
}

# --- Install llama.cpp runtime ------------------------------------------------

if ($Real) {
    Write-Section "Installing llama.cpp runtime"
    Write-Host "  Downloading the matching prebuilt build (LLM/RAG/TTS)..." -ForegroundColor Cyan
    & $venvPy "scripts\fetch_llama.py"
    if ($LASTEXITCODE -ne 0) {
        Write-Warning-Text "llama.cpp auto-install failed; you can install it later from Settings -> LLM runtime."
    }
}

# --- Install frontend deps ----------------------------------------------------

Write-Section "Installing frontend dependencies"
if ((Test-Path "frontend\node_modules") -and -not $Force) {
    Write-Success "node_modules already exists"
} else {
    Write-Host "  Running npm install..." -ForegroundColor Cyan
    Push-Location frontend
    & npm install 2>&1 | Out-Null
    $npmExit = $LASTEXITCODE
    Pop-Location
    if ($npmExit -ne 0) {
        Write-Error-Text "npm install failed (exit $npmExit). Check that Node.js 18+ is installed and on PATH."
        exit 1
    }
    Write-Success "Frontend packages installed (React, Tailwind, Vite, etc.)"
}

# --- Download models (optional) -----------------------------------------------

if ($DownloadAll) {
    Write-Section "Downloading profile starter models"

    Write-Host "`n  This downloads the starter model set recommended for $profileId." -ForegroundColor Yellow
    Write-Host "  Installing huggingface-hub if not already present..." -ForegroundColor Cyan
    & $venvPip install huggingface-hub 2>&1 | Out-Null
    Write-Success "huggingface-hub installed"

    & $venvPy "scripts\fetch_models.py" --profile $profileId
    if ($LASTEXITCODE -ne 0) {
        Write-Warning-Text "Some starter model downloads failed; the app will still run, and you can re-run .\setup.ps1 -DownloadAll."
    } else {
        Write-Success "Profile starter models downloaded"
    }
}

# --- Final summary and next steps ---------------------------------------------

Write-Section "Setup complete!"

Write-Host "`n  Mode: " -NoNewline -ForegroundColor White
if ($Stub) {
    Write-Host "STUB (foundation only)" -ForegroundColor Yellow
} else {
    Write-Host "ACCELERATED ($profileId)" -ForegroundColor Green
}
Write-Host "  Install profile: $profileId / tier: $($profile.hardware_tier)" -ForegroundColor DarkGray

Write-Host "`n  Next step: start the app`n" -ForegroundColor White

if ($Stub) {
    Write-Host "    run.bat stub" -ForegroundColor Cyan
    Write-Host "      or" -ForegroundColor DarkGray
    Write-Host "    .\scripts\run.ps1 -Stub" -ForegroundColor Cyan
} else {
    Write-Host "    run.bat" -ForegroundColor Cyan
    Write-Host "      or" -ForegroundColor DarkGray
    Write-Host "    .\scripts\run.ps1" -ForegroundColor Cyan
}

Write-Host "`n  This will start:" -ForegroundColor White
Write-Host "    - Backend at http://localhost:8260" -ForegroundColor DarkGray
Write-Host "    - Frontend at http://localhost:5173" -ForegroundColor DarkGray

if ($Real -and -not $DownloadAll) {
    Write-Host "`n  ⓘ GPU mode requires models in models/" -ForegroundColor Yellow
    Write-Host "    Download them manually or re-run: .\setup.ps1 -DownloadAll" -ForegroundColor Yellow
}

Write-Host "`n" -ForegroundColor White
