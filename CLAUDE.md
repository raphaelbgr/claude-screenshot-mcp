# Claude Code Project Instructions

## Auto-start Screenshot Daemon

When starting a session in this project, ensure the screenshot daemon is running
so the user can capture screen regions and paste file paths into the conversation.

### Startup check

Run this at the beginning of each session:

```bash
claude-screenshot-daemon --status
```

- If it prints "Daemon is running" — do nothing, it's already active.
- If it prints "Daemon is not running" (exit code 1) — start it as a background process:

```bash
claude-screenshot-daemon &
```

On Windows (PowerShell):

```powershell
Start-Process -NoNewWindow claude-screenshot-daemon
```

### Important notes

- The daemon uses a PID lock file to prevent duplicate instances. Only one daemon
  runs at a time. If `--status` says it's running, do NOT start another one.
- The daemon listens for a global hotkey (default: `Ctrl+Shift+Q`) and opens
  a region selector overlay. The captured screenshot path is copied to clipboard.
- The user pastes the path into Claude Code with `Ctrl+V`.
- If the daemon crashes or the PID file is stale, use `--force` to override:
  `claude-screenshot-daemon --force &`

### Default hotkey

`Ctrl+Shift+Q` — configurable via `claude-screenshot-daemon --set-hotkey <combo>`

### Troubleshooting

If the user reports the hotkey isn't working:
1. Run `claude-screenshot-daemon --debug` to see detected keypresses
2. Check if another application is capturing the same hotkey
3. Try a different hotkey: `claude-screenshot-daemon --set-hotkey ctrl+alt+p`

## Project Overview

This is a Python MCP server + hotkey daemon for screen capture. Key files:

- `screenshot_mcp/server.py` — MCP server with 6 tools (capture region, fullscreen, etc.)
- `screenshot_mcp/daemon.py` — Hotkey listener with instance lock
- `screenshot_mcp/capture.py` — Screen capture + tkinter overlay
- `screenshot_mcp/config.py` — JSON config management

## Tech stack

- Python 3.10+, FastMCP, pynput, mss, Pillow, tkinter
- MCP transport: stdio
- Hotkey detection: pynput with virtual key code normalization
