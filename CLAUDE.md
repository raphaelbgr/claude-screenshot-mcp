# Claude Code Project Instructions

## Auto-start Screenshot Daemon

When starting a session in this project, ensure the screenshot daemon is running
so the user can capture screen regions and paste file paths into the conversation.

### Startup check

Run this at the beginning of each session:

```bash
claude-screenshot-daemon --status
```

- If it prints "Daemon is running" — inform the user: "Screenshot daemon is already running. Press Ctrl+Shift+Q to capture a screen region, or Ctrl+Alt+Q to recapture the last region."
- If it prints "Daemon is not running" (exit code 1) — start it as a background process and then inform the user: "Screenshot daemon started. Press Ctrl+Shift+Q to capture a screen region, or Ctrl+Alt+Q to recapture the last region."

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
- The daemon listens for two global hotkeys:
  - `Ctrl+Shift+Q` — opens a region selector overlay. The captured screenshot path is copied to clipboard.
  - `Ctrl+Alt+Q` — instantly re-captures the last selected region (no overlay). Falls back to interactive selector if no previous region.
- The user pastes the path into Claude Code with `Ctrl+V`.
- If the daemon crashes or the PID file is stale, use `--force` to override:
  `claude-screenshot-daemon --force &`

### Default hotkeys

| Action | Default | Change with |
|--------|---------|-------------|
| Capture region | `Ctrl+Shift+Q` | `--set-hotkey <combo>` |
| Recapture last region | `Ctrl+Alt+Q` | `--set-recapture-hotkey <combo>` |

### Troubleshooting

If the user reports the hotkey isn't working:
1. Run `claude-screenshot-daemon --debug` to see detected keypresses
2. Check if another application is capturing the same hotkey
3. Try a different hotkey: `claude-screenshot-daemon --set-hotkey ctrl+alt+p`

## MCP Recapture Tool (for LLMs)

The `screenshot_recapture_region` MCP tool lets Claude Code (or any LLM client)
repeatedly capture the same screen area without user interaction:

1. **First call** — if no previous region exists, it automatically opens the
   interactive selector for the user to pick an area. The coordinates are saved.
2. **Subsequent calls** — instantly re-captures the saved coordinates. No overlay,
   no user interaction. The file path is returned in the JSON response.

This is ideal for automated workflows where the LLM needs to monitor a specific
area (build logs, UI changes, terminal output) by calling the tool in a loop.

## Project Overview

This is a Python MCP server + hotkey daemon for screen capture. Key files:

- `screenshot_mcp/server.py` — MCP server with 7 tools (capture region, recapture, fullscreen, etc.)
- `screenshot_mcp/daemon.py` — Hotkey listener with instance lock
- `screenshot_mcp/capture.py` — Screen capture + tkinter overlay
- `screenshot_mcp/config.py` — JSON config management

## Tech stack

- Python 3.10+, FastMCP, pynput, mss, Pillow, tkinter
- MCP transport: stdio
- Hotkey detection: pynput with virtual key code normalization
