# ============================================================
# Claude Screenshot MCP - Windows Installer
# ============================================================
# Run with:  powershell -ExecutionPolicy Bypass -File install.ps1
# ============================================================

$ErrorActionPreference = "Stop"

function Write-Header($text) {
    Write-Host ""
    Write-Host "  $text" -ForegroundColor Cyan
    Write-Host "  $('=' * $text.Length)" -ForegroundColor DarkCyan
    Write-Host ""
}

function Write-Check($label, $status, $detail) {
    if ($status -eq "OK") {
        Write-Host "  [OK]   $label" -ForegroundColor Green -NoNewline
        Write-Host " - $detail" -ForegroundColor DarkGray
    } elseif ($status -eq "WARN") {
        Write-Host "  [WARN] $label" -ForegroundColor Yellow -NoNewline
        Write-Host " - $detail" -ForegroundColor DarkGray
    } else {
        Write-Host "  [FAIL] $label" -ForegroundColor Red -NoNewline
        Write-Host " - $detail" -ForegroundColor DarkGray
    }
}

function Write-Step($num, $total, $text) {
    Write-Host ""
    Write-Host "  [$num/$total] $text" -ForegroundColor White
}

# ── Banner ──────────────────────────────────────────────────
Write-Host ""
Write-Host "  ================================================" -ForegroundColor Cyan
Write-Host "    Claude Screenshot MCP - Installer for Windows  " -ForegroundColor Cyan
Write-Host "  ================================================" -ForegroundColor Cyan
Write-Host ""

$totalSteps = 6
$hasErrors = $false

# ── Step 1: Check Prerequisites ─────────────────────────────
Write-Step 1 $totalSteps "Checking prerequisites..."

# Check Python
$pythonCmd = $null
$pythonVersion = $null
foreach ($cmd in @("python", "python3", "py")) {
    try {
        $ver = & $cmd --version 2>&1
        if ($ver -match "Python (\d+\.\d+\.\d+)") {
            $pythonVersion = $Matches[1]
            $pythonCmd = $cmd
            break
        }
    } catch { }
}

if ($pythonCmd) {
    $major, $minor, $patch = $pythonVersion.Split(".")
    if ([int]$major -ge 3 -and [int]$minor -ge 10) {
        Write-Check "Python" "OK" "$pythonVersion (using '$pythonCmd')"
    } else {
        Write-Check "Python" "FAIL" "$pythonVersion found but 3.10+ required"
        $hasErrors = $true
    }
} else {
    Write-Check "Python" "FAIL" "Not found. Install from https://www.python.org/downloads/"
    $hasErrors = $true
}

# Check pip
if ($pythonCmd) {
    try {
        $pipVer = & $pythonCmd -m pip --version 2>&1
        if ($pipVer -match "pip (\S+)") {
            Write-Check "pip" "OK" $Matches[1]
        }
    } catch {
        Write-Check "pip" "FAIL" "pip not found. Run: $pythonCmd -m ensurepip"
        $hasErrors = $true
    }
}

# Check tkinter (required for the overlay)
if ($pythonCmd) {
    try {
        & $pythonCmd -c "import tkinter" 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Check "tkinter" "OK" "Available"
        } else {
            Write-Check "tkinter" "FAIL" "Not available. Reinstall Python with tkinter checked."
            $hasErrors = $true
        }
    } catch {
        Write-Check "tkinter" "WARN" "Could not verify. Usually included with Python on Windows."
    }
}

# Check Claude Code
$claudeFound = $false
try {
    $claudeVer = & claude --version 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Check "Claude Code" "OK" "$claudeVer"
        $claudeFound = $true
    }
} catch {
    Write-Check "Claude Code" "WARN" "Not found. Install from https://docs.claude.com/en/docs/claude-code"
    Write-Host "           You can still use the daemon without it." -ForegroundColor DarkGray
}

# Check git (optional)
try {
    $gitVer = & git --version 2>&1
    if ($gitVer -match "git version") {
        Write-Check "git" "OK" "$gitVer"
    }
} catch {
    Write-Check "git" "WARN" "Not found (optional, only needed for development)"
}

if ($hasErrors) {
    Write-Host ""
    Write-Host "  Some required prerequisites are missing. Please fix the issues above and re-run." -ForegroundColor Red
    Write-Host ""
    Read-Host "  Press Enter to exit"
    exit 1
}

