<#
  HFabric automated setup script

    .\setup.ps1              # Guided setup (STUB → REAL → models)
    .\setup.ps1 -Stub        # STUB mode only (no GPU/ML stack)
    .\setup.ps1 -Real        # REAL mode: GPU stack + optional models
    .\setup.ps1 -DownloadAll # REAL mode: GPU stack + ALL curated models

  This script:
  1. Checks prerequisites (Python 3.12+, Node.js 18+, NVIDIA drivers if needed)
  2. Creates Python venv + installs pip dependencies
  3. Installs npm dependencies
  4. Optionally installs GPU stack (torch + requirements-gpu.txt)
  5. Optionally downloads model files (FLUX, SDXL, LLMs)
#>
param(
    [switch]$Stub,                  # STUB mode only
    [switch]$Real,                  # REAL mode + GPU stack
    [switch]$DownloadAll,           # REAL mode + GPU stack + all models
    [switch]$SkipPrerequiteCheck,   # Skip Python/Node.js/NVIDIA checks
    [switch]$Force                  # Force reinstall even if venv exists
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
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
    
    # NVIDIA GPU for REAL mode
    if (-not $Stub -and -not (Test-Command "nvidia-smi")) {
        Write-Warning-Text "NVIDIA drivers not found (nvidia-smi not in PATH)"
        Write-Host "`n  → For REAL mode, install NVIDIA GPU drivers: https://www.nvidia.com/Download/driverDetails.aspx" -ForegroundColor Yellow
        Write-Host "  → Or use STUB mode (no GPU required) with -Stub flag`n" -ForegroundColor Yellow
        $choice = Read-Host "Continue with STUB mode? (y/n)"
        if ($choice -ne "y") { exit 1 }
        $Stub = $true
    }
    elseif (-not $Stub -and (Test-Command "nvidia-smi")) {
        $gpuInfo = & nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>&1 | Select-Object -First 1
        Write-Success "NVIDIA GPU found: $gpuInfo"
    }
}

# --- Determine mode -----------------------------------------------------------

$mode = "guided"
if ($Stub) { $mode = "stub" }
elseif ($Real) { $mode = "real" }
elseif ($DownloadAll) { $mode = "download-all" }

if ($mode -eq "guided") {
    Write-Section "Setup mode selection"
    Write-Host "`n  1) STUB mode (no GPU, test foundation)  ← FASTEST, recommended first"
    Write-Host "  2) REAL mode (GPU stack only)"
    Write-Host "  3) REAL + Models (GPU + download models)"
    Write-Host ""
    $modeChoice = Read-Host "Select mode (1-3, default: 1)"
    switch ($modeChoice) {
        "2" { $mode = "real"; $Real = $true }
        "3" { $mode = "download-all"; $DownloadAll = $true }
        default { $mode = "stub"; $Stub = $true }
    }
}

if ($DownloadAll) { $Real = $true }

Write-Host "`n  Mode: " -NoNewline -ForegroundColor White
if ($Stub) {
    Write-Host "STUB (no GPU/ML)" -ForegroundColor Yellow
} else {
    Write-Host "REAL (GPU)" -ForegroundColor Green
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
    Write-Success "venv created"
}

Write-Host "  Upgrading pip..." -ForegroundColor Cyan
& $venvPy -m pip install --upgrade pip 2>&1 | Out-Null
Write-Success "pip upgraded"

# --- Install foundation deps --------------------------------------------------

Write-Section "Installing foundation dependencies"
Write-Host "  Installing from backend/requirements.txt..." -ForegroundColor Cyan
& $venvPip install -r backend\requirements.txt 2>&1 | Out-Null
Write-Success "Foundation packages installed (FastAPI, SQLAlchemy, Pydantic, etc.)"

# --- Install GPU deps if needed -----------------------------------------------

