#!/usr/bin/env bash
# ============================================================
# Claude Screenshot MCP - macOS / Linux Installer
# ============================================================
# Run with:  chmod +x install.sh && ./install.sh
# ============================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
WHITE='\033[1;37m'
GRAY='\033[0;37m'
NC='\033[0m'

write_check() {
    local label="$1" status="$2" detail="$3"
    if [ "$status" = "OK" ]; then
        echo -e "  ${GREEN}[OK]${NC}   $label ${GRAY}- $detail${NC}"
    elif [ "$status" = "WARN" ]; then
        echo -e "  ${YELLOW}[WARN]${NC} $label ${GRAY}- $detail${NC}"
    else
        echo -e "  ${RED}[FAIL]${NC} $label ${GRAY}- $detail${NC}"
    fi
}

write_step() {
    echo ""
    echo -e "  ${WHITE}[$1/$2] $3${NC}"
}

# ── Banner ──────────────────────────────────────────────────
echo ""
echo -e "  ${CYAN}================================================${NC}"
echo -e "  ${CYAN}  Claude Screenshot MCP - Installer             ${NC}"
echo -e "  ${CYAN}================================================${NC}"
echo ""

TOTAL_STEPS=6
HAS_ERRORS=0
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# ── Step 1: Check Prerequisites ─────────────────────────────
write_step 1 $TOTAL_STEPS "Checking prerequisites..."

# Check Python
PYTHON_CMD=""
for cmd in python3 python; do
    if command -v "$cmd" &> /dev/null; then
        ver=$("$cmd" --version 2>&1 | grep -oP 'Python \K[\d.]+')
        if [ -n "$ver" ]; then
            major=$(echo "$ver" | cut -d. -f1)
            minor=$(echo "$ver" | cut -d. -f2)
            if [ "$major" -ge 3 ] && [ "$minor" -ge 10 ]; then
                PYTHON_CMD="$cmd"
                write_check "Python" "OK" "$ver (using '$cmd')"
                break
            else
                write_check "Python" "FAIL" "$ver found but 3.10+ required"
            fi
        fi
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    write_check "Python" "FAIL" "Not found. Install Python 3.10+:"
    if [[ "$OSTYPE" == "darwin"* ]]; then
        echo "           brew install python3"
    else
        echo "           sudo apt install python3 python3-pip  (Debian/Ubuntu)"
        echo "           sudo dnf install python3 python3-pip  (Fedora)"
    fi
    HAS_ERRORS=1
fi

# Check pip
if [ -n "$PYTHON_CMD" ]; then
    if $PYTHON_CMD -m pip --version &> /dev/null; then
        pip_ver=$($PYTHON_CMD -m pip --version | grep -oP 'pip \K[\d.]+')
        write_check "pip" "OK" "$pip_ver"
    else
        write_check "pip" "FAIL" "pip not found. Run: $PYTHON_CMD -m ensurepip"
        HAS_ERRORS=1
    fi
fi

# Check tkinter
if [ -n "$PYTHON_CMD" ]; then
    if $PYTHON_CMD -c "import tkinter" &> /dev/null; then
        write_check "tkinter" "OK" "Available"
    else
        write_check "tkinter" "FAIL" "Not available."
        if [[ "$OSTYPE" == "darwin"* ]]; then
            echo "           brew install python-tk"
        else
            echo "           sudo apt install python3-tk  (Debian/Ubuntu)"
        fi
        HAS_ERRORS=1
    fi
fi

# Check Claude Code
CLAUDE_FOUND=0
if command -v claude &> /dev/null; then
    claude_ver=$(claude --version 2>&1 || true)
    write_check "Claude Code" "OK" "$claude_ver"
    CLAUDE_FOUND=1
else
    write_check "Claude Code" "WARN" "Not found (optional). Install: https://docs.claude.com"
fi

# Check git
if command -v git &> /dev/null; then
    git_ver=$(git --version)
    write_check "git" "OK" "$git_ver"
else
    write_check "git" "WARN" "Not found (optional, only for development)"
fi

