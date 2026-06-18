<#
  HFabric update script

    .\update.ps1              # git pull + refresh deps for detected profile
    .\update.ps1 -Stub        # refresh as CPU-safe/STUB
    .\update.ps1 -DownloadAll # refresh deps + starter models + voice assets
    .\update.ps1 -NoPull      # only refresh local deps
    .\update.ps1 -Prod        # also rebuild frontend/dist

  The script uses the same local .tools Python/Node bootstrap as setup/run. It
  never touches models/ or data/. If local source edits exist, git uses
  --autostash so the pull does not overwrite them silently.
#>
param(
    [switch]$Stub,
    [switch]$DownloadAll,
    [switch]$NoPull,
    [switch]$Prod,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root
. "$root\scripts\_windows_prereqs.ps1"

function Write-Section([string]$Title) {
    Write-Host "`n> $Title" -ForegroundColor Green -BackgroundColor DarkGray
}

function Write-Warn([string]$Message) {
    Write-Host "  ! $Message" -ForegroundColor Yellow
}

Write-Host "`nHFabric updater`n" -ForegroundColor Cyan

if (-not $NoPull) {
    Write-Section "Updating source"
    if ((Get-Command git -ErrorAction SilentlyContinue) -and (Test-Path ".git")) {
        $dirty = (& git status --porcelain) -join ""
        $pullArgs = @("pull", "--ff-only")
        if (-not [string]::IsNullOrWhiteSpace($dirty)) {
            Write-Warn "Local edits detected; git pull will use --autostash."
            $pullArgs += "--autostash"
        }
        & git @pullArgs
        if ($LASTEXITCODE -ne 0) {
            Write-Warn "git pull failed. Resolve the git message above, then rerun update."
            exit $LASTEXITCODE
        }
    } else {
        Write-Warn "This folder is not a git checkout or git is missing; skipping source update."
    }
}

Write-Section "Refreshing dependencies"
$setupArgs = @("-NoOptionalPrompts")
if ($Stub) { $setupArgs += "-Stub" }
if ($DownloadAll) { $setupArgs += "-DownloadAll" }
if ($Force) { $setupArgs += "-Force" }

Write-Host "  setup.ps1 $($setupArgs -join ' ')" -ForegroundColor DarkGray
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$root\setup.ps1" @setupArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if ($Prod) {
    Write-Section "Rebuilding frontend"
    Assert-NodeToolchain
    $npmCmd = Get-NpmCommand
    Push-Location "$root\frontend"
    try {
        & $npmCmd run build
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    } finally {
        Pop-Location
    }
}

Write-Host "`nUpdate complete. Start with run.bat (or run.bat --prod).`n" -ForegroundColor Green