if ($Real) {
    Write-Section "Installing GPU/ML stack"
    
    Write-Host "  Installing PyTorch 2.11 + CUDA 12.8..." -ForegroundColor Cyan
    Write-Host "  (this takes 2–5 min, ~2 GB download)" -ForegroundColor DarkGray
    & $venvPip install torch torchvision --index-url https://download.pytorch.org/whl/cu128 2>&1 | Out-Null
    Write-Success "PyTorch + CUDA installed"
    
    Write-Host "  Verifying PyTorch installation..." -ForegroundColor Cyan
    $torchCheck = & $venvPy -c "import torch; print(f'torch={torch.__version__}'); cap = torch.cuda.get_device_capability(); print(f'GPU capability={cap}')" 2>&1
    Write-Host "    $torchCheck" -ForegroundColor DarkGray
    Write-Success "PyTorch verified"
    
    Write-Host "  Installing GPU backends (diffusers, transformers, accelerate, bitsandbytes)..." -ForegroundColor Cyan
    Write-Host "  (this takes 3–5 min, ~1 GB download)" -ForegroundColor DarkGray
    & $venvPip install -r backend\requirements-gpu.txt 2>&1 | Out-Null
    Write-Success "GPU backends installed"
    
    # Optional: Nunchaku for FLUX
    $installNunchaku = $false
    if ($DownloadAll) {
        $installNunchaku = $true
    } else {
        Write-Host ""
        $nChoice = Read-Host "Install Nunchaku acceleration for FLUX? (y/n, default: n)"
        if ($nChoice -eq "y") { $installNunchaku = $true }
    }
    
    if ($installNunchaku) {
        Write-Host "`n  Installing Nunchaku (FLUX acceleration)..." -ForegroundColor Cyan
        Write-Host "  (Matching cu12.8+torch2.11+cp312 wheel, ~300 MB)" -ForegroundColor DarkGray
        $nunchakuUrl = "https://github.com/nunchaku-ai/nunchaku/releases/download/v1.3.0dev20260213/nunchaku-1.3.0.dev20260213+cu12.8torch2.11-cp312-cp312-win_amd64.whl"
        & $venvPip install $nunchakuUrl 2>&1 | Out-Null
        Write-Success "Nunchaku installed"
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
    Pop-Location
    Write-Success "Frontend packages installed (React, Tailwind, Vite, etc.)"
}

# --- Download models (optional) -----------------------------------------------

if ($DownloadAll) {
    Write-Section "Downloading curated models"
    
    Write-Host "`n  This will download ~80 GB of model files." -ForegroundColor Yellow
    Write-Host "  Install huggingface-cli if not already present..." -ForegroundColor Cyan
    & $venvPip install huggingface-hub 2>&1 | Out-Null
    Write-Success "huggingface-hub installed"
    
    $dlChoice = Read-Host "`nStart model downloads? (y/n)"
    if ($dlChoice -eq "y") {
        $hfCli = Join-Path $venvPath "Scripts\huggingface-cli.exe"
        
        # Ensure models directories exist
        @("models\image", "models\llm", "models\lora", "models\embed", "models\vision") |
            ForEach-Object { if (-not (Test-Path $_)) { mkdir $_ | Out-Null } }
        
        Write-Host "`n  Downloading image models (FLUX, SDXL)..." -ForegroundColor Cyan
        & $hfCli download black-forest-labs/FLUX.1-dev flux_dev.safetensors --local-dir models\image 2>&1 | Out-Null
        Write-Success "flux_dev.safetensors downloaded"
        
        & $hfCli download ByteDance/SDXL-Lightning sdxl_lightning_4step_lora.safetensors --local-dir models\lora 2>&1 | Out-Null
        Write-Success "SDXL Lightning LoRA downloaded"
        
        Write-Host "`n  Downloading LLM models (Gemma, GPT-OSS)..." -ForegroundColor Cyan
        & $hfCli download Gron1-ai/Gemma-3-12B-it-Heretic-v2-GGUF gemma-3-12b-it-heretic-v2-Q4_K_M.gguf --local-dir models\llm 2>&1 | Out-Null
        Write-Success "Gemma 3 12B downloaded"
        
        Write-Host "`n  Downloading embedding models (Nomic, for RAG)..." -ForegroundColor Cyan
        & $hfCli download nomic-ai/nomic-embed-text-v1.5 nomic-embed-text-v1.5.f16.gguf --local-dir models\embed 2>&1 | Out-Null
        Write-Success "Nomic embed downloaded"
        
        Write-Host "`n  Downloading vision models (Qwen VL)..." -ForegroundColor Cyan
        & $hfCli download Qwen/Qwen2.5-VL-3B-Instruct Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf --local-dir models\vision 2>&1 | Out-Null
        Write-Success "Qwen VL downloaded"
        
        Write-Success "All models downloaded to models/"
    } else {
        Write-Warning-Text "Model downloads skipped"
        Write-Host "  You can manually download models later using huggingface-cli" -ForegroundColor Yellow
        Write-Host "  Or re-run setup with -DownloadAll flag" -ForegroundColor Yellow
    }
}

# --- Final summary and next steps ---------------------------------------------

Write-Section "Setup complete!"

Write-Host "`n  Mode: " -NoNewline -ForegroundColor White
if ($Stub) {
    Write-Host "STUB (foundation only)" -ForegroundColor Yellow
} else {
    Write-Host "REAL (GPU + ML stack)" -ForegroundColor Green
}

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
