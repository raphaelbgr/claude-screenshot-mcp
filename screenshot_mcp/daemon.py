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

from .config import load_config, update_config, get_config_path, get_config_dir, save_last_region, load_last_region
from .capture import select_region_and_capture, recapture_region, copy_to_clipboard


# ──────────────────────────────────────────────
# Instance Lock (PID file)
# ──────────────────────────────────────────────

# The process name we expect to see for the daemon.
_DAEMON_PROCESS_NAME = "claude-screenshot-daemon"


def _get_pid_file() -> Path:
    """Get the path to the PID lock file."""
    return get_config_dir() / "daemon.pid"


def _get_process_name(pid: int) -> str:
    """Get the process name / command line for a PID. Returns '' if not found."""
    try:
        if sys.platform == "win32":
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=5,
            )
            # Output: "process_name.exe","pid","session","session#","mem"
            for line in result.stdout.strip().splitlines():
                if str(pid) in line:
                    # Extract process name from first CSV field
                    parts = line.strip().strip('"').split('","')
                    if parts:
                        return parts[0].lower()
        else:
            # Unix: read /proc/<pid>/comm or use ps
            comm_path = Path(f"/proc/{pid}/comm")
            if comm_path.exists():
                return comm_path.read_text().strip().lower()
            result = subprocess.run(
                ["ps", "-p", str(pid), "-o", "comm="],
                capture_output=True, text=True, timeout=5,
            )
            return result.stdout.strip().lower()
    except Exception:
        pass
    return ""


def _is_pid_our_daemon(pid: int) -> bool:
    """Check if a PID belongs to a claude-screenshot-daemon process.

    Verifies the process name contains 'claude-screenshot' or 'python'
    (since the daemon runs as a Python script).
    """
    name = _get_process_name(pid)
    if not name:
        return False
    # The daemon may appear as 'claude-screenshot-daemon', 'claude-screenshot-daemon.exe',
    # or 'python.exe' / 'python3' (when run via python -m or script)
    return ("claude-screenshot" in name or "python" in name)


