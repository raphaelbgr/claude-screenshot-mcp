#!/usr/bin/env python3
"""
Hotkey daemon for Claude Screenshot MCP.

Runs as a background process that:
1. Listens for a configurable global hotkey
2. On hotkey press, launches the region selector overlay
3. Saves the screenshot and copies the file path to clipboard
4. Optionally shows a system notification

Usage:
    claude-screenshot-daemon                          # Use default hotkey (ctrl+shift+s)
    claude-screenshot-daemon --hotkey ctrl+alt+p      # Use custom hotkey
    claude-screenshot-daemon --hotkey f9              # Single key hotkey
    claude-screenshot-daemon --debug                  # Show all key presses (for troubleshooting)
    claude-screenshot-daemon --set-hotkey ctrl+alt+s  # Save new hotkey to config and start
"""

import argparse
import atexit
import json
import os
import sys
import signal
import tempfile
import time
import subprocess
from pathlib import Path

from .config import load_config, update_config, get_config_path, get_config_dir
from .capture import select_region_and_capture, copy_to_clipboard


# ──────────────────────────────────────────────
# Instance Lock (PID file)
# ──────────────────────────────────────────────

def _get_pid_file() -> Path:
    """Get the path to the PID lock file."""
    return get_config_dir() / "daemon.pid"


def _is_daemon_running() -> bool:
    """Check if another daemon instance is already running.

    Returns True if a daemon is running, False otherwise.
    Also cleans up stale PID files.
    """
    pid_file = _get_pid_file()
    if not pid_file.exists():
        return False

    try:
        with open(pid_file, "r") as f:
            data = json.load(f)
        old_pid = data.get("pid")
        if old_pid is None:
            return False

        # Check if the process is actually running
        if sys.platform == "win32":
            # On Windows, use tasklist to check if PID exists
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {old_pid}", "/NH"],
                capture_output=True, text=True, timeout=5,
            )
            if str(old_pid) in result.stdout:
                return True
        else:
            # On Unix, send signal 0 to check if process exists
            try:
                os.kill(old_pid, 0)
                return True
            except (OSError, ProcessLookupError):
                pass

        # PID file exists but process is dead — stale lock
        pid_file.unlink(missing_ok=True)
        return False

    except (json.JSONDecodeError, IOError, ValueError):
        # Corrupt PID file — remove it
        pid_file.unlink(missing_ok=True)
        return False


def _acquire_lock() -> bool:
    """Acquire the instance lock by writing our PID to the lock file.

    Returns True if lock acquired, False if another instance is running.
    """
    if _is_daemon_running():
        return False

    pid_file = _get_pid_file()
    try:
        with open(pid_file, "w") as f:
            json.dump({"pid": os.getpid()}, f)

        # Register cleanup on exit
        atexit.register(_release_lock)
        return True
    except IOError:
        return False


def _release_lock():
    """Release the instance lock by removing the PID file."""
    pid_file = _get_pid_file()
    try:
        if pid_file.exists():
            with open(pid_file, "r") as f:
                data = json.load(f)
            # Only delete if it's our PID
            if data.get("pid") == os.getpid():
                pid_file.unlink(missing_ok=True)
    except (json.JSONDecodeError, IOError):
        pid_file.unlink(missing_ok=True)


def _normalize_key(key):
    """Normalize a pynput key so left/right variants match.

    e.g., Key.ctrl_r -> "ctrl", Key.shift_l -> "shift", KeyCode(char='s') -> "s"

    IMPORTANT: When modifier keys (ctrl/shift/alt) are held, pynput reports
    letter keys as control characters (e.g., Ctrl+S -> '\\x13' instead of 's').
    We use the virtual key code (vk) to resolve the actual letter in those cases.
    """
    from pynput.keyboard import Key, KeyCode

    if isinstance(key, Key):
        name = key.name  # e.g., "ctrl_l", "shift_r", "alt_l"
        # Strip _l / _r suffix so both sides match
        for suffix in ("_l", "_r"):
            if name.endswith(suffix):
                return name[: -len(suffix)]
        return name
    elif isinstance(key, KeyCode):
        # First try the virtual key code — this is reliable even with modifiers held
        if key.vk is not None:
            # vk 65-90 = A-Z, convert to lowercase letter
            if 65 <= key.vk <= 90:
                return chr(key.vk).lower()
            # vk 48-57 = 0-9
            if 48 <= key.vk <= 57:
                return chr(key.vk)
            # vk 112-123 = F1-F12
            if 112 <= key.vk <= 123:
                return f"f{key.vk - 111}"
            # Fallback: if char is a normal printable character, use it
            if key.char is not None and key.char.isprintable():
                return key.char.lower()
            return f"vk_{key.vk}"
        # No vk code, use char directly
        if key.char is not None and key.char.isprintable():
            return key.char.lower()
    return str(key)


