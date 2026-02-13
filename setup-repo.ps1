# ============================================================
# Claude Screenshot MCP - Git Repository Setup
# ============================================================
# Run with:  powershell -ExecutionPolicy Bypass -File setup-repo.ps1
#
# This script initializes the git repo, creates the first commit,
# and pushes to GitHub. Run this ONCE to set up the repo.
# ============================================================

$ErrorActionPreference = "Stop"

$repoUrl = "git@github.com:raphaelbgr/claude-screenshot-mcp.git"

Write-Host ""
Write-Host "  Claude Screenshot MCP - Repository Setup" -ForegroundColor Cyan
Write-Host "  =========================================" -ForegroundColor DarkCyan
Write-Host ""

# Check git
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "  [FAIL] git is not installed. Install from https://git-scm.com/" -ForegroundColor Red
    exit 1
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $scriptDir

# Check if already a git repo
if (Test-Path ".git") {
    Write-Host "  [INFO] Already a git repository." -ForegroundColor Yellow
    $confirm = Read-Host "  Reset and start fresh? (y/N)"
    if ($confirm -ne "y") {
        Write-Host "  Aborted." -ForegroundColor Gray
        Pop-Location
        exit 0
    }
    Remove-Item -Recurse -Force .git
}

# Initialize repo
Write-Host "  [1/5] Initializing git repository..." -ForegroundColor White
git init
git branch -M main

# Stage files
Write-Host "  [2/5] Staging files..." -ForegroundColor White
git add `
    screenshot_mcp/__init__.py `
    screenshot_mcp/__main__.py `
    screenshot_mcp/capture.py `
    screenshot_mcp/config.py `
    screenshot_mcp/daemon.py `
    screenshot_mcp/server.py `
    pyproject.toml `
    README.md `
    CLAUDE.md `
    LICENSE `
    .gitignore `
    install.ps1 `
    install.sh `
    install.bat `
    setup-repo.ps1 `
    docs/

# Show what's staged
Write-Host ""
Write-Host "  Staged files:" -ForegroundColor Gray
git status --short
Write-Host ""

# First commit
Write-Host "  [3/5] Creating initial commit..." -ForegroundColor White
git commit -m "Initial release: Claude Screenshot MCP plugin

Screen capture plugin for Claude Code with:
- Global hotkey daemon (Ctrl+Alt+Shift+S) for region capture
- MCP server with 6 tools for Claude Code integration
- Cross-platform support (Windows, macOS, Linux)
- Configurable hotkey, save directory, image format
- Pre-capture technique (overlay never appears in screenshots)
- Smart key normalization for reliable hotkey detection
- Installer scripts with prerequisite verification"

# Add remote
Write-Host "  [4/5] Adding remote origin..." -ForegroundColor White
Write-Host "  Remote: $repoUrl" -ForegroundColor Gray

$hasRemote = git remote 2>&1 | Select-String "origin"
if ($hasRemote) {
    git remote set-url origin $repoUrl
} else {
    git remote add origin $repoUrl
}

# Push
Write-Host "  [5/5] Pushing to GitHub..." -ForegroundColor White
Write-Host ""
Write-Host "  NOTE: You need to create the repo on GitHub first:" -ForegroundColor Yellow
Write-Host "  https://github.com/new -> Name: claude-screenshot-mcp" -ForegroundColor Yellow
Write-Host ""

$pushNow = Read-Host "  Push now? (y/N)"
if ($pushNow -eq "y") {
    git push -u origin main
    Write-Host ""
    Write-Host "  [OK] Pushed to $repoUrl" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "  [INFO] Repo initialized locally. Push when ready with:" -ForegroundColor Gray
    Write-Host "         git push -u origin main" -ForegroundColor Yellow
}

Write-Host ""
Pop-Location
