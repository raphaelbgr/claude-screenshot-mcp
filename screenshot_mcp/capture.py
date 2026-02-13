"""
Screen capture module with region selection overlay.

Provides a full-screen transparent overlay where the user can click and drag
to select a rectangular region. The selected region is then captured as a
screenshot and saved to disk.
"""

import datetime
import os
import sys
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Tuple

# We use mss for fast multi-monitor screen capture
# and Pillow for image processing/cropping
try:
    import mss
    import mss.tools
except ImportError:
    mss = None

try:
    from PIL import Image
except ImportError:
    Image = None


def _ensure_dependencies():
    """Check that required dependencies are available."""
    missing = []
    if mss is None:
        missing.append("mss")
    if Image is None:
        missing.append("Pillow")
    if missing:
        raise ImportError(
            f"Missing required packages: {', '.join(missing)}. "
            f"Install them with: pip install {' '.join(missing)}"
        )


def capture_full_screen() -> "Image.Image":
    """Capture the entire virtual screen (all monitors)."""
    _ensure_dependencies()
    with mss.mss() as sct:
        # Grab the full virtual screen (all monitors combined)
        monitor = sct.monitors[0]  # 0 = entire virtual screen
        screenshot = sct.grab(monitor)
        return Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")


def capture_region(x: int, y: int, width: int, height: int) -> "Image.Image":
    """Capture a specific region of the screen.

    Args:
        x: Left coordinate
        y: Top coordinate
        width: Width of the region
        height: Height of the region

    Returns:
        PIL Image of the captured region
    """
    _ensure_dependencies()
    with mss.mss() as sct:
        region = {"left": x, "top": y, "width": width, "height": height}
        screenshot = sct.grab(region)
        return Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")


def save_screenshot(
    image: "Image.Image",
    save_dir: Optional[str] = None,
    filename: Optional[str] = None,
    fmt: str = "png",
) -> str:
    """Save a screenshot image to disk.

    Args:
        image: PIL Image to save
        save_dir: Directory to save to (default: temp dir)
        filename: Custom filename (default: timestamp-based)
        fmt: Image format (png, jpg, webp)

    Returns:
        Absolute path to the saved file
    """
    if save_dir is None:
        save_dir = tempfile.gettempdir()

    Path(save_dir).mkdir(parents=True, exist_ok=True)

    if filename is None:
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        filename = f"claude_screenshot_{timestamp}.{fmt}"

    filepath = os.path.join(save_dir, filename)
    image.save(filepath, fmt.upper())
    return os.path.abspath(filepath)


def select_region_and_capture(
    save_dir: Optional[str] = None,
    fmt: str = "png",
    overlay_color: str = "#00aaff",
    overlay_opacity: float = 0.3,
) -> Optional[str]:
    """Launch interactive region selector overlay, capture the selected area.

    Opens a transparent fullscreen overlay. User clicks and drags to select
    a region. On release, that region is captured and saved.

    Press Escape to cancel.

    Args:
        save_dir: Where to save the screenshot
        fmt: Image format
        overlay_color: Color of the selection rectangle
        overlay_opacity: Opacity of the dimmed overlay

    Returns:
        File path of the saved screenshot, or None if cancelled
    """
    _ensure_dependencies()

    # Import tkinter here to avoid issues when running as MCP server
    import tkinter as tk

    result = {"path": None}

    # First, take a screenshot of the entire screen BEFORE showing the overlay
    # This way the overlay itself won't appear in the final capture
    full_screenshot = capture_full_screen()

    root = tk.Tk()
    root.title("Claude Screenshot - Select Region")
    root.attributes("-fullscreen", True)
    root.attributes("-topmost", True)
    root.attributes("-alpha", overlay_opacity)
    root.configure(bg="black")
    root.config(cursor="crosshair")

    # Force the window to grab focus so ESC works immediately
    root.focus_force()
    root.grab_set()

    canvas = tk.Canvas(root, highlightthickness=0, bg="black")
    canvas.pack(fill=tk.BOTH, expand=True)

    # Add ESC hint text in the center
    canvas.create_text(
        root.winfo_screenwidth() // 2,
        root.winfo_screenheight() // 2,
        text="Click and drag to select a region  |  Press ESC to cancel",
        fill="white",
        font=("Arial", 16),
    )

    # State for drag selection
    state = {"start_x": 0, "start_y": 0, "rect_id": None, "selecting": False}

    def on_press(event):
        state["start_x"] = event.x_root
        state["start_y"] = event.y_root
        state["selecting"] = True

    def on_drag(event):
        if not state["selecting"]:
            return
        if state["rect_id"]:
            canvas.delete(state["rect_id"])

        # Convert root coords to canvas coords
        cx1 = state["start_x"] - root.winfo_rootx()
        cy1 = state["start_y"] - root.winfo_rooty()
        cx2 = event.x_root - root.winfo_rootx()
        cy2 = event.y_root - root.winfo_rooty()

        state["rect_id"] = canvas.create_rectangle(
            cx1, cy1, cx2, cy2,
            outline=overlay_color,
            width=2,
            fill=overlay_color,
            stipple="gray25",
        )

    def on_release(event):
        if not state["selecting"]:
            return
        state["selecting"] = False

        x1 = min(state["start_x"], event.x_root)
        y1 = min(state["start_y"], event.y_root)
        x2 = max(state["start_x"], event.x_root)
        y2 = max(state["start_y"], event.y_root)

        width = x2 - x1
        height = y2 - y1

        root.grab_release()
        root.destroy()

        if width < 5 or height < 5:
            # Too small, treat as a cancelled selection
            return

        # Crop the pre-captured full screenshot
        cropped = full_screenshot.crop((x1, y1, x2, y2))
        result["path"] = save_screenshot(cropped, save_dir=save_dir, fmt=fmt)

    def on_escape(event):
        root.grab_release()
        root.destroy()

    # Also handle right-click as cancel
    def on_right_click(event):
        root.grab_release()
        root.destroy()

    root.bind("<ButtonPress-1>", on_press)
    root.bind("<B1-Motion>", on_drag)
    root.bind("<ButtonRelease-1>", on_release)
    root.bind("<Escape>", on_escape)
    root.bind("<ButtonPress-3>", on_right_click)

    root.mainloop()
    return result["path"]


def copy_to_clipboard(text: str) -> bool:
    """Copy text to system clipboard.

    Returns True if successful.
    """
    try:
        if sys.platform == "win32":
            # Use clip.exe on Windows
            process = subprocess.Popen(
                ["clip"],
                stdin=subprocess.PIPE,
                shell=True,
            )
            process.communicate(text.encode("utf-16le"))
            return process.returncode == 0
        elif sys.platform == "darwin":
            process = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
            process.communicate(text.encode("utf-8"))
            return process.returncode == 0
        else:
            # Try xclip or xsel on Linux
            for cmd in [["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]]:
                try:
                    process = subprocess.Popen(cmd, stdin=subprocess.PIPE)
                    process.communicate(text.encode("utf-8"))
                    if process.returncode == 0:
                        return True
                except FileNotFoundError:
                    continue
        return False
    except Exception:
        return False
