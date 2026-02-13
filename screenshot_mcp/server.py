#!/usr/bin/env python3
"""
MCP Server for Claude Screenshot.

Provides tools for Claude Code to capture screen regions interactively
or capture the full screen. Screenshots are saved to disk and the file
path is returned so Claude Code can reference the image.
"""

import json
import os
import sys
import subprocess
import threading
from typing import Optional
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field, ConfigDict

from .config import load_config, update_config, get_screenshots_dir, DEFAULTS
from .capture import (
    select_region_and_capture,
    capture_full_screen,
    capture_region,
    save_screenshot,
    copy_to_clipboard,
)

# Initialize MCP server
mcp = FastMCP("screenshot_mcp")


# ──────────────────────────────────────────────
# Input Models
# ──────────────────────────────────────────────

class CaptureRegionInput(BaseModel):
    """Input for interactive region capture."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    save_directory: Optional[str] = Field(
        default=None,
        description=(
            "Directory to save the screenshot. "
            "If not specified, uses the configured default directory."
        ),
    )
    filename: Optional[str] = Field(
        default=None,
        description=(
            "Custom filename for the screenshot (e.g., 'my_capture.png'). "
            "If not specified, a timestamp-based name is generated."
        ),
    )


class CaptureFullScreenInput(BaseModel):
    """Input for full screen capture."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    save_directory: Optional[str] = Field(
        default=None,
        description="Directory to save the screenshot.",
    )
    filename: Optional[str] = Field(
        default=None,
        description="Custom filename for the screenshot.",
    )


class CaptureCoordinatesInput(BaseModel):
    """Input for capturing a specific screen region by coordinates."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    x: int = Field(..., description="Left coordinate of the region (pixels)", ge=0)
    y: int = Field(..., description="Top coordinate of the region (pixels)", ge=0)
    width: int = Field(..., description="Width of the region (pixels)", ge=1)
    height: int = Field(..., description="Height of the region (pixels)", ge=1)
    save_directory: Optional[str] = Field(default=None, description="Directory to save the screenshot.")
    filename: Optional[str] = Field(default=None, description="Custom filename.")


class UpdateConfigInput(BaseModel):
    """Input for updating a configuration value."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    key: str = Field(
        ...,
        description=(
            f"Configuration key to update. Valid keys: {list(DEFAULTS.keys())}"
        ),
    )
    value: str = Field(
        ...,
        description="New value for the configuration key (as a string; booleans as 'true'/'false').",
    )


