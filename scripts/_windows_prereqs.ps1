# Shared Windows setup helpers for setup.ps1 and scripts/run.ps1:
# prerequisite checks (Python / Node) plus a robust frontend `npm install`.
#
# Dot-source this file so the functions land in the caller's scope:
#     . "$PSScriptRoot\_windows_prereqs.ps1"
#
# Why this exists: a bare `npm install` / `python -m venv` throws an opaque
# "CommandNotFoundException" when the toolchain isn't on PATH. Worse, the #1
# Windows trap is a toolchain that *is* installed but invisible to an
# already-open shell because its PATH was captured before the install. These
# helpers refresh PATH from the registry, recheck, optionally auto-install via
# winget, and otherwise fail with an actionable message instead of a stack trace.

function Update-SessionPath {
    # Rebuild this process's PATH from the persisted Machine + User values so a
    # freshly installed tool is visible without reopening the terminal.
    $machine = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [System.Environment]::GetEnvironmentVariable("Path", "User")
    $combined = @($machine, $user) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    if ($combined.Count -gt 0) { $env:Path = $combined -join ";" }
}

function Test-ToolOnPath {
    param([string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Test-WinGetAvailable {
    return [bool](Get-Command winget -ErrorAction SilentlyContinue)
}

function Assert-Python {
    # Needed to create the backend venv. Quiet on success.
    if (Test-ToolOnPath "python") { return }
    Update-SessionPath
    if (Test-ToolOnPath "python") { return }

    Write-Host ""
    Write-Host "[prereq] Python was not found on PATH." -ForegroundColor Red
    Write-Host "         HFabric needs Python 3.12+ to create the backend environment." -ForegroundColor Yellow
    Write-Host "           - Download: https://www.python.org/downloads/  (check 'Add Python to PATH')" -ForegroundColor Cyan
    Write-Host "           - Or:       winget install Python.Python.3.12" -ForegroundColor Cyan
    Write-Host "         If you just installed Python, open a NEW terminal so PATH refreshes." -ForegroundColor Yellow
    exit 1
}

function Assert-NodeToolchain {
    # Needed for the frontend (npm install / dev / build). Quiet on success.
    # Handles the stale-PATH case first, then offers a one-shot winget install.
    if ((Test-ToolOnPath "node") -and (Test-ToolOnPath "npm")) { return }

    Update-SessionPath
    if ((Test-ToolOnPath "node") -and (Test-ToolOnPath "npm")) {
        Write-Host "[prereq] found Node.js after refreshing PATH from the registry." -ForegroundColor DarkGray
        return
    }

    Write-Host ""
    Write-Host "[prereq] Node.js / npm was not found on PATH." -ForegroundColor Red
    Write-Host "         The frontend needs Node.js 18+ (which provides npm)." -ForegroundColor Yellow

    if ((Test-WinGetAvailable) -and [Environment]::UserInteractive) {
        $answer = Read-Host "         Install Node.js LTS now with winget? [Y/n]"
        if ([string]::IsNullOrWhiteSpace($answer) -or $answer.Trim().ToLowerInvariant().StartsWith("y")) {
            Write-Host "[prereq] winget install OpenJS.NodeJS.LTS ..." -ForegroundColor Cyan
            winget install --id OpenJS.NodeJS.LTS -e --source winget `
                --accept-package-agreements --accept-source-agreements
            Update-SessionPath
            if ((Test-ToolOnPath "node") -and (Test-ToolOnPath "npm")) {
                Write-Host "[prereq] Node.js installed and detected." -ForegroundColor Green
                return
            }
            Write-Host "[prereq] Node.js was installed but isn't visible in this session yet." -ForegroundColor Yellow
            Write-Host "         Close this window and start the app again." -ForegroundColor Yellow
            exit 1
        }
    }

    Write-Host "         Install it, then re-run:" -ForegroundColor Yellow
    Write-Host "           - Download: https://nodejs.org/  (LTS; keep 'Add to PATH' checked)" -ForegroundColor Cyan
    Write-Host "           - Or:       winget install OpenJS.NodeJS.LTS" -ForegroundColor Cyan
    Write-Host "         If you just installed Node.js, open a NEW terminal so PATH refreshes." -ForegroundColor Yellow
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
    Write-Host "            and update npm:  npm install -g npm@latest" -ForegroundColor Cyan
    Write-Host "          - EPERM removing node_modules: the folder is locked. Move the project OUT" -ForegroundColor Cyan
    Write-Host "            of a OneDrive-synced folder (Desktop/Documents) to a short local path" -ForegroundColor Cyan
    Write-Host "            like C:\HFabric, close editors/Explorer on it, and exclude it from AV." -ForegroundColor Cyan
    Write-Host "          - Then delete frontend\node_modules and run this again." -ForegroundColor Cyan
}

function Test-AcceleratorStackReady {
    # REAL mode needs the heavy stack; torch is the sentinel. Use find_spec (no
    # actual import) so this stays a fast per-launch check, not a multi-second
    # torch import. Foundation-only venvs won't have torch.
    param([string]$VenvPy)
    if (-not (Test-Path $VenvPy)) { return $false }
    & $VenvPy -c "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('torch') else 1)" 2>$null
    return ($LASTEXITCODE -eq 0)
}

function Install-AcceleratorStack {
    # The full REAL-mode stack for the detected profile: PyTorch (profile-specific
    # index), the profile's backend requirements (diffusers, sounddevice, etc.), and
    # the managed llama.cpp runtime. This is what makes "double-click and it works"
    # true — both run.ps1 (first run) and setup.ps1 install through here so they
    # behave identically. Optional Nunchaku acceleration stays a setup.ps1 prompt.
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

function Install-FrontendDeps {
    # npm is a native exe, so a failed install does NOT throw — it just returns a
    # non-zero code. Callers used to ignore that and march on to `npm run dev`,
    # turning a network/lock failure into a baffling "'vite' is not recognized".
    # Here we check the code, retry once after clearing a possibly-corrupt cache,
    # then fail loudly with actionable help.
    param([string]$FrontendDir)
    $code = 0
    Push-Location $FrontendDir
    try {
        npm install
        if ($LASTEXITCODE -eq 0) { return }
        Write-Host "[setup] npm install failed (exit $LASTEXITCODE); clearing cache and retrying once..." -ForegroundColor DarkYellow
        npm cache clean --force
        npm install
        if ($LASTEXITCODE -eq 0) { return }
        $code = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    Show-NpmFailureHelp $code
    exit 1
}