# ── Step 2: Install Package ─────────────────────────────────
Write-Step 2 $totalSteps "Installing claude-screenshot-mcp..."

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $scriptDir

try {
    & $pythonCmd -m pip install -e ".[all]" 2>&1 | ForEach-Object {
        if ($_ -match "error|ERROR|Error") {
            Write-Host "  $_" -ForegroundColor Red
        } elseif ($_ -match "Successfully") {
            Write-Host "  $_" -ForegroundColor Green
        }
    }
    if ($LASTEXITCODE -ne 0) {
        throw "pip install failed"
    }
    Write-Check "Package" "OK" "Installed successfully"
} catch {
    Write-Check "Package" "FAIL" "Installation failed: $_"
    Pop-Location
    Read-Host "  Press Enter to exit"
    exit 1
}

Pop-Location

# ── Step 3: Register MCP Server ──────────────────────────────
Write-Step 3 $totalSteps "Registering MCP server with Claude Code..."

if ($claudeFound) {
    try {
        & claude mcp add screenshot-mcp -- $pythonCmd -m screenshot_mcp 2>&1 | Out-Null
        Write-Check "MCP Server" "OK" "Registered as 'screenshot-mcp'"
    } catch {
        Write-Check "MCP Server" "WARN" "Auto-registration failed. Register manually (see below)."
    }
} else {
    Write-Check "MCP Server" "WARN" "Claude Code not found. Register manually when installed:"
    Write-Host "           claude mcp add screenshot-mcp -- $pythonCmd -m screenshot_mcp" -ForegroundColor DarkGray
}

# ── Step 4: Verify Installation ──────────────────────────────
Write-Step 4 $totalSteps "Verifying installation..."

try {
    & $pythonCmd -c "from screenshot_mcp.config import load_config; print('Config OK')" 2>&1 | Out-Null
    Write-Check "Config module" "OK" "Importable"
} catch {
    Write-Check "Config module" "FAIL" "Import failed"
}

try {
    & $pythonCmd -c "from screenshot_mcp.capture import capture_full_screen; print('Capture OK')" 2>&1 | Out-Null
    Write-Check "Capture module" "OK" "Importable"
} catch {
    Write-Check "Capture module" "FAIL" "Import failed"
}

try {
    & $pythonCmd -c "from screenshot_mcp.server import mcp; print('Server OK')" 2>&1 | Out-Null
    Write-Check "MCP Server" "OK" "Importable"
} catch {
    Write-Check "MCP Server" "FAIL" "Import failed"
}

try {
    $daemonPath = & $pythonCmd -c "import shutil; print(shutil.which('claude-screenshot-daemon') or 'NOT_FOUND')" 2>&1
    if ($daemonPath -ne "NOT_FOUND" -and $daemonPath) {
        Write-Check "Daemon CLI" "OK" "$daemonPath"
    } else {
        Write-Check "Daemon CLI" "WARN" "Not on PATH. Try running: $pythonCmd -m screenshot_mcp.daemon"
    }
} catch {
    Write-Check "Daemon CLI" "WARN" "Could not verify"
}

# ── Step 5: Auto-start with Claude Code ──────────────────────
Write-Step 5 $totalSteps "Auto-start configuration..."

Write-Host ""
Write-Host "  Would you like the screenshot daemon to start automatically" -ForegroundColor White
Write-Host "  every time Claude Code opens a session in this project?" -ForegroundColor White
Write-Host ""
Write-Host "  How it works:" -ForegroundColor Gray
Write-Host "    - Claude Code reads CLAUDE.md on startup" -ForegroundColor Gray
Write-Host "    - It checks if the daemon is already running (via PID lock file)" -ForegroundColor Gray
Write-Host "    - If not running, it starts the daemon as a background task" -ForegroundColor Gray
Write-Host "    - Only ONE instance can run at a time (instance protection)" -ForegroundColor Gray
Write-Host ""

$autoStart = Read-Host "  Enable auto-start? (Y/n)"

