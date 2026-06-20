# Shared Windows setup helpers for setup.ps1, scripts/run.ps1, and update.ps1:
# managed local Python / Node provisioning plus a robust frontend `npm install`.
#
# Dot-source this file so the functions land in the caller's scope:
#     . "$PSScriptRoot\_windows_prereqs.ps1"
#
# Why this exists: a bare `npm install` / `python -m venv` throws an opaque
# "CommandNotFoundException" when the toolchain isn't on PATH. These helpers
# create project-local tools under .tools (no system PATH writes) instead of
# sending the user to hunt for installers.

function Test-ToolOnPath {
    param([string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Get-RepoRoot {
    return (Split-Path -Parent $PSScriptRoot)
}

function Get-ToolsRoot {
    return (Join-Path (Get-RepoRoot) ".tools")
}

function Get-ManagedPythonVersion {
    if ([string]::IsNullOrWhiteSpace($env:HFAB_MANAGED_PYTHON_VERSION)) { return "3.12.10" }
    return $env:HFAB_MANAGED_PYTHON_VERSION.Trim()
}

function Get-ManagedNodeVersion {
    if ([string]::IsNullOrWhiteSpace($env:HFAB_MANAGED_NODE_VERSION)) { return "24.17.0" }
    return $env:HFAB_MANAGED_NODE_VERSION.Trim().TrimStart("v")
}

function Get-ManagedPythonDir {
    return (Join-Path (Get-ToolsRoot) ("python-" + (Get-ManagedPythonVersion)))
}

function Get-ManagedPythonExe {
    return (Join-Path (Get-ManagedPythonDir) "python.exe")
}

function Get-ManagedNodeDir {
    $version = Get-ManagedNodeVersion
    return (Join-Path (Get-ToolsRoot) "node-v$version-win-x64")
}

function Get-ManagedNodeExe {
    return (Join-Path (Get-ManagedNodeDir) "node.exe")
}

function Get-ManagedNpmCmd {
    return (Join-Path (Get-ManagedNodeDir) "npm.cmd")
}

function Add-ToolDirToPath {
    param([string]$Dir)
    if (-not (Test-Path $Dir)) { return }
    $parts = @($env:Path -split ";" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    $resolved = (Resolve-Path -LiteralPath $Dir).Path
    $kept = @()
    foreach ($part in $parts) {
        try {
            if ((Resolve-Path -LiteralPath $part -ErrorAction Stop).Path -ieq $resolved) {
                continue
            }
        } catch {}
        $kept += $part
    }
    $env:Path = (@($resolved) + $kept) -join ";"
}

function Enable-ManagedPython {
    $exe = Get-ManagedPythonExe
    if (Test-Path $exe) {
        Add-ToolDirToPath (Get-ManagedPythonDir)
    }
}

function Enable-ManagedNode {
    $exe = Get-ManagedNodeExe
    if (Test-Path $exe) {
        Add-ToolDirToPath (Get-ManagedNodeDir)
    }
}

function Invoke-HFabricDownload {
    param(
        [string]$Url,
        [string]$OutFile
    )
    $parent = Split-Path -Parent $OutFile
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    if (Test-Path $OutFile) { return }
    Write-Host "[prereq] downloading $Url" -ForegroundColor Cyan
    Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $OutFile
}

function Assert-UnderToolsRoot {
    param([string]$Path)
    $tools = (Resolve-Path -LiteralPath (Get-ToolsRoot) -ErrorAction SilentlyContinue)
    if (-not $tools) {
        New-Item -ItemType Directory -Force -Path (Get-ToolsRoot) | Out-Null
        $tools = Resolve-Path -LiteralPath (Get-ToolsRoot)
    }
    $full = [System.IO.Path]::GetFullPath($Path)
    $root = [System.IO.Path]::GetFullPath($tools.Path)
    if (-not $full.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "refusing to modify a path outside .tools: $full"
    }
}

function Install-ManagedPython {
    param([switch]$Force)
    $version = Get-ManagedPythonVersion
    $dir = Get-ManagedPythonDir
    $exe = Get-ManagedPythonExe
    if ((Test-Path $exe) -and -not $Force) {
        Enable-ManagedPython
        return
    }

    Assert-UnderToolsRoot $dir
    New-Item -ItemType Directory -Force -Path (Get-ToolsRoot) | Out-Null
    if (Test-Path $dir) {
        Remove-Item -LiteralPath $dir -Recurse -Force
    }

    # Use the official CPython NuGet package rather than the Windows installer:
    # the MSI installer modifies an existing per-user Python of the same version
    # instead of creating a true side-by-side project-local copy.
    $cache = Join-Path (Get-ToolsRoot) "cache"
    $package = Join-Path $cache "python.$version.nupkg"
    $zip = Join-Path $cache "python.$version.zip"
    $extract = Join-Path $cache "python-$version-extract"
    $url = "https://api.nuget.org/v3-flatcontainer/python/$version/python.$version.nupkg"
    Invoke-HFabricDownload $url $package

    Write-Host "[prereq] unpacking local Python $version into $dir" -ForegroundColor Cyan
    Remove-Item -LiteralPath $extract -Recurse -Force -ErrorAction SilentlyContinue
    Copy-Item -LiteralPath $package -Destination $zip -Force
    Expand-Archive -LiteralPath $zip -DestinationPath $extract -Force
    $tools = Join-Path $extract "tools"
    if (-not (Test-Path (Join-Path $tools "python.exe"))) {
        Write-Host "[prereq] Python package unpacked, but tools\python.exe was not found." -ForegroundColor Red
        exit 1
    }
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    Get-ChildItem -LiteralPath $tools -Force | Copy-Item -Destination $dir -Recurse -Force
    Remove-Item -LiteralPath $extract -Recurse -Force -ErrorAction SilentlyContinue

    if (-not (Test-Path $exe)) {
        Write-Host "[prereq] local Python unpack finished, but python.exe was not found at $exe." -ForegroundColor Red
        exit 1
    }
    Enable-ManagedPython
    & $exe -m ensurepip --upgrade 2>$null | Out-Null
}

function Install-ManagedNode {
    param([switch]$Force)
    $version = Get-ManagedNodeVersion
    $dir = Get-ManagedNodeDir
    $exe = Get-ManagedNodeExe
    if ((Test-Path $exe) -and (Test-Path (Get-ManagedNpmCmd)) -and -not $Force) {
        Enable-ManagedNode
        return
    }

    Assert-UnderToolsRoot $dir
    New-Item -ItemType Directory -Force -Path (Get-ToolsRoot) | Out-Null
    if (Test-Path $dir) {
        Remove-Item -LiteralPath $dir -Recurse -Force
    }

    $zip = Join-Path (Get-ToolsRoot) "cache\node-v$version-win-x64.zip"
    $url = "https://nodejs.org/dist/v$version/node-v$version-win-x64.zip"
    Invoke-HFabricDownload $url $zip

    Write-Host "[prereq] unpacking local Node.js $version into .tools" -ForegroundColor Cyan
    Expand-Archive -LiteralPath $zip -DestinationPath (Get-ToolsRoot) -Force
    if (-not (Test-Path $exe)) {
        Write-Host "[prereq] local Node.js archive unpacked, but node.exe was not found at $exe." -ForegroundColor Red
        exit 1
    }
    Enable-ManagedNode
}

function Get-PythonVersion {
    Enable-ManagedPython
    if (-not (Test-ToolOnPath "python")) { return $null }
    $raw = & python -c "import sys; print('%d.%d.%d' % sys.version_info[:3])" 2>$null
    if ($LASTEXITCODE -ne 0) { return $null }
    try { return [version]$raw.Trim() } catch { return $null }
}

function Get-NodeVersion {
    Enable-ManagedNode
    if (-not ((Test-ToolOnPath "node") -and (Test-Path (Get-NpmCommand)))) { return $null }
    $raw = & node -p "process.versions.node" 2>$null
    if ($LASTEXITCODE -ne 0) { return $null }
    try { return [version]$raw.Trim() } catch { return $null }
}

function Get-NpmCommand {
    $managed = Get-ManagedNpmCmd
    if (Test-Path $managed) { return $managed }
    $cmd = Get-Command "npm.cmd" -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $cmd = Get-Command "npm" -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return "npm"
}

function Test-MinVersion {
    param(
        [version]$Version,
        [int]$Major,
        [int]$Minor
    )
    if ($null -eq $Version) { return $false }
    return ($Version.Major -gt $Major) -or (($Version.Major -eq $Major) -and ($Version.Minor -ge $Minor))
}

function Assert-Python {
    # Needed to create the backend venv. Windows is intentionally project-managed:
    # even if system Python exists, create/use the local .tools runtime first.
    if (-not (Test-Path (Get-ManagedPythonExe))) {
        Install-ManagedPython
    } else {
        Enable-ManagedPython
    }
    $version = Get-PythonVersion
    if (Test-MinVersion $version 3 12) {
        if ($version.Major -eq 3 -and $version.Minor -gt 12) {
            Write-Host "[prereq] Python $version detected; 3.12 is the validated runtime for optional native wheels." -ForegroundColor Yellow
        }
        return
    }
    Write-Host "[prereq] local Python runtime is missing or invalid; reinstalling it." -ForegroundColor Yellow
    Install-ManagedPython -Force
    $version = Get-PythonVersion
    if (Test-MinVersion $version 3 12) { return }

    Write-Host ""
    if ($version) {
        Write-Host "[prereq] Python $version is too old." -ForegroundColor Red
    } else {
        Write-Host "[prereq] local Python could not be started." -ForegroundColor Red
    }
    Write-Host "[prereq] local Python install did not produce Python 3.12+." -ForegroundColor Red
    exit 1
}

function Assert-NodeToolchain {
    # Needed for the frontend (npm install / dev / build). Windows is intentionally
    # project-managed: even if system Node exists, create/use local .tools first.
    if (-not ((Test-Path (Get-ManagedNodeExe)) -and (Test-Path (Get-ManagedNpmCmd)))) {
        Install-ManagedNode
    } else {
        Enable-ManagedNode
    }
    $version = Get-NodeVersion
    if (Test-MinVersion $version 18 0) { return }

    Write-Host "[prereq] local Node.js runtime is missing or invalid; reinstalling it." -ForegroundColor Yellow
    Install-ManagedNode -Force
    $version = Get-NodeVersion
    if (Test-MinVersion $version 18 0) { return }

    Write-Host ""
    if ($version) {
        Write-Host "[prereq] Node.js $version is too old." -ForegroundColor Red
    } else {
        Write-Host "[prereq] local Node.js / npm could not be started." -ForegroundColor Red
    }
    Write-Host "[prereq] local Node.js install did not produce Node.js 18+." -ForegroundColor Red
    exit 1
}

function Test-FrontendReady {
    # A *complete* install leaves the vite launcher. A half-removed node_modules
    # (e.g. an EPERM cleanup after a failed download) leaves the folder but not
    # vite — so checking the folder alone would wrongly skip a needed reinstall
    # and later blow up with "'vite' is not recognized".
    param([string]$FrontendDir)
    $nm = Join-Path $FrontendDir "node_modules"
    if (-not (Test-Path $nm)) { return $false }
    return (Test-Path (Join-Path $nm ".bin\vite.cmd")) -or
           (Test-Path (Join-Path $nm ".bin\vite.ps1")) -or
           (Test-Path (Join-Path $nm "vite\package.json"))
}

function Show-NpmFailureHelp {
    param([int]$ExitCode)
    Write-Host ""
    Write-Host "[setup] npm install did not finish (exit $ExitCode); the frontend is not ready." -ForegroundColor Red
    Write-Host "        Common Windows causes and fixes:" -ForegroundColor Yellow
    Write-Host "          - TLS errors (ERR_SSL_CIPHER_OPERATION_FAILED): a VPN, corporate proxy," -ForegroundColor Cyan
    Write-Host "            or antivirus is intercepting HTTPS. Pause it (or configure npm proxy)," -ForegroundColor Cyan
    Write-Host "            then re-run update.bat --force or setup.bat." -ForegroundColor Cyan
    Write-Host "          - EPERM removing node_modules: the folder is locked. Move the project OUT" -ForegroundColor Cyan
    Write-Host "            of a OneDrive-synced folder (Desktop/Documents) to a short local path" -ForegroundColor Cyan
    Write-Host "            like C:\HFabric, close editors/Explorer on it, and exclude it from AV." -ForegroundColor Cyan
    Write-Host "          - Then re-run update.bat --force or setup.bat." -ForegroundColor Cyan
}

function Test-FoundationDepsReady {
    # Foundation mode still needs the in-app model downloader, diagnostics, DB,
    # and basic image/audio helpers. Keep this as a find_spec check so launch
    # stays cheap and does not import FastAPI/torch.
    param([string]$VenvPy)
    if (-not (Test-Path $VenvPy)) { return $false }
    $code = @"
import importlib.util, sys
mods = ['fastapi', 'pydantic_settings', 'sqlalchemy', 'PIL', 'psutil', 'huggingface_hub']
missing = [m for m in mods if importlib.util.find_spec(m) is None]
sys.exit(1 if missing else 0)
"@
    & $VenvPy -c $code 2>$null
    return ($LASTEXITCODE -eq 0)
}

function Install-FoundationDeps {
    param([string]$VenvPy)
    Write-Host "[setup] installing foundation backend packages..." -ForegroundColor Cyan
    & $VenvPy -m pip install -r backend\requirements.txt
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[setup] foundation dependency install failed (exit $LASTEXITCODE)." -ForegroundColor Red
        exit 1
    }
}

function Test-AcceleratorStackReady {
    # REAL mode needs the heavy stack. Use find_spec (no actual import) so this
    # stays a fast per-launch check, not a multi-second torch import. Torch alone
    # is not enough: voice/audio previously failed when sounddevice/onnxruntime
    # were absent in a half-upgraded venv.
    param([string]$VenvPy)
    if (-not (Test-Path $VenvPy)) { return $false }
    $code = @"
import importlib.util, sys
mods = ['torch', 'diffusers', 'transformers', 'accelerate', 'peft', 'sounddevice', 'soundfile', 'onnxruntime', 'torchfcpe', 'torchcrepe', 'faiss']
missing = [m for m in mods if importlib.util.find_spec(m) is None]
sys.exit(1 if missing else 0)
"@
    & $VenvPy -c $code 2>$null
    return ($LASTEXITCODE -eq 0)
}

function Get-NunchakuCudaWheelUrl {
    return "https://github.com/nunchaku-ai/nunchaku/releases/download/v1.3.0dev20260213/nunchaku-1.3.0.dev20260213+cu12.8torch2.11-cp312-cp312-win_amd64.whl"
}

function Test-NunchakuReady {
    param([string]$VenvPy)
    if (-not (Test-Path $VenvPy)) { return $false }
    $code = @"
import importlib.util, sys
sys.exit(0 if importlib.util.find_spec('nunchaku') is not None else 1)
"@
    & $VenvPy -c $code 2>$null
    return ($LASTEXITCODE -eq 0)
}

function Test-NunchakuModelPresent {
    param([string]$ModelsDir = (Join-Path (Get-Location) "models\image"))
    if (-not (Test-Path $ModelsDir)) { return $false }
    $files = Get-ChildItem -LiteralPath $ModelsDir -Recurse -File -Include *.safetensors -ErrorAction SilentlyContinue
    foreach ($file in $files) {
        $name = $file.Name.ToLowerInvariant()
        if (($name.Contains("svdq") -or $name.Contains("nunchaku")) -and (
            $name.Contains("flux") -or
            $name.Contains("qwen") -or
            $name.Contains("z-image") -or
            $name.Contains("z_image")
        )) {
            return $true
        }
    }
    return $false
}

function Install-NunchakuCuda {
    param([string]$VenvPy)
    if (Test-NunchakuReady $VenvPy) { return $true }
    Write-Host "[setup] installing Nunchaku (FLUX/Qwen/Z-Image SVDQuant fp4)..." -ForegroundColor Cyan
    Write-Host "[setup] matching cu12.8 + torch2.11 + Python 3.12 wheel (~300 MB)" -ForegroundColor DarkGray
    & $VenvPy -m pip install (Get-NunchakuCudaWheelUrl)
    if ($LASTEXITCODE -ne 0) { return $false }
    return (Test-NunchakuReady $VenvPy)
}

function Install-AcceleratorStack {
    # The full REAL-mode stack for the detected profile: PyTorch (profile-specific
    # index), the profile's backend requirements (diffusers, sounddevice, etc.), and
    # the managed llama.cpp runtime. This is what makes "double-click and it works"
    # true — both run.ps1 (first run) and setup.ps1 install through here so they
    # behave identically. Optional Nunchaku acceleration is handled separately.
    param(
        [string]$VenvPy,
        $Profile
    )
    $profileId = [string]$Profile.selected_profile
    $torchPackages = @($Profile.install.torch.packages)
    $torchIndex = [string]$Profile.install.torch.index_url

    if ($torchPackages.Count -gt 0) {
        Write-Host "[setup] installing PyTorch for $profileId (this can be a few GB)..." -ForegroundColor Cyan
        if ([string]::IsNullOrWhiteSpace($torchIndex)) {
            & $VenvPy -m pip install @torchPackages
        } else {
            Write-Host "[setup] torch index: $torchIndex" -ForegroundColor DarkGray
            & $VenvPy -m pip install @torchPackages --index-url $torchIndex
        }
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[setup] PyTorch install failed (exit $LASTEXITCODE). Check your network and retry." -ForegroundColor Red
            exit 1
        }
    }

    $verify = [string]$Profile.install.verify
    if (-not [string]::IsNullOrWhiteSpace($verify)) {
        $check = & $VenvPy -c $verify 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[setup] PyTorch verification warning for $($profileId): $check" -ForegroundColor Yellow
        } else {
            Write-Host "[setup] torch OK: $check" -ForegroundColor DarkGray
        }
    }

    foreach ($req in @($Profile.install.requirements)) {
        if ([string]::IsNullOrWhiteSpace($req)) { continue }
        Write-Host "[setup] installing backend requirements: $req ..." -ForegroundColor Cyan
        & $VenvPy -m pip install -r $req
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[setup] '$req' install failed (exit $LASTEXITCODE)." -ForegroundColor Red
            exit 1
        }
    }

    # llama.cpp runtime (LLM/RAG/TTS). Best-effort: installable later from Settings.
    Write-Host "[setup] installing the matching llama.cpp runtime..." -ForegroundColor Cyan
    & $VenvPy (Join-Path $PSScriptRoot "fetch_llama.py")
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[setup] llama.cpp auto-install failed; install later from Settings -> LLM runtime." -ForegroundColor Yellow
    }
}

