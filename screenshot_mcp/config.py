"""
Configuration management for Claude Screenshot MCP.

Handles loading/saving user preferences (hotkey, save directory, etc.)
from a JSON config file in the user's home directory.
"""

import json
import os
import sys
from pathlib import Path
from typing import Optional


# Default configuration values
DEFAULTS = {
    "hotkey": "ctrl+shift+q",
    "recapture_hotkey": "ctrl+alt+q",
    "save_directory": "",  # Empty = use temp directory
    "image_format": "png",
    "show_notification": True,
    "copy_path_to_clipboard": True,
    "auto_paste_path": False,
    "overlay_color": "#00aaff",
    "overlay_opacity": 0.3,
}


def get_config_dir() -> Path:
    """Get the configuration directory path."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))

    config_dir = base / "claude-screenshot-mcp"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def get_config_path() -> Path:
    """Get the configuration file path."""
    return get_config_dir() / "config.json"


def get_screenshots_dir() -> Path:
    """Get the default screenshots directory."""
    screenshots_dir = get_config_dir() / "screenshots"
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    return screenshots_dir


def load_config() -> dict:
    """Load configuration from disk, merging with defaults."""
    config = DEFAULTS.copy()
    config_path = get_config_path()

    if config_path.exists():
        try:
            with open(config_path, "r") as f:
                user_config = json.load(f)
            config.update(user_config)
        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Could not load config from {config_path}: {e}", file=sys.stderr)

    # Resolve save directory — default to system temp folder
    if not config["save_directory"]:
        import tempfile
        config["save_directory"] = tempfile.gettempdir()

    return config


def save_config(config: dict) -> None:
    """Save configuration to disk."""
    config_path = get_config_path()
    try:
        with open(config_path, "w") as f:
            json.dump(config, f, indent=2)
    except IOError as e:
        print(f"Warning: Could not save config to {config_path}: {e}", file=sys.stderr)


def update_config(key: str, value) -> dict:
    """Update a single configuration value and save."""
    config = load_config()
    if key in DEFAULTS:
        config[key] = value
        save_config(config)
    else:
        raise ValueError(f"Unknown config key: {key}. Valid keys: {list(DEFAULTS.keys())}")
    return config


def _get_last_region_path() -> Path:
    """Get the path to the last_region.json file."""
    return get_config_dir() / "last_region.json"


def save_last_region(x: int, y: int, width: int, height: int) -> None:
    """Save the last captured region coordinates to disk."""
    region_path = _get_last_region_path()
    try:
        with open(region_path, "w") as f:
            json.dump({"x": x, "y": y, "width": width, "height": height}, f)
    except IOError as e:
        print(f"Warning: Could not save last region to {region_path}: {e}", file=sys.stderr)


def load_last_region() -> Optional[dict]:
    """Load the last captured region coordinates from disk.

    Returns:
        Dict with x, y, width, height keys, or None if not available.
    """
    region_path = _get_last_region_path()
    if not region_path.exists():
        return None

    try:
        with open(region_path, "r") as f:
            data = json.load(f)
        # Validate required keys
        required = {"x", "y", "width", "height"}
        if not required.issubset(data.keys()):
            return None
        # Validate values are integers. x/y can be negative (monitors
        # left of or above the primary monitor have negative coordinates).
        for key in required:
            if not isinstance(data[key], int):
                return None
        if data["width"] < 1 or data["height"] < 1:
            return None
        return data
    except (json.JSONDecodeError, IOError, ValueError):
        return None