class GetLatestInput(BaseModel):
    """Input for getting the latest screenshot."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    count: int = Field(
        default=1,
        description="Number of recent screenshots to list",
        ge=1,
        le=20,
    )


# ──────────────────────────────────────────────
# Tools
# ──────────────────────────────────────────────

@mcp.tool(
    name="screenshot_capture_region",
    annotations={
        "title": "Capture Screen Region",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
async def screenshot_capture_region(params: CaptureRegionInput) -> str:
    """Launch an interactive screen region selector and capture the selected area.

    Opens a fullscreen transparent overlay where the user can click and drag
    to select a rectangular region. The selected area is captured as a PNG
    screenshot and saved to disk. Press Escape to cancel.

    Args:
        params (CaptureRegionInput): Parameters containing:
            - save_directory (Optional[str]): Where to save the screenshot
            - filename (Optional[str]): Custom filename

    Returns:
        str: JSON with the file path of the captured screenshot, or error message.

        Success: {"status": "ok", "path": "/path/to/screenshot.png", "message": "Screenshot saved!"}
        Cancelled: {"status": "cancelled", "message": "Selection was cancelled by user."}
        Error: {"status": "error", "message": "Error description"}
    """
    try:
        config = load_config()
        save_dir = params.save_directory or config["save_directory"]

        # Run the region selector (this blocks until user finishes selecting)
        # We need to run it in a thread since tkinter needs the main thread on some platforms
        result_holder = {"path": None, "error": None}

        def run_capture():
            try:
                result_holder["path"] = select_region_and_capture(
                    save_dir=save_dir,
                    fmt=config.get("image_format", "png"),
                    overlay_color=config.get("overlay_color", "#00aaff"),
                    overlay_opacity=config.get("overlay_opacity", 0.3),
                )
            except Exception as e:
                result_holder["error"] = str(e)

        # Use subprocess to launch the capture in a separate process
        # This avoids tkinter main thread issues
        capture_script = _build_capture_command(save_dir, config)
        proc = subprocess.run(
            [sys.executable, "-c", capture_script],
            capture_output=True,
            text=True,
            timeout=120,
        )

        if proc.returncode != 0:
            return json.dumps({
                "status": "error",
                "message": f"Capture process failed: {proc.stderr.strip()}",
            })

        path = proc.stdout.strip()
        if not path or path == "None" or path == "CANCELLED":
            return json.dumps({
                "status": "cancelled",
                "message": "Selection was cancelled by the user.",
            })

        # Optionally copy path to clipboard
        if config.get("copy_path_to_clipboard", True):
            copy_to_clipboard(path)

        return json.dumps({
            "status": "ok",
            "path": path,
            "message": f"Screenshot saved! You can reference it at: {path}",
        })

    except subprocess.TimeoutExpired:
        return json.dumps({
            "status": "error",
            "message": "Region selection timed out after 120 seconds.",
        })
    except Exception as e:
        return json.dumps({"status": "error", "message": f"Unexpected error: {e}"})


@mcp.tool(
    name="screenshot_capture_fullscreen",
    annotations={
        "title": "Capture Full Screen",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
async def screenshot_capture_fullscreen(params: CaptureFullScreenInput) -> str:
    """Capture the entire screen (all monitors) and save as an image.

    Args:
        params (CaptureFullScreenInput): Parameters containing:
            - save_directory (Optional[str]): Where to save
            - filename (Optional[str]): Custom filename

    Returns:
        str: JSON with file path or error message.
    """
    try:
        config = load_config()
        save_dir = params.save_directory or config["save_directory"]
        image = capture_full_screen()
        path = save_screenshot(
            image,
            save_dir=save_dir,
            filename=params.filename,
            fmt=config.get("image_format", "png"),
        )

        if config.get("copy_path_to_clipboard", True):
            copy_to_clipboard(path)

        return json.dumps({
            "status": "ok",
            "path": path,
            "message": f"Full screen captured! Path: {path}",
        })
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})


@mcp.tool(
    name="screenshot_capture_coordinates",
    annotations={
        "title": "Capture Screen Coordinates",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def screenshot_capture_coordinates(params: CaptureCoordinatesInput) -> str:
    """Capture a specific rectangular region of the screen by coordinates.

    Useful when you already know the exact coordinates of what you want to capture.

    Args:
        params (CaptureCoordinatesInput): Parameters containing:
            - x (int): Left pixel coordinate
            - y (int): Top pixel coordinate
            - width (int): Width in pixels
            - height (int): Height in pixels
            - save_directory (Optional[str]): Where to save
            - filename (Optional[str]): Custom filename

    Returns:
        str: JSON with file path or error message.
    """
    try:
        config = load_config()
        save_dir = params.save_directory or config["save_directory"]
        image = capture_region(params.x, params.y, params.width, params.height)
        path = save_screenshot(
            image,
            save_dir=save_dir,
            filename=params.filename,
            fmt=config.get("image_format", "png"),
        )

        if config.get("copy_path_to_clipboard", True):
            copy_to_clipboard(path)

        return json.dumps({
            "status": "ok",
            "path": path,
            "message": f"Region captured! Path: {path}",
        })
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})


@mcp.tool(
    name="screenshot_get_latest",
    annotations={
        "title": "Get Latest Screenshots",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def screenshot_get_latest(params: GetLatestInput) -> str:
    """Get the file path(s) of the most recently captured screenshot(s).

    Scans the screenshots directory and returns the most recent files,
    sorted by modification time.

    Args:
        params (GetLatestInput): Parameters containing:
            - count (int): How many recent screenshots to return (1-20)

    Returns:
        str: JSON with list of screenshot paths or message if none found.
    """
    config = load_config()
    save_dir = config["save_directory"]

    if not os.path.isdir(save_dir):
        return json.dumps({
            "status": "ok",
            "screenshots": [],
            "message": "No screenshots directory found.",
        })

    # List image files sorted by modification time (newest first)
    image_extensions = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
    files = []
    for f in Path(save_dir).iterdir():
        if f.is_file() and f.suffix.lower() in image_extensions:
            files.append((f, f.stat().st_mtime))

    files.sort(key=lambda x: x[1], reverse=True)
    latest = [str(f.resolve()) for f, _ in files[: params.count]]

    if not latest:
        return json.dumps({
            "status": "ok",
            "screenshots": [],
            "message": "No screenshots found in the screenshots directory.",
        })

    return json.dumps({
        "status": "ok",
        "screenshots": latest,
        "message": f"Found {len(latest)} recent screenshot(s).",
    })


@mcp.tool(
    name="screenshot_get_config",
    annotations={
        "title": "Get Screenshot Config",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def screenshot_get_config() -> str:
    """Get the current screenshot plugin configuration.

    Returns all current settings including hotkey, save directory,
    image format, and overlay appearance.

    Returns:
        str: JSON with current configuration values.
    """
    config = load_config()
    return json.dumps({"status": "ok", "config": config}, indent=2)


@mcp.tool(
    name="screenshot_update_config",
    annotations={
        "title": "Update Screenshot Config",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def screenshot_update_config(params: UpdateConfigInput) -> str:
    """Update a configuration setting for the screenshot plugin.

    Allows changing the hotkey, save directory, image format,
    and other preferences.

    Args:
        params (UpdateConfigInput): Parameters containing:
            - key (str): Config key to update
            - value (str): New value

    Returns:
        str: JSON confirming the update.
    """
    try:
        # Parse boolean values
        value = params.value
        if value.lower() in ("true", "false"):
            value = value.lower() == "true"
        elif value.isdigit():
            value = int(value)
        else:
            try:
                value = float(value)
            except ValueError:
                pass  # Keep as string

        config = update_config(params.key, value)
        return json.dumps({
            "status": "ok",
            "message": f"Updated '{params.key}' to '{value}'.",
            "config": config,
        })
    except ValueError as e:
        return json.dumps({"status": "error", "message": str(e)})


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _build_capture_command(save_dir: str, config: dict) -> str:
    """Build a Python script string to run the capture in a subprocess.

    This is needed because tkinter requires the main thread and the MCP
    server runs async, so we launch capture in a separate process.
    """
    fmt = config.get("image_format", "png")
    color = config.get("overlay_color", "#00aaff")
    opacity = config.get("overlay_opacity", 0.3)

    return f"""
import sys
sys.path.insert(0, r'{os.path.dirname(os.path.dirname(os.path.abspath(__file__)))}')
from screenshot_mcp.capture import select_region_and_capture
result = select_region_and_capture(
    save_dir=r'{save_dir}',
    fmt='{fmt}',
    overlay_color='{color}',
    overlay_opacity={opacity},
)
print(result if result else 'CANCELLED')
"""


# ──────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────

def main():
    """Run the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