# Linux: check xclip/xsel for clipboard
if [[ "$OSTYPE" == "linux"* ]]; then
    if command -v xclip &> /dev/null || command -v xsel &> /dev/null; then
        write_check "Clipboard" "OK" "xclip/xsel available"
    else
        write_check "Clipboard" "WARN" "Install xclip for clipboard support: sudo apt install xclip"
    fi
fi

if [ $HAS_ERRORS -ne 0 ]; then
    echo ""
    echo -e "  ${RED}Some required prerequisites are missing. Fix the issues above and re-run.${NC}"
    echo ""
    exit 1
fi

# ── Step 2: Install Package ─────────────────────────────────
write_step 2 $TOTAL_STEPS "Installing claude-screenshot-mcp..."

cd "$SCRIPT_DIR"
$PYTHON_CMD -m pip install -e ".[all]" 2>&1 | while read -r line; do
    if echo "$line" | grep -iq "error"; then
        echo -e "  ${RED}$line${NC}"
    elif echo "$line" | grep -iq "successfully"; then
        echo -e "  ${GREEN}$line${NC}"
    fi
done
write_check "Package" "OK" "Installed successfully"

# ── Step 3: Register MCP Server ──────────────────────────────
write_step 3 $TOTAL_STEPS "Registering MCP server with Claude Code..."

if [ $CLAUDE_FOUND -eq 1 ]; then
    if claude mcp add screenshot-mcp -- "$PYTHON_CMD" -m screenshot_mcp 2>/dev/null; then
        write_check "MCP Server" "OK" "Registered as 'screenshot-mcp'"
    else
        write_check "MCP Server" "WARN" "Auto-registration failed. Register manually:"
        echo "           claude mcp add screenshot-mcp -- $PYTHON_CMD -m screenshot_mcp"
    fi
else
    write_check "MCP Server" "WARN" "Claude Code not found. Register manually when installed:"
    echo "           claude mcp add screenshot-mcp -- $PYTHON_CMD -m screenshot_mcp"
fi

# ── Step 4: Verify Installation ──────────────────────────────
write_step 4 $TOTAL_STEPS "Verifying installation..."

$PYTHON_CMD -c "from screenshot_mcp.config import load_config" 2>/dev/null && \
    write_check "Config module" "OK" "Importable" || \
    write_check "Config module" "FAIL" "Import failed"

$PYTHON_CMD -c "from screenshot_mcp.capture import capture_full_screen" 2>/dev/null && \
    write_check "Capture module" "OK" "Importable" || \
    write_check "Capture module" "FAIL" "Import failed"

$PYTHON_CMD -c "from screenshot_mcp.server import mcp" 2>/dev/null && \
    write_check "MCP Server" "OK" "Importable" || \
    write_check "MCP Server" "FAIL" "Import failed"

if command -v claude-screenshot-daemon &> /dev/null; then
    write_check "Daemon CLI" "OK" "$(which claude-screenshot-daemon)"
else
    write_check "Daemon CLI" "WARN" "Not on PATH. Try: $PYTHON_CMD -m screenshot_mcp.daemon"
fi

# ── Step 5: Auto-start with Claude Code ──────────────────────
write_step 5 $TOTAL_STEPS "Auto-start configuration..."

echo ""
echo -e "  ${WHITE}Would you like the screenshot daemon to start automatically${NC}"
echo -e "  ${WHITE}every time Claude Code opens a session in this project?${NC}"
echo ""
echo -e "  ${GRAY}How it works:${NC}"
echo -e "  ${GRAY}  - Claude Code reads CLAUDE.md on startup${NC}"
echo -e "  ${GRAY}  - It checks if the daemon is already running (via PID lock file)${NC}"
echo -e "  ${GRAY}  - If not running, it starts the daemon as a background task${NC}"
echo -e "  ${GRAY}  - Only ONE instance can run at a time (instance protection)${NC}"
echo ""
read -r -p "  Enable auto-start? (Y/n) " AUTO_START