function Test-VoiceAssetsReady {
    param([string]$VenvPy)
    if (-not (Test-Path $VenvPy)) { return $false }
    $code = @"
from pathlib import Path
import sys
sys.path.insert(0, str(Path('backend').resolve()))
from app.services.voice_engine.assets import discover_assets
sys.exit(0 if discover_assets()['ready'] else 1)
"@
    & $VenvPy -c $code 2>$null
    return ($LASTEXITCODE -eq 0)
}

function Install-VoiceAssets {
    param([string]$VenvPy)
    Write-Host "[setup] downloading shared voice changer assets..." -ForegroundColor Cyan
    & $VenvPy "scripts\fetch_voice_assets.py"
    return ($LASTEXITCODE -eq 0)
}

function Install-FrontendDeps {
    # npm is a native exe, so a failed install does NOT throw — it just returns a
    # non-zero code. Callers used to ignore that and march on to `npm run dev`,
    # turning a network/lock failure into a baffling "'vite' is not recognized".
    # Here we check the code, retry once after clearing a possibly-corrupt cache,
    # then fail loudly with actionable help.
    param([string]$FrontendDir)
    $code = 0
    $npm = Get-NpmCommand
    Push-Location $FrontendDir
    try {
        & $npm install
        if ($LASTEXITCODE -eq 0) { return }
        Write-Host "[setup] npm install failed (exit $LASTEXITCODE); clearing cache and retrying once..." -ForegroundColor DarkYellow
        & $npm cache clean --force
        & $npm install
        if ($LASTEXITCODE -eq 0) { return }
        $code = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    Show-NpmFailureHelp $code
    exit 1
}