def _is_daemon_running() -> bool:
    """Check if another daemon instance is already running.

    Returns True if a verified daemon is running, False otherwise.
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

        # Check if the process is actually running AND is our daemon
        if _is_pid_our_daemon(old_pid):
            return True

        # PID file exists but process is dead or not ours — stale lock
        pid_file.unlink(missing_ok=True)
        return False

    except (json.JSONDecodeError, IOError, ValueError):
        # Corrupt PID file — remove it
        pid_file.unlink(missing_ok=True)
        return False


def _stop_existing_daemon() -> bool:
    """Stop an existing daemon instance if one is running.

    Reads the PID file, verifies the process is actually our daemon
    (by checking process name), and only then terminates it.

    Returns True if a daemon was stopped, False if none was running.
    """
    pid_file = _get_pid_file()
    if not pid_file.exists():
        return False

    try:
        with open(pid_file, "r") as f:
            data = json.load(f)
        old_pid = data.get("pid")
        if old_pid is None:
            pid_file.unlink(missing_ok=True)
            return False

        if not _is_pid_our_daemon(old_pid):
            # PID exists but it's NOT our daemon — stale file, just clean up
            pid_file.unlink(missing_ok=True)
            return False

        # Verified: this PID is our daemon. Terminate it.
        print(f"  Stopping existing daemon (PID {old_pid})...", file=sys.stderr)
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/PID", str(old_pid), "/F"],
                capture_output=True, timeout=10,
            )
        else:
            os.kill(old_pid, signal.SIGTERM)
            # Give it a moment to clean up
            time.sleep(0.5)
            try:
                os.kill(old_pid, 0)
                # Still alive, force kill
                os.kill(old_pid, signal.SIGKILL)
            except (OSError, ProcessLookupError):
                pass

        # Clean up the PID file
        pid_file.unlink(missing_ok=True)
        # Wait for process to fully exit
        time.sleep(0.5)
        print(f"  Existing daemon stopped.", file=sys.stderr)
        return True

    except (json.JSONDecodeError, IOError, ValueError, subprocess.TimeoutExpired):
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
            json.dump({
                "pid": os.getpid(),
                "process_name": _DAEMON_PROCESS_NAME,
            }, f)

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


def _show_tray_info(hotkey: str, recapture_hotkey: str, debug: bool = False):
    """Print hotkey info to stderr (visible in terminal)."""
    print("", file=sys.stderr)
    print("  Claude Screenshot Daemon", file=sys.stderr)
    print("  ========================", file=sys.stderr)
    print(f"  Capture hotkey:    {hotkey}", file=sys.stderr)
    print(f"  Recapture hotkey:  {recapture_hotkey}", file=sys.stderr)
    print(f"  Config:  {get_config_path()}", file=sys.stderr)
    print(f"  Status:  Listening...", file=sys.stderr)
    if debug:
        print("  Mode:    DEBUG (showing all key presses)", file=sys.stderr)
    print("", file=sys.stderr)
    print("  Press the capture hotkey to select a screen region.", file=sys.stderr)
    print("  Press the recapture hotkey to re-capture the last region.", file=sys.stderr)
    print("  Press ESC during capture to cancel.", file=sys.stderr)
    print("  Right-click during capture to cancel.", file=sys.stderr)
    print("  The file path will be copied to your clipboard.", file=sys.stderr)
    print("  Press Ctrl+C to stop the daemon.", file=sys.stderr)
    print("", file=sys.stderr)
    print(f"  Change hotkeys:", file=sys.stderr)
    print(f"    claude-screenshot-daemon --set-hotkey ctrl+alt+s", file=sys.stderr)
    print(f"    claude-screenshot-daemon --set-recapture-hotkey ctrl+alt+r", file=sys.stderr)
    print("", file=sys.stderr)


def _on_hotkey_triggered(config: dict):
    """Called when the capture hotkey is pressed."""
    print("  >> Hotkey triggered! Opening region selector...", file=sys.stderr)

    save_dir = config["save_directory"]
    fmt = config.get("image_format", "png")
    overlay_color = config.get("overlay_color", "#00aaff")
    overlay_opacity = config.get("overlay_opacity", 0.3)

    capture_result = select_region_and_capture(
        save_dir=save_dir,
        fmt=fmt,
        overlay_color=overlay_color,
        overlay_opacity=overlay_opacity,
        capture_hotkey=config.get("hotkey", "ctrl+shift+q"),
        recapture_hotkey=config.get("recapture_hotkey", "ctrl+alt+q"),
    )

    if capture_result.path:
        # Save region for recapture
        if capture_result.region:
            r = capture_result.region
            save_last_region(r["x"], r["y"], r["width"], r["height"])

        if config.get("copy_path_to_clipboard", True):
            copy_to_clipboard(capture_result.path)
            print(f"  >> Captured: {capture_result.path}", file=sys.stderr)
            print(f"  >> Path copied to clipboard! Paste into Claude Code with Ctrl+V", file=sys.stderr)
        else:
            print(f"  >> Captured: {capture_result.path}", file=sys.stderr)

        if config.get("show_notification", True):
            _show_notification(
                "Claude Screenshot",
                f"Saved! Path copied to clipboard.\n{os.path.basename(capture_result.path)}",
            )
    else:
        print("  >> Capture cancelled (ESC / right-click / region too small).", file=sys.stderr)


def _on_recapture_triggered(config: dict):
    """Called when the recapture hotkey is pressed."""
    region = load_last_region()
    if region is None:
        print("  >> No previous region saved. Falling back to interactive selector...", file=sys.stderr)
        _on_hotkey_triggered(config)
        return

    print(f"  >> Recapturing region: x={region['x']}, y={region['y']}, "
          f"{region['width']}x{region['height']}...", file=sys.stderr)

    save_dir = config["save_directory"]
    fmt = config.get("image_format", "png")

    try:
        path = recapture_region(
            x=region["x"],
            y=region["y"],
            width=region["width"],
            height=region["height"],
            save_dir=save_dir,
            fmt=fmt,
        )

        if config.get("copy_path_to_clipboard", True):
            copy_to_clipboard(path)
            print(f"  >> Recaptured: {path}", file=sys.stderr)
            print(f"  >> Path copied to clipboard! Paste into Claude Code with Ctrl+V", file=sys.stderr)
        else:
            print(f"  >> Recaptured: {path}", file=sys.stderr)

        if config.get("show_notification", True):
            _show_notification(
                "Claude Screenshot",
                f"Recaptured! Path copied to clipboard.\n{os.path.basename(path)}",
            )
    except Exception as e:
        print(f"  >> Recapture failed: {e}", file=sys.stderr)


def run_daemon(hotkey_override: str = None, recapture_hotkey_override: str = None, debug: bool = False, replace_existing: bool = False):
    """Main daemon entry point. Uses pynput for global hotkey listening."""
    # Instance lock — prevent multiple daemons
    if replace_existing:
        # --force or --restart: safely stop the old daemon first, then start
        _stop_existing_daemon()

    if not _acquire_lock():
        print("  [!] Another claude-screenshot-daemon is already running.", file=sys.stderr)
        print(f"      PID file: {_get_pid_file()}", file=sys.stderr)
        print("      Use --restart to safely replace it.", file=sys.stderr)
        sys.exit(0)

    config = load_config()
    hotkey = hotkey_override or config.get("hotkey", "ctrl+shift+q")
    recapture_hotkey = recapture_hotkey_override or config.get("recapture_hotkey", "ctrl+alt+q")

    _show_tray_info(hotkey, recapture_hotkey, debug=debug)

    try:
        from pynput import keyboard as pynput_keyboard
    except ImportError:
        print(
            "Error: 'pynput' package is required for the hotkey daemon.\n"
            "Install it with: pip install pynput\n",
            file=sys.stderr,
        )
        sys.exit(1)

    # Parse both hotkey strings into normalized key names
    hotkey_names = _parse_hotkey_string(hotkey)
    recapture_hotkey_names = _parse_hotkey_string(recapture_hotkey)
    print(f"  Listening for capture keys:    {hotkey_names}", file=sys.stderr)
    print(f"  Listening for recapture keys:  {recapture_hotkey_names}", file=sys.stderr)
    print("", file=sys.stderr)

    # Track currently pressed normalized key names
    current_keys = set()
    capturing = False

    # Sort hotkeys by length (longer first) to avoid subset collisions
    # e.g., ctrl+alt+q should be checked before ctrl+q
    hotkey_actions = [
        (hotkey_names, _on_hotkey_triggered),
        (recapture_hotkey_names, _on_recapture_triggered),
    ]
    hotkey_actions.sort(key=lambda pair: len(pair[0]), reverse=True)

    def on_press(key):
        nonlocal capturing
        if capturing:
            return

        normalized = _normalize_key(key)
        current_keys.add(normalized)

        if debug:
            print(f"  [debug] pressed: {key} -> normalized: '{normalized}' | active: {current_keys}", file=sys.stderr)

        # Check hotkeys (longer combos first to avoid subset collisions)
        for keys, handler in hotkey_actions:
            if keys.issubset(current_keys):
                capturing = True
                current_keys.clear()

                current_config = load_config()
                handler(current_config)
                capturing = False
                break

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
  claude-screenshot-daemon                                  Use default hotkeys
  claude-screenshot-daemon --hotkey ctrl+alt+p              Custom capture hotkey (session only)
  claude-screenshot-daemon --recapture-hotkey ctrl+alt+r    Custom recapture hotkey (session only)
  claude-screenshot-daemon --set-hotkey ctrl+alt+s          Save capture hotkey to config
  claude-screenshot-daemon --set-recapture-hotkey ctrl+alt+r  Save recapture hotkey to config
  claude-screenshot-daemon --debug                          Show key presses for troubleshooting
  claude-screenshot-daemon --restart                        Safely stop existing daemon and start fresh
  claude-screenshot-daemon --stop                           Stop the running daemon
        """,
    )
    parser.add_argument(
        "--hotkey",
        type=str,
        default=None,
        help="Capture hotkey combo for this session (e.g., ctrl+shift+q, ctrl+alt+p, f9)",
    )
    parser.add_argument(
        "--set-hotkey",
        type=str,
        default=None,
        help="Save a new default capture hotkey to config and start the daemon",
    )
    parser.add_argument(
        "--recapture-hotkey",
        type=str,
        default=None,
        help="Recapture hotkey combo for this session (e.g., ctrl+alt+q)",
    )
    parser.add_argument(
        "--set-recapture-hotkey",
        type=str,
        default=None,
        help="Save a new default recapture hotkey to config and start the daemon",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Show all key presses in the terminal (for troubleshooting)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Stop the existing daemon (verified by process name) and start a new one",
    )
    parser.add_argument(
        "--restart",
        action="store_true",
        help="Safely stop the existing daemon (verified by process name) and start fresh",
    )
    parser.add_argument(
        "--stop",
        action="store_true",
        help="Stop the running daemon and exit",
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

    # --stop: safely stop the running daemon and exit
    if args.stop:
        if _stop_existing_daemon():
            print("  Daemon stopped successfully.", file=sys.stderr)
        else:
            print("  No daemon was running.", file=sys.stderr)
        sys.exit(0)

    # If --set-hotkey, save it to config first
    if args.set_hotkey:
        update_config("hotkey", args.set_hotkey)
        print(f"  Capture hotkey saved to config: {args.set_hotkey}", file=sys.stderr)

    if args.set_recapture_hotkey:
        update_config("recapture_hotkey", args.set_recapture_hotkey)
        print(f"  Recapture hotkey saved to config: {args.set_recapture_hotkey}", file=sys.stderr)

    hotkey = args.hotkey or args.set_hotkey or None
    recapture_hotkey = args.recapture_hotkey or args.set_recapture_hotkey or None
    replace_existing = args.force or args.restart
    run_daemon(hotkey_override=hotkey, recapture_hotkey_override=recapture_hotkey, debug=args.debug, replace_existing=replace_existing)


if __name__ == "__main__":
    main()