if ($autoStart -eq "" -or $autoStart -eq "y" -or $autoStart -eq "Y") {
    # CLAUDE.md already exists in the project, just confirm it's in place
    $scriptDir2 = Split-Path -Parent $MyInvocation.MyCommand.Path
    $claudeMdPath = Join-Path $scriptDir2 "CLAUDE.md"

    if (Test-Path $claudeMdPath) {
        Write-Check "Auto-start" "OK" "CLAUDE.md is present — daemon will auto-start with Claude Code"
    } else {
        Write-Check "Auto-start" "WARN" "CLAUDE.md not found in project root. Copy it from the repo."
    }

    # Also copy CLAUDE.md to user's home .claude/ directory for global auto-start
    $userClaudeDir = "$env:USERPROFILE\.claude"
    if (Test-Path $userClaudeDir) {
        Write-Host ""
        Write-Host "  Also install globally (all Claude Code projects)?" -ForegroundColor White
        Write-Host "  This copies the auto-start instruction to $userClaudeDir" -ForegroundColor Gray
        $global = Read-Host "  Install globally? (y/N)"
        if ($global -eq "y" -or $global -eq "Y") {
            $globalClaudeMd = Join-Path $userClaudeDir "CLAUDE.md"
            $autoStartBlock = @"

# Auto-start Screenshot Daemon
# On session start, check if claude-screenshot-daemon is running.
# If not, start it as a background task. Only one instance runs at a time (PID lock).
# To start manually: claude-screenshot-daemon
# To check status:   claude-screenshot-daemon --status
# To change hotkey:  claude-screenshot-daemon --set-hotkey ctrl+alt+p
"@
            if (Test-Path $globalClaudeMd) {
                # Append if not already present
                $existing = Get-Content $globalClaudeMd -Raw
                if ($existing -notmatch "screenshot-daemon") {
                    Add-Content -Path $globalClaudeMd -Value $autoStartBlock
                    Write-Check "Global auto-start" "OK" "Appended to $globalClaudeMd"
                } else {
                    Write-Check "Global auto-start" "OK" "Already configured in $globalClaudeMd"
                }
            } else {
                Set-Content -Path $globalClaudeMd -Value $autoStartBlock
                Write-Check "Global auto-start" "OK" "Created $globalClaudeMd"
            }
        }
    }
} else {
    Write-Host ""
    Write-Host "  Skipped. You can enable auto-start later by keeping CLAUDE.md in your project." -ForegroundColor Gray
    Write-Host "  Or start the daemon manually: claude-screenshot-daemon" -ForegroundColor Gray
}

# ── Step 6: Summary ──────────────────────────────────────────
Write-Step 6 $totalSteps "Done!"

$configPath = "$env:APPDATA\claude-screenshot-mcp\config.json"

Write-Host ""
Write-Host "  ================================================" -ForegroundColor Green
Write-Host "    Installation Complete!                         " -ForegroundColor Green
Write-Host "  ================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  HOW TO USE:" -ForegroundColor White
Write-Host ""
Write-Host "    1. Start the hotkey daemon:" -ForegroundColor Gray
Write-Host "       claude-screenshot-daemon" -ForegroundColor Yellow
Write-Host ""
Write-Host "    2. Press Ctrl+Alt+Shift+S to capture a region" -ForegroundColor Gray
Write-Host ""
Write-Host "    3. Paste the file path into Claude Code with Ctrl+V" -ForegroundColor Gray
Write-Host ""
Write-Host "  INSTANCE PROTECTION:" -ForegroundColor White
Write-Host ""
Write-Host "    The daemon uses a PID lock file — only one instance" -ForegroundColor Gray
Write-Host "    can run at a time. Safe to call multiple times." -ForegroundColor Gray
Write-Host "    Check status:    claude-screenshot-daemon --status" -ForegroundColor Gray
Write-Host ""
Write-Host "  CONFIGURE:" -ForegroundColor White
Write-Host ""
Write-Host "    Change hotkey:   claude-screenshot-daemon --set-hotkey ctrl+alt+p" -ForegroundColor Gray
Write-Host "    Debug mode:      claude-screenshot-daemon --debug" -ForegroundColor Gray
Write-Host "    Config file:     $configPath" -ForegroundColor Gray
Write-Host ""
Write-Host "    During capture:  ESC or Right-click to cancel" -ForegroundColor Gray
Write-Host ""
Read-Host "  Press Enter to close"