def _parse_hotkey_string(hotkey_str: str) -> set:
    """Parse a hotkey string like 'ctrl+shift+s' into a set of normalized key names.

    Returns a set of strings like {"ctrl", "shift", "s"}.
    """
    parts = [p.strip().lower() for p in hotkey_str.split("+")]
    normalized = set()
    for part in parts:
        # Normalize common aliases
        aliases = {
            "ctrl": "ctrl",
            "control": "ctrl",
            "shift": "shift",
            "alt": "alt",
            "cmd": "cmd",
            "win": "cmd",
            "super": "cmd",
            "esc": "esc",
            "escape": "esc",
            "enter": "enter",
            "return": "enter",
            "space": "space",
            "tab": "tab",
            "backspace": "backspace",
            "delete": "delete",
            "print_screen": "print_screen",
            "printscreen": "print_screen",
        }
        normalized.add(aliases.get(part, part))
    return normalized


def _show_notification(title: str, message: str):
    """Show a system notification (best-effort, platform-dependent)."""
    try:
        if sys.platform == "win32":
            ps_script = f"""
            [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
            $template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
            $textNodes = $template.GetElementsByTagName("text")
            $textNodes.Item(0).AppendChild($template.CreateTextNode("{title}")) | Out-Null
            $textNodes.Item(1).AppendChild($template.CreateTextNode("{message}")) | Out-Null
            $toast = [Windows.UI.Notifications.ToastNotification]::new($template)
            [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("Claude Screenshot").Show($toast)
            """
            subprocess.Popen(
                ["powershell", "-Command", ps_script],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        elif sys.platform == "darwin":
            subprocess.Popen([
                "osascript", "-e",
                f'display notification "{message}" with title "{title}"',
            ])
        else:
            subprocess.Popen(["notify-send", title, message])
    except Exception:
        pass


def _show_tray_info(hotkey: str, debug: bool = False):
    """Print hotkey info to stderr (visible in terminal)."""
    print("", file=sys.stderr)
    print("  Claude Screenshot Daemon", file=sys.stderr)
    print("  ========================", file=sys.stderr)
    print(f"  Hotkey:  {hotkey}", file=sys.stderr)
    print(f"  Config:  {get_config_path()}", file=sys.stderr)
    print(f"  Status:  Listening...", file=sys.stderr)
    if debug:
        print("  Mode:    DEBUG (showing all key presses)", file=sys.stderr)
    print("", file=sys.stderr)
    print("  Press the hotkey to capture a screen region.", file=sys.stderr)
    print("  Press ESC during capture to cancel.", file=sys.stderr)
    print("  Right-click during capture to cancel.", file=sys.stderr)
    print("  The file path will be copied to your clipboard.", file=sys.stderr)
    print("  Press Ctrl+C to stop the daemon.", file=sys.stderr)
    print("", file=sys.stderr)
    print(f"  Change hotkey:  claude-screenshot-daemon --set-hotkey ctrl+alt+s", file=sys.stderr)
    print("", file=sys.stderr)


def _on_hotkey_triggered(config: dict):
    """Called when the hotkey is pressed."""
    print("  >> Hotkey triggered! Opening region selector...", file=sys.stderr)

    save_dir = config["save_directory"]
    fmt = config.get("image_format", "png")
    overlay_color = config.get("overlay_color", "#00aaff")
    overlay_opacity = config.get("overlay_opacity", 0.3)

    path = select_region_and_capture(
        save_dir=save_dir,
        fmt=fmt,
        overlay_color=overlay_color,
        overlay_opacity=overlay_opacity,
    )

    if path:
        if config.get("copy_path_to_clipboard", True):
            copy_to_clipboard(path)
            print(f"  >> Captured: {path}", file=sys.stderr)
            print(f"  >> Path copied to clipboard! Paste into Claude Code with Ctrl+V", file=sys.stderr)
        else:
            print(f"  >> Captured: {path}", file=sys.stderr)

        if config.get("show_notification", True):
            _show_notification(
                "Claude Screenshot",
                f"Saved! Path copied to clipboard.\n{os.path.basename(path)}",
            )
    else:
        print("  >> Capture cancelled (ESC / right-click / region too small).", file=sys.stderr)


def run_daemon(hotkey_override: str = None, debug: bool = False, skip_lock: bool = False):
    """Main daemon entry point. Uses pynput for global hotkey listening."""
    # Instance lock — prevent multiple daemons
    if not skip_lock:
        if not _acquire_lock():
            print("  [!] Another claude-screenshot-daemon is already running.", file=sys.stderr)
            print(f"      PID file: {_get_pid_file()}", file=sys.stderr)
            print("      To force start, delete the PID file or use --force.", file=sys.stderr)
            sys.exit(0)

    config = load_config()
    hotkey = hotkey_override or config.get("hotkey", "ctrl+shift+s")

    _show_tray_info(hotkey, debug=debug)

    try:
        from pynput import keyboard as pynput_keyboard
    except ImportError:
        print(
            "Error: 'pynput' package is required for the hotkey daemon.\n"
            "Install it with: pip install pynput\n",
            file=sys.stderr,
        )
        sys.exit(1)

    # Parse the hotkey string into normalized key names
    hotkey_names = _parse_hotkey_string(hotkey)
    print(f"  Listening for keys: {hotkey_names}", file=sys.stderr)
    print("", file=sys.stderr)

    # Track currently pressed normalized key names
    current_keys = set()
    capturing = False

    def on_press(key):
        nonlocal capturing
        if capturing:
            return

        normalized = _normalize_key(key)
        current_keys.add(normalized)

        if debug:
            print(f"  [debug] pressed: {key} -> normalized: '{normalized}' | active: {current_keys}", file=sys.stderr)

        # Check if all hotkey keys are currently pressed
        if hotkey_names.issubset(current_keys):
            capturing = True
            current_keys.clear()

            current_config = load_config()
            _on_hotkey_triggered(current_config)
            capturing = False

    def on_release(key):
        normalized = _normalize_key(key)
        current_keys.discard(normalized)

        if debug:
            print(f"  [debug] released: {key} -> normalized: '{normalized}'", file=sys.stderr)

    # Start the listener
    listener = pynput_keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.start()

    # Handle graceful shutdown
    def signal_handler(sig, frame):
        print("\n  Daemon stopped.", file=sys.stderr)
        listener.stop()
        _release_lock()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Keep the main thread alive
    try:
        while listener.is_alive():
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n  Daemon stopped.", file=sys.stderr)
        listener.stop()
        _release_lock()


def main():
    """CLI entry point for the daemon."""
    parser = argparse.ArgumentParser(
        description="Claude Screenshot Daemon - global hotkey screen capture for Claude Code",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  claude-screenshot-daemon                          Use default hotkey
  claude-screenshot-daemon --hotkey ctrl+alt+p      Use custom hotkey (this session only)
  claude-screenshot-daemon --hotkey f9              Single key hotkey
  claude-screenshot-daemon --set-hotkey ctrl+alt+s  Save hotkey to config and start
  claude-screenshot-daemon --debug                  Show key presses for troubleshooting
        """,
    )
    parser.add_argument(
        "--hotkey",
        type=str,
        default=None,
        help="Hotkey combo for this session (e.g., ctrl+shift+s, ctrl+alt+p, f9)",
    )
    parser.add_argument(
        "--set-hotkey",
        type=str,
        default=None,
        help="Save a new default hotkey to config and start the daemon",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Show all key presses in the terminal (for troubleshooting)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force start even if another instance appears to be running",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Check if the daemon is running and exit",
    )

    args = parser.parse_args()

    # --status: just check and report
    if args.status:
        if _is_daemon_running():
            pid_file = _get_pid_file()
            with open(pid_file, "r") as f:
                data = json.load(f)
            print(f"  Daemon is running (PID {data.get('pid')})", file=sys.stderr)
            sys.exit(0)
        else:
            print("  Daemon is not running.", file=sys.stderr)
            sys.exit(1)

    # If --set-hotkey, save it to config first
    if args.set_hotkey:
        update_config("hotkey", args.set_hotkey)
        print(f"  Hotkey saved to config: {args.set_hotkey}", file=sys.stderr)

    hotkey = args.hotkey or args.set_hotkey or None
    run_daemon(hotkey_override=hotkey, debug=args.debug, skip_lock=args.force)


if __name__ == "__main__":
    main()