if [ -z "$AUTO_START" ] || [ "$AUTO_START" = "y" ] || [ "$AUTO_START" = "Y" ]; then
    CLAUDE_MD_PATH="$SCRIPT_DIR/CLAUDE.md"
    if [ -f "$CLAUDE_MD_PATH" ]; then
        write_check "Auto-start" "OK" "CLAUDE.md is present — daemon will auto-start with Claude Code"
    else
        write_check "Auto-start" "WARN" "CLAUDE.md not found in project root. Copy it from the repo."
    fi

    # Offer global install
    CLAUDE_DIR="$HOME/.claude"
    if [ -d "$CLAUDE_DIR" ]; then
        echo ""
        echo -e "  ${WHITE}Also install globally (all Claude Code projects)?${NC}"
        echo -e "  ${GRAY}This copies the auto-start instruction to $CLAUDE_DIR${NC}"
        read -r -p "  Install globally? (y/N) " GLOBAL

        if [ "$GLOBAL" = "y" ] || [ "$GLOBAL" = "Y" ]; then
            GLOBAL_CLAUDE_MD="$CLAUDE_DIR/CLAUDE.md"
            AUTO_START_BLOCK="
# Auto-start Screenshot Daemon
# On session start, check if claude-screenshot-daemon is running.
# If not, start it as a background task. Only one instance runs at a time (PID lock).
# To start manually: claude-screenshot-daemon
# To check status:   claude-screenshot-daemon --status
# To change hotkey:  claude-screenshot-daemon --set-hotkey ctrl+alt+p"

            if [ -f "$GLOBAL_CLAUDE_MD" ]; then
                if grep -q "screenshot-daemon" "$GLOBAL_CLAUDE_MD" 2>/dev/null; then
                    write_check "Global auto-start" "OK" "Already configured in $GLOBAL_CLAUDE_MD"
                else
                    echo "$AUTO_START_BLOCK" >> "$GLOBAL_CLAUDE_MD"
                    write_check "Global auto-start" "OK" "Appended to $GLOBAL_CLAUDE_MD"
                fi
            else
                echo "$AUTO_START_BLOCK" > "$GLOBAL_CLAUDE_MD"
                write_check "Global auto-start" "OK" "Created $GLOBAL_CLAUDE_MD"
            fi
        fi
    fi
else
    echo ""
    echo -e "  ${GRAY}Skipped. Enable auto-start later by keeping CLAUDE.md in your project.${NC}"
    echo -e "  ${GRAY}Or start the daemon manually: claude-screenshot-daemon${NC}"
fi

# ── Step 6: Summary ──────────────────────────────────────────
write_step 6 $TOTAL_STEPS "Done!"

echo ""
echo -e "  ${GREEN}================================================${NC}"
echo -e "  ${GREEN}  Installation Complete!                         ${NC}"
echo -e "  ${GREEN}================================================${NC}"
echo ""
echo -e "  ${WHITE}HOW TO USE:${NC}"
echo ""
echo -e "  ${GRAY}  1. Start the hotkey daemon:${NC}"
echo -e "  ${YELLOW}     claude-screenshot-daemon${NC}"
echo ""
echo -e "  ${GRAY}  2. Press Ctrl+Shift+Q to capture a region${NC}"
echo ""
echo -e "  ${GRAY}  3. Paste the file path into Claude Code with Ctrl+V${NC}"
echo ""
echo -e "  ${WHITE}INSTANCE PROTECTION:${NC}"
echo ""
echo -e "  ${GRAY}  The daemon uses a PID lock file — only one instance${NC}"
echo -e "  ${GRAY}  can run at a time. Safe to call multiple times.${NC}"
echo -e "  ${GRAY}  Check status:   claude-screenshot-daemon --status${NC}"
echo ""
echo -e "  ${WHITE}CONFIGURE:${NC}"
echo ""
echo -e "  ${GRAY}  Change hotkey:  claude-screenshot-daemon --set-hotkey ctrl+alt+p${NC}"
echo -e "  ${GRAY}  Debug mode:     claude-screenshot-daemon --debug${NC}"
echo -e "  ${GRAY}  During capture: ESC or Right-click to cancel${NC}"
echo ""
