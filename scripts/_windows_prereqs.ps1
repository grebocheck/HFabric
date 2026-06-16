# Shared Windows prerequisite checks for setup.ps1 and scripts/run.ps1.
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
